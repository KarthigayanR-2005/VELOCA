# VELOCA design notes: the velocity-adaptive algorithm

This document didn't exist before Phase 3 — the Phase 3 brief assumed it
did ("read CLAUDE.md and docs/... especially the velocity-adaptive
algorithm"). It's written now, describing what was actually specified and
built, so it's real going forward instead of assumed.

## The problem this solves

A full causal search (PCMCI) is accurate but slow — tens of seconds on
even a small window. A network mid-flash-surge doesn't hold still that
long: by the time PCMCI finishes, the surge may have already passed. A
cheap pairwise Granger test is fast (milliseconds) but cruder and more
prone to spurious edges. VELOCA's causal engine picks between them based
on how fast the network is currently changing, rather than always using
one or the other.

## Velocity: how fast is the network changing right now?

1. Sum `offered_load_mbps` across all 6 nodes → aggregate load `L(t)`.
2. `baseline` = median of `L(t)` over a calm reference window (the first
   `CALM_WINDOW_S` seconds of whatever window is being analyzed — 30s by
   default).
3. Normalize: `L_norm(t) = L(t) / baseline`.
4. At 1s sample spacing, the first difference *is* the derivative:
   `raw(t) = |L_norm(t) - L_norm(t-1)|`.
5. Smooth with an EMA: `v(t) = α·raw(t) + (1-α)·v(t-1)`, `α = 0.3`.

## Mode selection: hysteresis, not a single threshold

A single threshold (`v > 0.4 → fast path`) would flap the mode back and
forth every sample whenever `v` sits near the boundary — noise, not signal.
Instead:

- Once **slow**, switch to **fast** only when `v` rises above `V_HIGH =
  0.4`.
- Once **fast**, switch back to **slow** only when `v` drops below `V_LOW
  = 0.15`.
- Anywhere between `V_LOW` and `V_HIGH`, the mode doesn't change on its
  own — that dead zone is what prevents flapping.

Verified directly in `causal-engine/tests/test_velocity.py`: a synthetic
`v(t)` series that oscillates between 0.36 and 0.45 (straddling `V_HIGH`,
never dropping near `V_LOW`) stays in "fast" mode for its entire
oscillation — exactly 2 mode transitions for the whole run, not one per
oscillation.

## Fast path vs. slow path

| | Fast (Granger) | Slow (PCMCI) |
|---|---|---|
| Method | Pairwise Granger causality, `statsmodels` | PCMCI (Tigramite), ParCorr test |
| Max lag | `tau_max=3` | `tau_max=10` |
| Cost | O(vars²) independent pairwise tests | Joint conditional-independence search |
| Measured runtime (30 vars, 60s window) | ~3.3s | ~51s |

Both return a `networkx.DiGraph` with the same shape (edge = `source ->
target`, `weight`, `p_value`), so root-cause ranking and the counterfactual
validator don't need to know which path produced the graph.

## Background refinement

A **fast**-path diagnosis is returned immediately, but also schedules a
**slow**-path re-run of the *same window* in the background. If the slow
path's top root cause disagrees with the fast path's, the stored verdict
is revised in place (`revised: true`, with the slow result attached as
`revision`) — fetchable later via `GET /diagnose/{id}`. This was the
point of splitting "answer now" from "verify later" rather than just
always waiting for PCMCI: get an instant (if cruder) answer, upgrade it
quietly if a better one becomes available.

Verified live: a fast-path diagnosis on the Phase 2 surge window
initially reported `n4` as top root cause; ~51s later the background slow
path finished, disagreed (reported `n1`), and the stored verdict updated
to `revised: true` with `revision_note: "background slow path disagreed:
fast said 'n4', slow says 'n1'"`.

## Root-cause ranking

Given the causal graph and the window, a metric is **degraded** if its
back half (`BASELINE_FRACTION=0.5` split) deviates more than
`Z_SCORE_THRESHOLD=3.0` standard deviations above its own front half
("recent baseline" vs. "calm baseline" — this is why a diagnosis window
should end soon after the event of interest, with roughly half the
window being calm beforehand).

Only `latency_ms` and `packet_loss_pct` columns are checked (not
`throughput_mbps` or `queue_depth` — those rise/fall with legitimate load,
not just trouble). Every graph node is scored by:

```
score = (edges pointing INTO degraded variables)
       - (edges pointing IN FROM degraded variables)
       + earliness bonus (if this variable is itself degraded and was
         first to cross the anomaly threshold)
```

High score = upstream of the trouble, not caused by it. Candidates are
collapsed one-per-node (best-scoring column wins) and returned top-3.

## Counterfactual validation

The proposed remediation is always the same shape: cap the top root
cause's `offered_load_mbps` back to its topology baseline. DoWhy estimates
the causal effect of that node's load on the *target* node's latency via
`backdoor.linear_regression`, which gives a **per-unit** effect
(`d(latency)/d(load)`). That's translated into a **p95 latency**
prediction by shifting every sample of the observed outcome by
`effect_per_unit × (cap_value − observed_load)` and comparing the
resulting p95 to the actual one — a simple way to get a p95-level answer
out of a mean-effect estimator.

An action is **approved** only if:
1. a causal path from the capped node's load to the target's latency
   exists in the discovered graph at all (no path → immediate rejection,
   no DoWhy call needed — there's no claim to test), and
2. the predicted p95 improvement is ≥ `MIN_GAIN` (10%) of the current p95,
   and
3. a placebo-treatment refuter (label shuffled) doesn't find a comparably
   large "effect" from noise alone.

One practical wrinkle discovered while wiring this up: Granger/PCMCI
graphs are **not** guaranteed acyclic (mutual A↔B edges are common), but
DoWhy's identifier requires a DAG. `validate.py` resolves this by keeping
only the stronger-evidence direction of any mutual pair before handing the
graph to DoWhy — naively breaking an arbitrary cycle (picking whichever
one `networkx.find_cycle` happens to return first) risks discarding a
strong direct edge instead of a weak indirect one in a dense graph.

## What Phase 3 actually validated

Running `make surge` (Phase 2's demo: a 3.5x spike on n1+n4, with a 15%
loss fault on n2-n3 five seconds in) and diagnosing the resulting window
confirmed:
- top root cause: `n1` (n4 close behind) — the correct bottleneck.
- the proposed action (cap n1's load to its 120 Mbps baseline) was
  **approved**, with a large predicted p95 latency improvement.
- a nonsense action (cap an uninvolved node, e.g. n6, targeting n1's
  latency) was **rejected** — no causal path in the discovered graph.
- fast and slow paths can disagree on the exact top-1 node (varies run to
  run) even while agreeing on the top-3 set — which is precisely what the
  background-refinement mechanism exists to catch and correct.

`experiments/validate_phase3.py` runs this systematically against every
fault logged in `ground_truth.jsonl`: **4/4 testable faults correctly
diagnosed** (top-3 match; a concurrent load spike's targets count as an
equally-correct answer, since `make surge` always fires both together and
the spike is usually the dominant effect). A handful of older log entries
from before Prometheus got a persistent volume (an infra fix made partway
through this phase) are skipped rather than counted as failures — their
underlying metric history no longer exists, which is a data-availability
gap, not a wrong diagnosis.

## Phase 4: closing the loop

No "Chapter 5" or loop diagram existed before this phase either (Phase 3's
brief made the same assumption about this file that Phase 4's did — see
the note at the top of this document). Here's the actual loop, as built:

```
   Prometheus  <---- metrics ---- agents (n1..n6)
       |
       | polled every --interval (watch.py, off by default)
       v
  [detect]  find_degraded() — same z-score check as rootcause.py
       |  (only if something crosses the threshold)
       v
  [settle]  wait --settle-before-diagnose — a fresh trigger has almost no
       |    incident data yet; even the fast path needs a few overload
       |    samples to find a lagged relationship reliably
       v
  [diagnose]  POST /diagnose (mode=fast, auto_execute=true)
       |      velocity -> discovery -> rank root causes (severity-
       |      weighted) -> try top-3 in order -> DoWhy validates each ->
       |      first approved one wins
       v
  [execute]  causal-engine calls control-plane's POST /execute
       |     control-plane re-checks approved==true itself (defense in
       |     depth), publishes veloca.action.<node>, logs actions.jsonl
       v
  [obey]  agent clamps its own offered load to cap_mbps for duration_s,
       |  then releases back to the load generator/baseline
       v
  [verify]  after settle_s, POST /verify/{action_id} — pull a fresh
             window, compare the target metric against its pre-incident
             baseline, classify recovered / partial / not_recovered.
             not_recovered -> escalation event, not a silent retry.
```

A **fast**-mode diagnosis (which is what watch.py always requests) also
still schedules the existing Phase 3 background slow-path re-run of the
same window — that mechanism didn't change, it just now sits underneath
an auto-executing verdict instead of a purely advisory one.

### Why the action is temporary, and what that revealed

`cap_offered_load` clamps a node's external load for `duration_s` (30s
default) and then releases it — it does not touch the load generator or
chaos fault that's still trying to push the original values. This is
deliberate: the action addresses the *node's* behavior, not the demand
being placed on it. Against `make surge`'s original 26s profile this
rarely mattered (the cap outlasted the surge). Against a longer, more
realistic surge it does: the first live run against a 66s spike showed
the capped node's latency snap back to baseline within 2 seconds of the
cap taking effect, hold there for the full 30s window, then resurge the
moment the cap expired — because the load generator was still trying to
push 3.5x baseline for another 30+ seconds. Watch mode's own poll cadence
(bounded below by settle + diagnosis + verify time, each several to tens
of seconds) didn't happen to land another detection cycle during that
resurgence in this run, so it went unaddressed until the surge's own
profile ended naturally.

This is reported as a real, observed limitation, not smoothed over: a
single one-shot action provides genuine, measurable relief while it's
active, but isn't a durable fix against a *persistently renewing* load on
its own — durable suppression would need either a longer `duration_s`
tied to how long the underlying anomaly is expected to last, or a watch
loop fast enough to reliably re-trigger before an expired cap's problem
resurges. Neither is implemented; both are natural Phase 5 material.

### The recovery-time comparison

Two identical scenarios — `loadgen --profile spike --target n1,n4
--amplitude 3.5 --rise 3s --plateau 60s --fall 3s --seed 42`, no
concurrent chaos fault (isolates the loop's response to the actual
overload from an unrelated fault competing for root-cause ranking) — one
with `watch.py` running, one without:

| | With the loop | Without (control) |
|---|---|---|
| n4 latency leaves baseline | t+3s (ramp begins) | t+3s (ramp begins) |
| n4 latency peaks | ~719ms (t+13-21s) | ~746ms (t+59-65s) |
| **n4 latency back near baseline** | **t+23s** (cap takes effect) | **t+69s** (surge's own profile ends) |
| Mechanism | automatic detect->diagnose->execute, ~46s faster | none — waits out the full 60s plateau |

Both trajectories pulled directly from Prometheus range queries over the
live run (not the `/verify` endpoint's single post-hoc check) — the
control run's n4 latency sits continuously in the 600-750ms band for the
entire plateau with zero relief, confirming the with-loop drop at t+23s
is attributable to the executed action and not coincidental timing.

### Safety

- A calm-baseline window with `auto_execute=true`: no degraded metric
  found -> `approved=False` -> `execution: {"executed": false, "reason":
  "verdict not approved, execution skipped"}` -> nothing published to any
  agent. Observed live and repeatedly (watch mode's own false-trigger
  cycles during this phase's debugging all correctly executed nothing).
- `POST /execute` independently refuses a hand-crafted `{"approved":
  false, ...}` verdict sent directly — control-plane doesn't just trust
  causal-engine's judgment, it re-checks.
- The Phase 3 nonsense-action test (cap an uninvolved node) still holds:
  `validate_action` rejects for lack of a causal path regardless of who's
  calling it.

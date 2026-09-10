# VELOCA — Velocity-Adaptive Causal Discovery for Self-Healing Networks Under Flash-Surge Traffic

Solo final-year project. VELOCA simulates a small mesh network, learns causal
relationships between node/link metrics as traffic surges hit it, and uses
that causal model to decide how to reroute traffic and heal itself faster
than a reactive (non-causal) baseline would.

## Why "velocity-adaptive"

Flash surges change the network's dynamics faster than fixed-window causal
discovery can track. VELOCA's causal engine is meant to adapt its discovery
window/rate to the *velocity* of change in the traffic, not just react to
absolute thresholds. That adaptive piece is future work (Phase 3+) — Phase 1
only builds the substrate it will run on.

## Phases

1. **Foundation** — repo skeleton, a living simulated network with no AI:
   topology definition, per-node agents publishing noisy-but-stable metrics
   over NATS, a control-plane tracking node liveness/state, Prometheus +
   Grafana visualizing it. Everything runs via `docker compose up`.
2. **Flash-surge injection (this step)** — agents now run a real per-node
   queueing simulation instead of noise-around-baseline, so load actually
   causes congestion; `loadgen/` drives synthetic traffic profiles and
   `chaos/` injects faults (kill/latency/loss), both logged as ground truth
   for later evaluation. See "Phase 2: load & fault model" below.
3. **Causal discovery engine (this step)** — `causal-engine` (Python/
   FastAPI) watches how fast the network is changing and picks a fast
   (Granger) or slow (PCMCI) discovery path accordingly, ranks root causes,
   proposes a remediation, and validates it counterfactually via DoWhy —
   all standalone over HTTP, not yet wired into the control plane. See
   "Phase 3: the causal engine" below and `docs/design.md` for the full
   algorithm writeup.
4. **Self-healing control loop (this step)** — agents obey a `cap_offered_
   load` action; control-plane executes approved verdicts against them and
   logs every action; `watch.py` polls for degradation and drives the full
   detect→diagnose→validate→execute→verify loop with no manual step,
   off by default. See "Phase 4: closing the loop" below.
5. **Velocity-adaptive tuning + evaluation** — adapt the causal discovery
   window/cadence to observed traffic velocity; run experiments comparing
   self-healing vs. a non-causal reactive baseline; write up results in
   `docs/`.

## Tech stack

- `control-plane/` — Go. Loads `infra/topology.yaml`, tracks node/agent
  state from NATS traffic, later issues reroute commands. Exposes an HTTP
  API for status/inspection.
- `agent/` — Go. One process per simulated network node. Runs the queueing
  simulation described below, publishes the resulting metrics over NATS,
  and exposes them in Prometheus format. Reacts to load/chaos/action
  commands (see Phase 2 section).
- `loadgen/` — Go CLI. Drives a synthetic traffic profile (spike/ramp/
  plateau-only) against one or more nodes.
- `chaos/` — Go CLI. Injects one fault (kill/latency/loss) at a time.
- `causal-engine/` — Python 3.11 + FastAPI. Uses `tigramite` (PCMCI),
  `dowhy`, `statsmodels` (fast-path Granger), `causal-learn` (installed,
  not yet used — PCMCI/Granger cover discovery so far). Standalone HTTP
  service, not wired into the control plane yet (Phase 4). See "Phase 3"
  below and `docs/design.md`.
- `infra/` — Docker Compose, Prometheus config, Grafana provisioning +
  dashboards, `topology.yaml` (shared network definition read by both Go
  services).
- `experiments/logs/` — `load_<timestamp>.json` (exact profile a loadgen run
  sent) and `ground_truth.jsonl` (every chaos fault ever fired, one JSON
  object per line) — the answer key later evaluation compares detections
  against. Both are generated, not hand-written; don't edit them.
- `experiments/validate_phase3.py` — calls `/diagnose` on each
  ground-truth fault's window and checks the reported root cause against
  it (also accounting for a concurrent load spike, since `make surge`
  fires one alongside the chaos fault — see Phase 3 section).
- `docs/` — write-up material for the final report; `docs/design.md` is
  the actual design doc (velocity-adaptive algorithm, mode selection,
  root-cause ranking, counterfactual validation).

Messaging (NATS subjects):
- `veloca.register` — agent liveness heartbeat.
- `veloca.metrics.<node_id>` — an agent's per-tick metrics.
- `veloca.load.<node_id>` — loadgen overrides a node's external offered load.
- `veloca.flow.<node_id>` — one neighbor telling this node how much traffic
  it just forwarded to it (cross-traffic propagation, see below).
- `veloca.chaos.<node_id>` — chaos fires a kill/latency/loss fault.
- `veloca.action.<node_id>` — control-plane publishes an executed action
  here (currently only `cap_offered_load`); the agent obeys it and logs
  before/after offered load (see Phase 4 section).

Metrics: Prometheus + Grafana. Everything runs via a single
`docker compose up` from `infra/`.

## Phase 2: load & fault model

Each agent runs a small queueing simulation every 1s tick instead of just
adding noise to a baseline:

- **Capacity**: a node's capacity is the *minimum* bandwidth over its
  attached links (its bottleneck link) — see `infra/topology.yaml`. Every
  node's weakest link is its diagonal (250 Mbps vs. 400 Mbps on the ring),
  so the diagonal is always the constraining link.
- **Queueing**: `served = min(offered, capacity)`; the backlog
  (`queue_depth`) builds while overloaded and decays exponentially once
  under capacity again, clamped to a max.
- **Latency**: `base_latency + M/M/1-style util term + queue_depth*factor +
  injected_latency` — rises sharply as utilisation approaches 1.
- **Loss**: rises once the queue is close to full (overflow), plus any
  injected link loss.
- **Cross-traffic propagation**: each node forwards `spilloverFraction`
  (20%) of what it served to each neighbor over `veloca.flow.<neighbor>`;
  a neighbor folds inbound flows into its own offered load next tick. This
  means steady-state throughput is naturally somewhat above each node's
  raw `baseline.throughput_mbps` (own traffic + relayed cross-traffic) —
  that's expected, not a bug. Injected link loss (`chaos loss <a>-<b>`)
  reduces what the sending node (`a`) delivers to its neighbor (`b`),
  which is real but can be a small fraction of a busy node's total inbound
  if that node also receives a lot of traffic from other neighbors — check
  the specific inbound flow, not just aggregate throughput, if a loss
  fault's effect looks subtle.
- **Reproducibility**: each agent seeds its RNG from `SEED` (env, same
  across all agents) XOR a hash of its own `NODE_ID`, and only the noise
  applied to *reported* values uses that RNG — the underlying queue physics
  are deterministic given the same offered-load input. Same `SEED` + same
  `loadgen`/`chaos` invocations ⇒ near-identical runs.
- `loadgen --target n1,n4 ...` publishes `veloca.load.<node>` at 1 Hz
  following the requested profile, then returns nodes to baseline; it logs
  the exact series sent to `experiments/logs/load_<timestamp>.json` and
  posts Grafana annotations at profile start/end.
- `chaos kill|latency|loss <target> --at <delay> [--ms|--pct] [--for
  <duration>]` fires one fault via `veloca.chaos.<node>` after `--at`,
  appends it to `experiments/logs/ground_truth.jsonl`, and posts a Grafana
  annotation. `kill` exits the agent process outright (permanent until the
  container restarts); `latency`/`loss` self-expire after `--for` — the
  agent tracks the expiry, not the CLI.
- `make surge` / `make chaos-kill NODE=<id>` run these from the host
  against the compose NATS on `localhost:4222`. Both CLIs also build as
  one-shot containers (`docker compose run --rm loadgen ...` / `... chaos
  ...`, `profiles: ["tools"]` so `docker compose up` skips them).

## Phase 3: the causal engine

`causal-engine/causal_engine/` (Python 3.11, FastAPI, standalone — venv at
`causal-engine/.venv`, not committed):

- `window.py` — pulls an aligned 1s-resolution DataFrame from Prometheus
  for a `[end_ts - duration_s, end_ts]` window, one column per
  `<node>_<metric>` (all 6 nodes × `offered_load_mbps`, `throughput_mbps`,
  `latency_ms`, `queue_depth`, `packet_loss_pct`). Forward/back-fills gaps
  up to 5s; raises `WindowError` rather than ever substituting zeros.
- `velocity.py` — the velocity-adaptive mode selector. See
  `docs/design.md` for the full algorithm; short version: EMA-smoothed
  `|d/dt(total offered load / calm-period baseline)|`, hysteresis between
  `V_LOW=0.15` and `V_HIGH=0.4` picks "fast" or "slow". Pure-function
  tested in `tests/test_velocity.py` (hysteresis anti-flapping, EMA
  correctness, a synthetic ramp).
- `fast_discovery.py` — pairwise Granger causality (`statsmodels`),
  `tau_max=3`. ~3s over a 60s/30-variable window.
- `slow_discovery.py` — PCMCI (`tigramite`, ParCorr), `tau_max=10`. ~50s
  over the same window. Tigramite's `p_matrix[i,j,tau]`/`graph[i,j,tau]`
  encode a link `i -> j` — verified against a synthetic `x[t-1] -> y[t]`
  example before relying on it.
- `rootcause.py` — flags a metric "degraded" if its back half deviates
  >3σ from its front half (only `latency_ms`/`packet_loss_pct` are
  checked); ranks graph nodes by how upstream they are of degraded
  metrics plus earliest-onset, collapsed to one candidate per network
  node, top-3 returned.
- `validate.py` — DoWhy counterfactual check on a proposed action (cap a
  node's `offered_load_mbps` to its topology baseline): rejects outright
  if there's no causal path treatment→outcome in the graph; otherwise
  estimates a per-unit effect via `backdoor.linear_regression`, translates
  it into a predicted p95-latency improvement, and requires both a
  minimum-gain threshold (`MIN_GAIN=0.10`) and a passing placebo refuter
  to approve. Granger/PCMCI graphs aren't guaranteed acyclic (mutual A↔B
  edges are common) but DoWhy needs a DAG — resolved by keeping only the
  stronger-evidence direction of each mutual pair before any fallback
  arbitrary-cycle breaking (see `_make_acyclic`; naively breaking whatever
  cycle `networkx.find_cycle` returns first can discard a strong direct
  edge in a dense graph instead of a weak indirect one).
- `main.py` — `POST /diagnose {end_ts, duration_s, mode}` (`mode`:
  `"auto"` velocity-decided, or force `"fast"`/`"slow"`) runs the full
  pipeline and returns one verdict. A **fast**-mode diagnosis also
  schedules a **slow**-path re-run of the same window in the background;
  if it disagrees on the top root cause, the stored verdict is revised in
  place (`revised: true`, slow result attached as `revision`) — fetchable
  via `GET /diagnose/{id}`. Also `GET /status` (recent verdicts) and
  `GET /graph/latest`.
- `annotate.py` — every diagnosis posts a Grafana annotation ("diagnosis
  (mode): root cause=X, action approved/not approved"), and a background
  revision posts its own ("revised diagnosis..."), tagged `["veloca",
  "diagnosis"]` — same mechanism loadgen/chaos use, so verdicts show up as
  markers on the same dashboard timeline as the load spikes and faults
  that caused them. The dashboard's annotation query needs `"type":
  "tags"` set explicitly (see `infra/grafana/dashboards/veloca-
  overview.json`) — without it Grafana scopes the query to this
  dashboard's own annotations by ID instead of searching by tag, and
  nothing shows up even though the annotations exist.

## Phase 4: closing the loop

`agent/action.go` — agents obey `veloca.action.<node_id>`: `cap_offered_
load` clamps external offered load to `cap_mbps` for `duration_s`, then
releases back to whatever the load generator/baseline says (no lingering
effect once it expires). Logs before/after offered load and the action_id
on `docker compose logs agent-<node>`.

`control-plane/execute.go` — `POST /execute` takes a causal-engine verdict
JSON. Rejects (publishes nothing, logs why) unless `approved: true` *and*
`proposed_action` is present — enforced here too, not just trusted from
the caller. On success: publishes the action to the target node, appends
an `{"event":"executed",...}` record to `experiments/logs/actions.jsonl`,
posts a Grafana annotation, returns `{executed, action_id, reason}` (always
HTTP 200 for a well-formed request — callers check `executed`, not the
status code, for the business-logic outcome). `GET /actions` returns
recent records from memory.

`causal-engine/causal_engine/main.py` — `POST /diagnose` gained
`auto_execute: bool | None` (`None` → `config.AUTO_EXECUTE_DEFAULT`, off).
When true and the verdict is approved, it calls control-plane's
`/execute` itself and attaches the result as `verdict["execution"]`
(always populated with a reason, even when nothing executed — "auto_execute
is off" vs. "verdict not approved" are distinct, not both collapsed into
a bare `null`). Only the *initial* verdict can trigger execution — a
background slow-path revision never does (by the time it lands ~50s
later, the original action may already be settling/verified, and
re-triggering off a late correction would just confuse the timeline).
`POST /verify/{action_id}` (only for actions this instance itself
executed, tracked in memory) waits `settle_s` (default 15s), pulls a
fresh window, and checks whether the target metric recovered — see
`verify.py` below.

`causal-engine/causal_engine/verify.py` — `recovery_fraction = 1 -
(recent_mean - baseline_mean) / (peak - baseline_mean)`: 1.0 = fully back
at the pre-incident baseline, 0.0 = still at the incident's peak.
`>= RECOVERED_FRACTION` (0.8) → `"recovered"`, `>= PARTIAL_FRACTION` (0.3)
→ `"partial"`, else `"not_recovered"` — the last one appends an
`"escalation"` event to `actions.jsonl` rather than silently declaring
success or attempting a second automatic action (out of scope on purpose).

`causal-engine/watch.py` — standalone script, **off unless explicitly
run** (changes live traffic on purpose is never the default). Polls
Prometheus every `--interval`, checks for degradation via the same
`find_degraded` z-score check as `rootcause.py`; if found, waits
`--settle-before-diagnose` (see below), then runs
detect→diagnose(`auto_execute=true`)→execute→verify with no manual step.
Forces `mode="fast"` regardless of velocity — watch mode's whole point is
reacting quickly, and a diagnosis fired the instant degradation crosses
the threshold has very little incident data to work with; both the slow
path and the velocity estimator itself need more samples than a fresh
trigger has, and a short surge can be over before a 15-50s slow-path
diagnosis even finishes.

**Bugs found and fixed via live runs, not synthetic tests** (each one
only surfaced by actually running the loop against the real network):
- `window.py` reindexed against a fractional-second grid when given
  `time.time()` directly (as `watch.py` does) — Prometheus's returned
  samples are whole-second-aligned, so every column silently came back
  all-NaN. Fixed by rounding `end_ts` before building the query and the
  reindex grid.
- A stale, no-longer-updating time series (`instance="agent-n1:9100"`
  mislabeled `node="n4"`) lingered in Prometheus after container churn
  during the Phase 3 disk-space incident, and could get silently picked
  as `result[0]` for a query matching on `node=` alone. Fixed by also
  matching on `instance=` and raising `WindowError` if more than one
  series comes back, instead of silently taking the first.
- `rank_root_causes` never weighed a candidate's own degradation severity
  — only graph topology (in/out-degree to other degraded variables).
  Observed live: a node with a barely-crossed z≈5 spillover blip
  outranked a node at z≈180 because it happened to pick up a couple more
  spurious edges on a dense, uncorrected-for-multiple-testing graph.
  Fixed by adding a `log10(z_score+1)` severity term per node.
- `_make_acyclic` (breaking cycles before handing the graph to DoWhy)
  repeatedly called `nx.find_cycle` + removed one edge at a time — correct
  but only guaranteed breaking *one* cycle per iteration, and a dense
  graph can have hundreds. Took **over 100 seconds** in a live run.
  Replaced with the standard Eades-Lin-Smyth greedy feedback-arc-set
  heuristic (one linear-ish pass, no cycle search at all): ~6ms on the
  same class of graph in testing.
- Root-cause ranking only ever tried the top candidate's proposed action;
  a tie (or a candidate degraded by something other than its own offered
  load, e.g. a link-loss victim) could rank highest while having no
  causally-supported action, silently giving up rather than trying the
  next-ranked candidate. Fixed: try each top-3 candidate in order, take
  the first one DoWhy actually approves.
- `packet_loss_pct`'s baseline sits so close to zero (~0.05%) that a bare
  5%-of-mean noise floor was a fraction of a percentage point — small
  enough that ordinary jitter alone crossed z=3 and false-triggered watch
  mode on a perfectly calm network. Fixed with a metric-specific absolute
  noise floor (`_ABSOLUTE_NOISE_FLOOR` in `rootcause.py`).

**Verified end-to-end** (real timestamps, real Prometheus data, no
manual step): `watch.py` running, then a 66s n1/n4 spike (`loadgen
--plateau 60s`, no concurrent chaos fault — isolates the loop's response
to the actual overload from an unrelated fault) fired at t=0. Detected at
t+7s, diagnosed+executed (cap n4 to baseline) at t+20s (5.1s fast-path
discovery), verified `recovered` (96%) at t+36s. Cross-checked against
raw Prometheus data: n4's latency (peaked at 719ms) dropped to
near-baseline within 2s of the cap taking effect and stayed there for the
full 30s the action was active — genuine causal effect, not coincidental
timing with the surge's own profile, which was still 30+ seconds from
ending. A control run (identical `loadgen` command, no watch mode)
confirmed n4's latency stayed elevated (600-750ms) continuously for the
entire ~66s plateau, only recovering ~t+69s once the profile ended
naturally. The action's relief was temporary (the 30s cap expired mid-
plateau and the problem resurged, which subsequent watch cycles in this
run didn't happen to catch — a real, honestly-observed limitation of a
single one-shot action against a persistently-renewing load, not glossed
over) — but the *first response* was ~46s faster than doing nothing.

Safety verified: a calm-baseline window with `auto_execute=true` produces
no root-cause candidate → `approved=False` → nothing executed (observed
live, repeatedly); `POST /execute` with `approved: false` sent directly
is refused with no NATS publish and no `actions.jsonl` entry.

## Conventions

- Keep files small and readable; this is a project meant to be read and
  explained during a viva, not a production system. Prefer clarity over
  abstraction.
- `infra/topology.yaml` is the single source of truth for the network
  shape and per-node baseline metrics — both Go services parse it directly,
  don't duplicate node/link data in code.
- Go services are independent modules (`agent/`, `control-plane/`,
  `loadgen/`, `chaos/`, each with their own `go.mod`), no shared go.work —
  they're built as separate Docker images. Small shared bits (e.g. topology
  parsing, Grafana annotation posting) are intentionally duplicated per
  module rather than factored into a shared package. `causal-engine/` (Python)
  follows the same rule — its own small `topology.py` reader, not a shared
  package with the Go services.

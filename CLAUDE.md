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
3. **Causal discovery engine** — `causal-engine` (Python/FastAPI) consumes
   the metrics stream and runs PCMCI (Tigramite), causal-learn, and DoWhy to
   infer a causal graph across node/link metrics and identify likely root
   causes of a surge or degradation, exposed over an HTTP API.
4. **Self-healing control loop** — control-plane consumes causal-engine
   output and issues reroute commands back to agents (adjust simulated
   routing weights/paths), closing the loop from detection to remediation.
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
- `causal-engine/` — Python + FastAPI. Uses `causal-learn`, `tigramite`
  (PCMCI), `dowhy`. Empty placeholder until Phase 3.
- `infra/` — Docker Compose, Prometheus config, Grafana provisioning +
  dashboards, `topology.yaml` (shared network definition read by both Go
  services).
- `experiments/logs/` — `load_<timestamp>.json` (exact profile a loadgen run
  sent) and `ground_truth.jsonl` (every chaos fault ever fired, one JSON
  object per line) — the answer key later evaluation compares detections
  against. Both are generated, not hand-written; don't edit them.
- `docs/` — write-up material for the final report.

Messaging (NATS subjects):
- `veloca.register` — agent liveness heartbeat.
- `veloca.metrics.<node_id>` — an agent's per-tick metrics.
- `veloca.load.<node_id>` — loadgen overrides a node's external offered load.
- `veloca.flow.<node_id>` — one neighbor telling this node how much traffic
  it just forwarded to it (cross-traffic propagation, see below).
- `veloca.chaos.<node_id>` — chaos fires a kill/latency/loss fault.
- `veloca.action.<node_id>` — reserved for Phase 4 reroute commands; agents
  currently only log what arrives here.

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
  module rather than factored into a shared package.

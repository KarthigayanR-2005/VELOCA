# causal-engine

Placeholder for Phase 3. Will be a Python + FastAPI service that consumes
the metrics stream from NATS/Prometheus and runs causal discovery
(`causal-learn`, `tigramite`/PCMCI, `dowhy`) over node/link metrics to infer
a causal graph and identify likely root causes of a surge or degradation.

Not wired into `infra/docker-compose.yml` yet — nothing to run here yet.

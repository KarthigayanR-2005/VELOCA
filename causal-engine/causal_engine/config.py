"""All tunable constants in one place, overridable via env vars so
experiments/validate_phase3.py can sweep them without editing code."""
import os

from causal_engine.topology import node_ids

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PASS = os.environ.get("GRAFANA_PASS", "admin")

METRICS = ["throughput_mbps", "latency_ms", "queue_depth", "packet_loss_pct"]


def NODES() -> list[str]:
    """Node IDs from topology.yaml, resolved lazily so a missing file only
    breaks things that actually need it, not module import."""
    return node_ids()


# --- velocity estimator (causal_engine/velocity.py) ---
EMA_ALPHA = float(os.environ.get("EMA_ALPHA", "0.3"))
V_HIGH = float(os.environ.get("V_HIGH", "0.4"))
V_LOW = float(os.environ.get("V_LOW", "0.15"))
CALM_WINDOW_S = float(os.environ.get("CALM_WINDOW_S", "30"))

# --- discovery (fast_discovery.py / slow_discovery.py) ---
TAU_MAX_FAST = int(os.environ.get("TAU_MAX_FAST", "3"))
TAU_MAX_SLOW = int(os.environ.get("TAU_MAX_SLOW", "10"))
GRANGER_P_THRESHOLD = float(os.environ.get("GRANGER_P_THRESHOLD", "0.05"))
PCMCI_ALPHA = float(os.environ.get("PCMCI_ALPHA", "0.05"))

# --- root-cause ranking (rootcause.py) ---
DEGRADED_METRICS = ("latency_ms", "packet_loss_pct")
Z_SCORE_THRESHOLD = float(os.environ.get("Z_SCORE_THRESHOLD", "3.0"))
# how much of the window (from the start) counts as "recent baseline" for
# z-scoring — the rest is treated as the period that might be degraded.
BASELINE_FRACTION = float(os.environ.get("BASELINE_FRACTION", "0.5"))

# --- counterfactual validation (validate.py) ---
MIN_GAIN = float(os.environ.get("MIN_GAIN", "0.10"))  # require >=10% improvement in the target metric

# --- background slow-path refinement (main.py) ---
# how long the API will wait for an in-flight background slow-path re-run
# before GET /diagnose/{id} just returns the fast verdict as final.
SLOW_PATH_TIMEOUT_S = float(os.environ.get("SLOW_PATH_TIMEOUT_S", "120"))

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

# --- Phase 4: closing the loop (execute_client.py, verify.py, watch.py) ---
CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://localhost:8080")
ACTIONS_LOG_PATH = os.environ.get("ACTIONS_LOG_PATH", "../experiments/logs/actions.jsonl")

# how long a proposed cap_offered_load action stays in effect before the
# agent releases control back to the load generator/baseline
ACTION_DURATION_S = float(os.environ.get("ACTION_DURATION_S", "30"))

# whether POST /diagnose auto-executes an approved verdict when the
# request doesn't say either way — default OFF so routine /diagnose calls
# (debugging, validate_phase3.py, curl) never touch a live agent by
# accident. watch.py explicitly passes auto_execute=true on every call
# regardless of this default, since driving real actions is its whole job.
AUTO_EXECUTE_DEFAULT = os.environ.get("AUTO_EXECUTE_DEFAULT", "false").lower() == "true"

# verify.py: how long to wait after an action executes before checking
# whether the target metric recovered
SETTLE_S = float(os.environ.get("SETTLE_S", "15"))
# recovery classification: recovery_fraction = 1 - (recent-baseline)/(peak-baseline)
RECOVERED_FRACTION = float(os.environ.get("RECOVERED_FRACTION", "0.8"))
PARTIAL_FRACTION = float(os.environ.get("PARTIAL_FRACTION", "0.3"))

# watch.py: polling loop, off by default per the brief (changes live
# traffic — must be started deliberately, never running by accident)
WATCH_INTERVAL_S = float(os.environ.get("WATCH_INTERVAL_S", "10"))
WATCH_WINDOW_S = float(os.environ.get("WATCH_WINDOW_S", "60"))
# don't trigger a new action while a previous one is still settling/verifying
WATCH_COOLDOWN_S = float(os.environ.get("WATCH_COOLDOWN_S", "20"))

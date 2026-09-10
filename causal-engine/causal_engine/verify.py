"""Post-action verification: after an action executes, wait a settle
time, pull a fresh metrics window, and check whether the target metric
(the one validate.py checked) actually recovered toward its pre-incident
baseline — recorded against the action_id in actions.jsonl, not silently
assumed."""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from causal_engine import config
from causal_engine.window import WindowError, get_window


@dataclass
class VerifyResult:
    action_id: str
    column: str
    checked_at: float
    recent_mean: float
    baseline_mean: float
    peak: float
    recovery_fraction: float
    outcome: str  # "recovered" | "partial" | "not_recovered" | "unknown"
    reason: str


def classify_recovery(recent_mean: float, baseline_mean: float, peak: float) -> tuple[float, str]:
    """recovery_fraction = 1 means back at baseline, 0 means still at the
    incident's peak. Anything <= baseline counts as fully recovered even
    if recent_mean undershoots (jitter)."""
    span = peak - baseline_mean
    if span <= 1e-9:
        return 1.0, "recovered"  # nothing was actually elevated to begin with
    fraction = max(0.0, min(1.0, 1 - (recent_mean - baseline_mean) / span))
    if fraction >= config.RECOVERED_FRACTION:
        outcome = "recovered"
    elif fraction >= config.PARTIAL_FRACTION:
        outcome = "partial"
    else:
        outcome = "not_recovered"
    return fraction, outcome


def verify_action(
    action_id: str,
    target_metric: dict,
    settle_s: float = config.SETTLE_S,
    check_window_s: float = 15,
) -> VerifyResult:
    if settle_s > 0:
        time.sleep(settle_s)
    now = time.time()
    column = target_metric["column"]
    baseline_mean = target_metric["baseline_mean"]
    peak = target_metric["peak"]

    try:
        window = get_window(now, check_window_s)
    except WindowError as exc:
        return VerifyResult(
            action_id=action_id, column=column, checked_at=now, recent_mean=float("nan"),
            baseline_mean=baseline_mean, peak=peak, recovery_fraction=0.0,
            outcome="unknown", reason=str(exc),
        )
    if column not in window.columns:
        return VerifyResult(
            action_id=action_id, column=column, checked_at=now, recent_mean=float("nan"),
            baseline_mean=baseline_mean, peak=peak, recovery_fraction=0.0,
            outcome="unknown", reason=f"{column} not in fresh window",
        )

    recent_mean = float(window[column].tail(10).mean())
    fraction, outcome = classify_recovery(recent_mean, baseline_mean, peak)
    reason = f"{column} recent={recent_mean:.2f} baseline={baseline_mean:.2f} peak={peak:.2f} recovery={fraction:.0%}"
    return VerifyResult(
        action_id=action_id, column=column, checked_at=now, recent_mean=recent_mean,
        baseline_mean=baseline_mean, peak=peak, recovery_fraction=fraction,
        outcome=outcome, reason=reason,
    )


def append_verification(rec: VerifyResult) -> None:
    path = Path(config.ACTIONS_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"event": "verified", **asdict(rec)}) + "\n")
        if rec.outcome == "not_recovered":
            # escalate clearly rather than silently declaring success or
            # quietly retrying — a second automatic action is out of scope
            # here on purpose; this just makes the failure visible.
            f.write(json.dumps({
                "event": "escalation", "action_id": rec.action_id,
                "reason": f"action {rec.action_id} did not recover {rec.column}: {rec.reason}",
                "checked_at": rec.checked_at,
            }) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manually verify one action_id against a recorded target metric.")
    parser.add_argument("action_id")
    parser.add_argument("--column", required=True)
    parser.add_argument("--baseline-mean", type=float, required=True)
    parser.add_argument("--peak", type=float, required=True)
    parser.add_argument("--settle-s", type=float, default=0.0)
    args = parser.parse_args()

    result = verify_action(
        args.action_id,
        {"column": args.column, "baseline_mean": args.baseline_mean, "peak": args.peak},
        settle_s=args.settle_s,
    )
    print(result)
    append_verification(result)

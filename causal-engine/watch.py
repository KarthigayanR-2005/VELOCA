"""Watch mode: polls Prometheus every --interval seconds, checks whether
any node is currently degraded (same z-score check as rootcause.py), and
if so drives the full self-healing loop end-to-end with no manual step:
POST /diagnose (auto_execute=true) -> control-plane /execute -> POST
/verify.

OFF unless explicitly run — this changes live traffic on the real running
agents. Not a background thread inside the FastAPI app on purpose: you
have to deliberately start this script for anything to happen.

Usage: python watch.py [--interval 10] [--window 60] [--max-cycles 1]
"""
from __future__ import annotations

import argparse
import logging
import time

import httpx

from causal_engine import config
from causal_engine.rootcause import find_degraded
from causal_engine.window import WindowError, get_window

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("watch")


def poll_once(base_url: str, window_s: float, settle_before_diagnose_s: float = 0.0) -> dict | None:
    """Checks for degradation and, if found, runs one full detect ->
    diagnose -> execute -> verify cycle. Returns None if nothing was
    degraded (no cycle run), else a dict with every stage's result."""
    now = time.time()
    try:
        window = get_window(now, window_s)
    except WindowError as exc:
        logger.warning("skipping poll: %s", exc)
        return None

    degraded = find_degraded(window)
    if not degraded:
        return None

    worst = max(degraded, key=lambda d: d.z_score)
    t_detect = time.time()
    logger.info("DETECTED degradation: %s z=%.2f at t=%.3f", worst.column, worst.z_score, t_detect)

    if settle_before_diagnose_s > 0:
        # A single sample can cross the z-score bar almost the instant an
        # incident starts, but even the fast (Granger) path needs several
        # overload samples to find a lagged relationship reliably — a
        # short debounce lets real evidence accumulate before spending a
        # diagnosis on what's still mostly a single data point.
        logger.info("settling %.0fs before diagnosing, to let more incident data accumulate", settle_before_diagnose_s)
        time.sleep(settle_before_diagnose_s)
        now = time.time()

    # Force the fast path rather than "auto": watch mode's whole point is
    # reacting quickly, and a diagnosis fired the moment degradation
    # crosses the threshold has very little "incident" data to work with
    # yet — both the slow path's search and the velocity estimator itself
    # need more samples than a fresh trigger has, and a short live surge
    # can be over before a 15-50s slow-path diagnosis even finishes. The
    # background slow-path refinement (already automatic for fast-mode
    # diagnoses) still double-checks this verdict a bit later.
    t_diagnose0 = time.time()
    resp = httpx.post(
        f"{base_url}/diagnose",
        json={"end_ts": now, "duration_s": window_s, "mode": "fast", "auto_execute": True},
        timeout=180,
    )
    resp.raise_for_status()
    verdict = resp.json()
    t_diagnose1 = time.time()

    top = verdict["root_causes"][0]["node"] if verdict["root_causes"] else None
    logger.info(
        "DIAGNOSED verdict=%s mode=%s top=%s approved=%s at t=%.3f (took %.2fs)",
        verdict["id"], verdict["mode"], top, verdict["approved"], t_diagnose1, t_diagnose1 - t_diagnose0,
    )

    execution = verdict.get("execution") or {}
    if not execution.get("executed"):
        logger.info("NOT EXECUTED: %s", execution.get("reason", "unknown"))
        return {"detected_at": t_detect, "verdict": verdict, "execution": execution, "verify": None}

    action_id = execution["action_id"]
    t_execute = time.time()
    logger.info("EXECUTED action=%s on %s at t=%.3f", action_id, verdict["proposed_action"]["node"], t_execute)

    vresp = httpx.post(f"{base_url}/verify/{action_id}", timeout=config.SETTLE_S + 30)
    vresp.raise_for_status()
    verify_result = vresp.json()
    t_verify = time.time()
    logger.info(
        "VERIFIED action=%s outcome=%s recovery=%.0f%% at t=%.3f (%.1fs after execute)",
        action_id, verify_result["outcome"], verify_result["recovery_fraction"] * 100, t_verify, t_verify - t_execute,
    )
    return {
        "detected_at": t_detect, "verdict": verdict, "execution": execution,
        "verify": verify_result, "executed_at": t_execute, "verified_at": t_verify,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--causal-engine-url", default="http://localhost:8000")
    parser.add_argument("--interval", type=float, default=config.WATCH_INTERVAL_S)
    parser.add_argument("--window", type=float, default=config.WATCH_WINDOW_S)
    parser.add_argument("--cooldown", type=float, default=config.WATCH_COOLDOWN_S)
    parser.add_argument("--settle-before-diagnose", type=float, default=0.0, help="wait this long after detection before diagnosing, to let more incident data accumulate")
    parser.add_argument("--max-cycles", type=int, default=0, help="stop after this many detect->verify cycles (0 = run forever)")
    args = parser.parse_args()

    logger.warning(
        "WATCH MODE ON: polling every %.0fs, will auto-execute approved actions against live agents (Ctrl+C to stop)",
        args.interval,
    )
    cycles = 0
    cooldown_until = 0.0
    while True:
        now = time.time()
        if now >= cooldown_until:
            result = poll_once(args.causal_engine_url, args.window, args.settle_before_diagnose)
            if result is not None:
                cycles += 1
                cooldown_until = time.time() + args.cooldown
                if args.max_cycles and cycles >= args.max_cycles:
                    logger.info("reached --max-cycles=%d, stopping", args.max_cycles)
                    break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

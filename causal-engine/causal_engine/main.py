"""FastAPI orchestration: velocity -> discovery path -> root-cause ranking
-> proposed action -> counterfactual validation, returned as one verdict.

A fast-path diagnosis also schedules a slow-path re-run in the background;
if the slow path disagrees on the top root cause, the stored verdict is
revised in place, fetchable via GET /diagnose/{id}.

Phase 4: an approved verdict can auto-execute (POST to control-plane's
/execute) — controlled per-request by `auto_execute`, defaulting to
config.AUTO_EXECUTE_DEFAULT (off) when omitted, so routine /diagnose calls
never touch a live agent by accident. Only the initial verdict can trigger
execution — a background slow-path *revision* never does, since by the
time it lands the original action may already be settling/verified and
re-triggering off a 50s-late correction would just confuse the timeline.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict
from typing import Any

import networkx as nx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from causal_engine import config
from causal_engine.annotate import post_annotation
from causal_engine.execute_client import execute_verdict
from causal_engine.fast_discovery import run_fast_discovery
from causal_engine.rootcause import column_baseline, find_degraded, rank_root_causes
from causal_engine.slow_discovery import run_slow_discovery
from causal_engine.topology import baseline_throughput
from causal_engine.validate import validate_action
from causal_engine.velocity import compute_velocity
from causal_engine.verify import append_verification, verify_action
from causal_engine.window import WindowError, get_window

logger = logging.getLogger(__name__)
app = FastAPI(title="VELOCA causal-engine")

_verdicts: dict[str, dict[str, Any]] = {}
_verdict_order: list[str] = []
_MAX_STORED = 50

# action_id -> {"verdict_id", "node", "target_metric"} for executed
# actions, so /verify/{action_id} knows what to re-check without needing
# to re-read control-plane's actions.jsonl.
_actions: dict[str, dict[str, Any]] = {}


class DiagnoseRequest(BaseModel):
    end_ts: float
    duration_s: float = 60
    mode: str = "auto"  # "auto" (velocity-decided) | "fast" | "slow" — force a path for comparison/testing
    auto_execute: bool | None = None  # None -> config.AUTO_EXECUTE_DEFAULT


def _graph_to_edge_list(graph: nx.DiGraph) -> list[dict]:
    return [{"source": u, "target": v, **data} for u, v, data in graph.edges(data=True)]


def _annotate_verdict(verdict: dict, prefix: str = "") -> None:
    top = verdict["root_causes"][0]["node"] if verdict["root_causes"] else "none"
    verdict_status = "approved" if verdict["approved"] else "not approved"
    text = f"{prefix}diagnosis ({verdict['mode']}): root cause={top}, action {verdict_status}"
    post_annotation(text, tags=["veloca", "diagnosis"], time_ms=int(verdict["end_ts"] * 1000))


def _propose_action_for(node: str, window) -> dict | None:
    """Proposes capping one candidate node's offered load back to its
    topology baseline, and records what "recovered" means for it (the
    same pre-incident baseline / incident peak validate.py implicitly
    reasons about for its outcome column) so verify.py can check it later
    without needing to re-derive anything."""
    try:
        cap = baseline_throughput(node)
    except KeyError:
        return None

    target_col = f"{node}_latency_ms"
    if target_col not in window.columns:
        return None
    match = next((d for d in find_degraded(window) if d.column == target_col), None)
    if match:
        baseline_mean, baseline_std, peak = match.baseline_mean, match.baseline_std, match.peak
    else:
        baseline_mean, baseline_std = column_baseline(window, target_col)
        peak = float(window[target_col].max())

    return {
        "type": "cap_offered_load",
        "node": node,
        "target_node": node,
        "cap_mbps": cap,
        "duration_s": config.ACTION_DURATION_S,
        "target_metric": {
            "column": target_col,
            "baseline_mean": baseline_mean,
            "baseline_std": baseline_std,
            "peak": peak,
        },
    }


def _run_diagnosis(window, mode: str) -> dict:
    if mode == "fast":
        graph, discovery_s = run_fast_discovery(window)
    elif mode == "slow":
        graph, discovery_s = run_slow_discovery(window)
    else:
        raise ValueError(f"unknown mode {mode!r}")
    discovery_ms = discovery_s * 1000

    root_causes = rank_root_causes(graph, window)

    # Try each top-3 candidate in ranked order, not just the top one: a
    # tie (or a candidate whose own degradation comes from something other
    # than its own offered load, e.g. an injected link-loss victim rather
    # than an overloaded node) can rank highest while having no
    # causally-supported action at all. Report the first one that's
    # actually approved; if none are, fall back to the top candidate's
    # attempt so the rejection is still transparent.
    t_val0 = time.perf_counter()
    action, effect, approved, val_reason = None, 0.0, False, "no root cause candidate to act on"
    fallback_action, fallback_effect, fallback_reason = None, 0.0, None
    for candidate in root_causes:
        candidate_action = _propose_action_for(candidate.node, window)
        if candidate_action is None:
            continue
        validation = validate_action(graph, window, candidate_action)
        if fallback_action is None:
            fallback_action, fallback_effect, fallback_reason = candidate_action, validation.estimated_effect, validation.reason
        if validation.approved:
            action, effect, approved, val_reason = candidate_action, validation.estimated_effect, True, validation.reason
            break
    if action is None and fallback_action is not None:
        action, effect, val_reason = fallback_action, fallback_effect, fallback_reason
    validation_ms = (time.perf_counter() - t_val0) * 1000

    return {
        "mode": mode,
        "graph": _graph_to_edge_list(graph),
        "root_causes": [
            {"node": c.node, "column": c.column, "score": c.score,
             "out_to_degraded": c.out_to_degraded, "in_from_degraded": c.in_from_degraded}
            for c in root_causes
        ],
        "proposed_action": action,
        "effect": effect,
        "approved": approved,
        "validation_reason": val_reason,
        "timings": {"discovery_ms": discovery_ms, "validation_ms": validation_ms},
    }


def _refine_in_background(verdict_id: str, window) -> None:
    stored = _verdicts.get(verdict_id)
    if stored is None:
        return
    try:
        slow_result = _run_diagnosis(window, mode="slow")
    except Exception:
        logger.exception("background slow-path refinement failed for verdict %s", verdict_id)
        return

    old_top = stored["root_causes"][0]["node"] if stored["root_causes"] else None
    new_top = slow_result["root_causes"][0]["node"] if slow_result["root_causes"] else None

    stored["slow_path_checked"] = True
    if new_top != old_top:
        stored["revised"] = True
        stored["revision"] = slow_result
        stored["revision_note"] = f"background slow path disagreed: fast said {old_top!r}, slow says {new_top!r}"
        post_annotation(
            f"revised diagnosis (slow): root cause={new_top} (fast path had said {old_top})",
            tags=["veloca", "diagnosis"], time_ms=int(stored["end_ts"] * 1000),
        )


@app.post("/diagnose")
def diagnose(req: DiagnoseRequest, background_tasks: BackgroundTasks):
    t0 = time.perf_counter()
    try:
        window = get_window(req.end_ts, req.duration_s)
    except WindowError as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc

    t_vel0 = time.perf_counter()
    velocity_result = compute_velocity(window)
    velocity_ms = (time.perf_counter() - t_vel0) * 1000
    use_mode = velocity_result.mode if req.mode == "auto" else req.mode

    result = _run_diagnosis(window, use_mode)

    verdict_id = str(uuid.uuid4())
    total_ms = (time.perf_counter() - t0) * 1000
    verdict = {
        "id": verdict_id,
        "end_ts": req.end_ts,
        "duration_s": req.duration_s,
        "velocity": float(velocity_result.v.iloc[-1]),
        "velocity_mode_auto": velocity_result.mode,
        "baseline_load_mbps": velocity_result.baseline_load_mbps,
        "revised": False,
        "slow_path_checked": use_mode == "slow",
        **result,
        "timings": {"velocity_ms": velocity_ms, **result["timings"], "total_ms": total_ms},
    }
    _verdicts[verdict_id] = verdict
    _verdict_order.append(verdict_id)
    if len(_verdict_order) > _MAX_STORED:
        _verdicts.pop(_verdict_order.pop(0), None)

    _annotate_verdict(verdict)

    should_execute = config.AUTO_EXECUTE_DEFAULT if req.auto_execute is None else req.auto_execute
    if not should_execute:
        verdict["execution"] = {"executed": False, "action_id": None, "reason": "auto_execute is off"}
    elif not verdict["approved"]:
        verdict["execution"] = {"executed": False, "action_id": None, "reason": "verdict not approved, execution skipped"}
    else:
        exec_result = execute_verdict(verdict)
        verdict["execution"] = exec_result
        if exec_result.get("executed") and exec_result.get("action_id"):
            action = verdict["proposed_action"]
            _actions[exec_result["action_id"]] = {
                "verdict_id": verdict_id, "node": action["node"], "target_metric": action["target_metric"],
            }
            logger.info("auto-executed verdict %s -> action %s on %s", verdict_id, exec_result["action_id"], action["node"])

    if use_mode == "fast":
        background_tasks.add_task(_refine_in_background, verdict_id, window)

    return verdict


@app.post("/verify/{action_id}")
def verify(action_id: str, settle_s: float | None = None):
    info = _actions.get(action_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown action id (not executed via this causal-engine instance)")

    settle_s = config.SETTLE_S if settle_s is None else settle_s
    result = verify_action(action_id, info["target_metric"], settle_s=settle_s)
    append_verification(result)
    post_annotation(
        f"verify {action_id[:8]}: {result.outcome} ({result.recovery_fraction:.0%} recovered)",
        tags=["veloca", "verify"], time_ms=int(result.checked_at * 1000),
    )
    return asdict(result)


@app.get("/diagnose/{verdict_id}")
def get_diagnosis(verdict_id: str):
    verdict = _verdicts.get(verdict_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail="unknown verdict id")
    return verdict


@app.get("/status")
def status(n: int = 10):
    recent_ids = _verdict_order[-n:]
    return {
        "status": "ok",
        "stored_verdicts": len(_verdict_order),
        "last_verdicts": [_verdicts[i] for i in reversed(recent_ids)],
    }


@app.get("/graph/latest")
def graph_latest():
    if not _verdict_order:
        raise HTTPException(status_code=404, detail="no diagnosis has run yet")
    latest = _verdicts[_verdict_order[-1]]
    return {"id": latest["id"], "mode": latest["mode"], "graph": latest["graph"]}

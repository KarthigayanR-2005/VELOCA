"""FastAPI orchestration: velocity -> discovery path -> root-cause ranking
-> proposed action -> counterfactual validation, returned as one verdict.

A fast-path diagnosis also schedules a slow-path re-run in the background;
if the slow path disagrees on the top root cause, the stored verdict is
revised in place, fetchable via GET /diagnose/{id}.

This module is standalone — it is deliberately NOT wired into the control
plane yet (that's Phase 4).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import networkx as nx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from causal_engine.fast_discovery import run_fast_discovery
from causal_engine.rootcause import rank_root_causes
from causal_engine.slow_discovery import run_slow_discovery
from causal_engine.topology import baseline_throughput
from causal_engine.validate import validate_action
from causal_engine.velocity import compute_velocity
from causal_engine.window import WindowError, get_window

logger = logging.getLogger(__name__)
app = FastAPI(title="VELOCA causal-engine")

_verdicts: dict[str, dict[str, Any]] = {}
_verdict_order: list[str] = []
_MAX_STORED = 50


class DiagnoseRequest(BaseModel):
    end_ts: float
    duration_s: float = 60
    mode: str = "auto"  # "auto" (velocity-decided) | "fast" | "slow" — force a path for comparison/testing


def _graph_to_edge_list(graph: nx.DiGraph) -> list[dict]:
    return [{"source": u, "target": v, **data} for u, v, data in graph.edges(data=True)]


def _propose_action(root_causes: list) -> dict | None:
    if not root_causes:
        return None
    node = root_causes[0].node
    try:
        cap = baseline_throughput(node)
    except KeyError:
        return None
    return {"type": "cap_offered_load", "node": node, "target_node": node, "cap_mbps": cap}


def _run_diagnosis(window, mode: str) -> dict:
    if mode == "fast":
        graph, discovery_s = run_fast_discovery(window)
    elif mode == "slow":
        graph, discovery_s = run_slow_discovery(window)
    else:
        raise ValueError(f"unknown mode {mode!r}")
    discovery_ms = discovery_s * 1000

    root_causes = rank_root_causes(graph, window)
    action = _propose_action(root_causes)

    t_val0 = time.perf_counter()
    if action is not None:
        validation = validate_action(graph, window, action)
        effect, approved, val_reason = validation.estimated_effect, validation.approved, validation.reason
    else:
        effect, approved, val_reason = 0.0, False, "no root cause candidate to act on"
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

    if use_mode == "fast":
        background_tasks.add_task(_refine_in_background, verdict_id, window)

    return verdict


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

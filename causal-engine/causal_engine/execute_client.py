"""Calls control-plane's POST /execute with a verdict. Kept as its own
tiny module so main.py's auto-execute branch and watch.py's standalone
loop both call the exact same thing."""
from __future__ import annotations

import logging

import httpx

from causal_engine import config

logger = logging.getLogger(__name__)


def execute_verdict(verdict: dict, timeout: float = 10.0) -> dict:
    """Returns control-plane's ExecuteResponse dict: {executed, action_id,
    reason}. Network/HTTP failures are turned into a well-formed
    "not executed" response rather than raised, so a caller doesn't need
    a second exception-handling path on top of the normal reject case."""
    try:
        resp = httpx.post(f"{config.CONTROL_PLANE_URL}/execute", json=verdict, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("calling control-plane /execute failed: %s", exc)
        return {"executed": False, "action_id": None, "reason": f"execute call failed: {exc}"}

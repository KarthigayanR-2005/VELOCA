"""Posts a Grafana annotation for a diagnosis, so a verdict shows up as a
marker on the same dashboard load spikes and chaos faults already do
(see loadgen/annotate.go and chaos/annotate.go for the Go-side twins)."""
from __future__ import annotations

import logging

import httpx

from causal_engine import config

logger = logging.getLogger(__name__)


def post_annotation(text: str, tags: list[str], time_ms: int) -> None:
    try:
        resp = httpx.post(
            f"{config.GRAFANA_URL}/api/annotations",
            json={"time": time_ms, "tags": tags, "text": text},
            auth=(config.GRAFANA_USER, config.GRAFANA_PASS),
            timeout=3.0,
        )
        if resp.status_code >= 300:
            logger.warning("annotation post returned %s: %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("annotation post failed (is Grafana reachable at %s?): %s", config.GRAFANA_URL, exc)

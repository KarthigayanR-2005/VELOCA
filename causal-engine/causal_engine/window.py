"""Pulls an aligned metrics window from Prometheus for the causal engine to
run discovery over."""
from __future__ import annotations

import datetime as dt

import pandas as pd
from prometheus_api_client import PrometheusConnect

from causal_engine import config

# offered_load_mbps isn't one of the 4 "headline" per-node metrics, but the
# velocity estimator needs it (see velocity.py) — so the window always
# carries it too rather than making callers fetch it separately.
ALL_METRICS = ["offered_load_mbps"] + config.METRICS


class WindowError(RuntimeError):
    """Raised when Prometheus doesn't have enough data to build a usable
    window — callers should surface this, not silently substitute zeros."""


def _client() -> PrometheusConnect:
    return PrometheusConnect(url=config.PROMETHEUS_URL, disable_ssl=True)


def get_window(end_ts: float, duration_s: float = 60, metrics: list[str] | None = None) -> pd.DataFrame:
    """Returns a DataFrame indexed by a 1s-spaced UTC DatetimeIndex running
    from (end_ts - duration_s) to end_ts, with one column per node/metric
    pair (e.g. "n1_latency_ms"). Small gaps (a few missed scrapes) are
    forward-filled; if a whole series is missing, or still mostly empty
    after filling, raises WindowError rather than returning zeros.
    """
    metrics = metrics or ALL_METRICS
    start_ts = end_ts - duration_s
    start = dt.datetime.fromtimestamp(start_ts, tz=dt.timezone.utc)
    end = dt.datetime.fromtimestamp(end_ts, tz=dt.timezone.utc)
    index = pd.date_range(start=start, end=end, freq="1s", tz="UTC")

    client = _client()
    columns: dict[str, pd.Series] = {}
    missing: list[str] = []

    for node in config.NODES():
        for metric in metrics:
            col = f"{node}_{metric}"
            query = f'veloca_{metric}{{node="{node}"}}'
            try:
                result = client.custom_query_range(query=query, start_time=start, end_time=end, step="1s")
            except Exception as exc:  # Prometheus unreachable, bad query, etc.
                raise WindowError(f"querying Prometheus for {col}: {exc}") from exc

            if not result:
                missing.append(col)
                continue

            values = result[0]["values"]
            ts = pd.to_datetime([float(v[0]) for v in values], unit="s", utc=True)
            vals = [float(v[1]) for v in values]
            columns[col] = pd.Series(vals, index=ts)

    if missing:
        raise WindowError(f"Prometheus has no data at all for {len(missing)} series: {missing}")

    df = pd.DataFrame(columns)
    df = df.reindex(index)
    # forward/back-fill only short gaps (a few missed scrapes); a gap wider
    # than this is a real hole in the data, not something to paper over.
    df = df.ffill(limit=5).bfill(limit=5)

    still_bad = [c for c in df.columns if df[c].isna().any()]
    if still_bad:
        raise WindowError(f"gaps wider than 5s remain (after fill) in: {still_bad}")

    return df

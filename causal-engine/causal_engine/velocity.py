"""Velocity-adaptive mode selection: how fast is the network's aggregate
offered load changing right now, and should we run the fast (Granger) or
slow (PCMCI) causal discovery path?

v(t) = EMA_alpha( |d/dt(load(t) / baseline)| )

baseline is the median load over a calm reference window at the start of
the sample (first CALM_WINDOW_S seconds). Mode switches via hysteresis
(V_LOW < V_HIGH) so noise sitting right at one threshold can't flap the
mode back and forth every sample — see tests/test_velocity.py.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from causal_engine import config


@dataclass
class VelocityResult:
    v: pd.Series             # smoothed |d/dt(load/baseline)| per second
    mode: str                # "fast" or "slow" as of the last sample
    mode_series: pd.Series   # mode at every point in v, for inspection/tests
    baseline_load_mbps: float


def aggregate_load(window: pd.DataFrame) -> pd.Series:
    """Sums offered_load_mbps across every node's column in the window."""
    load_cols = [c for c in window.columns if c.endswith("_offered_load_mbps")]
    if not load_cols:
        raise ValueError("window has no *_offered_load_mbps columns")
    return window[load_cols].sum(axis=1)


def ema(series: pd.Series, alpha: float) -> pd.Series:
    """Exponential moving average, seeded with the first value (not 0) so
    it doesn't report a fake velocity spike at the very first sample."""
    vals = series.to_numpy()
    out = np.empty(len(vals))
    out[0] = vals[0]
    for i in range(1, len(vals)):
        out[i] = alpha * vals[i] + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def hysteresis_mode(v: pd.Series, v_high: float, v_low: float) -> pd.Series:
    """"fast" once v crosses above v_high, staying "fast" until v drops
    back below v_low. A value sitting between v_low and v_high never
    changes the mode by itself — that's what stops it flapping right at a
    single boundary.
    """
    modes = []
    state = "slow"
    for val in v.to_numpy():
        if state == "slow" and val > v_high:
            state = "fast"
        elif state == "fast" and val < v_low:
            state = "slow"
        modes.append(state)
    return pd.Series(modes, index=v.index)


def compute_velocity(
    window: pd.DataFrame,
    calm_window_s: float = config.CALM_WINDOW_S,
    alpha: float = config.EMA_ALPHA,
    v_high: float = config.V_HIGH,
    v_low: float = config.V_LOW,
) -> VelocityResult:
    load = aggregate_load(window)

    calm_end = load.index[0] + pd.Timedelta(seconds=calm_window_s)
    calm_slice = load[load.index <= calm_end]
    baseline = float(calm_slice.median()) if len(calm_slice) else float(load.median())
    if baseline <= 0:
        baseline = 1.0  # degenerate all-zero window guard, avoids a div-by-zero blowup

    load_norm = load / baseline
    # samples are 1s apart, so the first difference *is* d/dt
    raw = load_norm.diff().abs().fillna(0.0)

    v = ema(raw, alpha)
    mode_series = hysteresis_mode(v, v_high, v_low)

    return VelocityResult(v=v, mode=mode_series.iloc[-1], mode_series=mode_series, baseline_load_mbps=baseline)

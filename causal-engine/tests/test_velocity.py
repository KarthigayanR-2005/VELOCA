"""Pure-function tests for causal_engine/velocity.py — no Prometheus, no
network, just synthetic series."""
import numpy as np
import pandas as pd

from causal_engine.velocity import compute_velocity, ema, hysteresis_mode

V_HIGH, V_LOW = 0.4, 0.15


def _series(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="1s", tz="UTC")
    return pd.Series(values, index=idx)


def test_hysteresis_holds_fast_mode_while_oscillating_at_the_boundary():
    # calm -> crosses V_HIGH -> oscillates around V_HIGH (never dipping
    # below V_LOW) -> finally drops below V_LOW.
    values = (
        [0.05, 0.05, 0.05]
        + [0.45]
        + [0.36, 0.44, 0.37, 0.43, 0.38, 0.44, 0.36]  # straddles V_HIGH, stays above V_LOW
        + [0.05, 0.05]
    )
    v = _series(values)
    modes = hysteresis_mode(v, V_HIGH, V_LOW)

    oscillation = modes.iloc[4:11]
    assert (oscillation == "fast").all(), f"hysteresis flapped during the oscillation: {oscillation.tolist()}"

    # exactly one slow->fast and one fast->slow transition for the whole run
    transitions = (modes != modes.shift()).sum() - 1  # -1 for the first (non-)transition
    assert transitions == 2, f"expected exactly 2 mode transitions, got {transitions}: {modes.tolist()}"

    # sanity: without hysteresis (single threshold at V_HIGH) the same
    # oscillation *would* flap, which is exactly the failure mode hysteresis
    # exists to prevent.
    naive = _series(values) > V_HIGH
    naive_transitions_in_oscillation = (naive.iloc[4:11] != naive.iloc[4:11].shift()).sum()
    assert naive_transitions_in_oscillation > 0, "test fixture doesn't actually straddle the boundary"


def test_hysteresis_stays_slow_if_it_never_reaches_v_high():
    values = [0.1, 0.2, 0.3, 0.39, 0.2, 0.1]
    modes = hysteresis_mode(_series(values), V_HIGH, V_LOW)
    assert (modes == "slow").all()


def test_ema_matches_hand_computed_values():
    v = ema(_series([1.0, 0.0, 1.0, 0.0]), alpha=0.5)
    # out[0]=1; out[1]=0.5*0+0.5*1=0.5; out[2]=0.5*1+0.5*0.5=0.75; out[3]=0.5*0+0.5*0.75=0.375
    assert np.allclose(v.to_numpy(), [1.0, 0.5, 0.75, 0.375])


def test_compute_velocity_flags_a_sudden_ramp_as_fast_and_settles_back_to_slow():
    n1 = np.concatenate([
        np.full(30, 100.0),                       # calm baseline
        np.linspace(100.0, 400.0, 5),              # sudden 4x ramp over 5s
        np.full(20, 400.0),                        # plateau
        np.full(15, 100.0),                        # back to baseline, held long enough to decay
    ])
    idx = pd.date_range("2026-01-01", periods=len(n1), freq="1s", tz="UTC")
    window = pd.DataFrame({"n1_offered_load_mbps": n1}, index=idx)

    result = compute_velocity(window, calm_window_s=29, alpha=0.3, v_high=V_HIGH, v_low=V_LOW)

    ramp_end = 30 + 5
    assert (result.mode_series.iloc[30:ramp_end] == "fast").any(), "the ramp itself should trip fast mode"
    assert result.mode_series.iloc[-1] == "slow", "should have settled back to slow well after the plateau"

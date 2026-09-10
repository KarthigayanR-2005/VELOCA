"""Ranks candidate root causes for the currently-degraded metrics, using
the causal graph's structure (who's upstream vs downstream of the trouble)
plus which degraded variable's anomaly started earliest."""
from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

from causal_engine import config


@dataclass
class DegradedVar:
    column: str
    z_score: float
    onset: pd.Timestamp | None
    baseline_mean: float
    baseline_std: float
    peak: float


@dataclass
class RootCauseCandidate:
    node: str
    column: str
    score: float
    out_to_degraded: int
    in_from_degraded: int


def find_degraded(
    window: pd.DataFrame,
    baseline_fraction: float = config.BASELINE_FRACTION,
    z_threshold: float = config.Z_SCORE_THRESHOLD,
) -> list[DegradedVar]:
    """A variable is "degraded" if, in the back half of the window, it
    strays more than z_threshold standard deviations above its own mean
    from the front half (its "recent baseline")."""
    n = len(window)
    split = max(1, int(n * baseline_fraction))
    baseline, recent = window.iloc[:split], window.iloc[split:]
    if len(recent) == 0:
        baseline, recent = window, window

    degraded = []
    for col in window.columns:
        if not any(col.endswith("_" + m) for m in config.DEGRADED_METRICS):
            continue
        b_mean, b_std = baseline[col].mean(), baseline[col].std()
        b_std = _noise_floor(col, b_mean, b_std)
        z = (recent[col] - b_mean) / b_std
        max_z = z.max()
        if max_z > z_threshold:
            onset = z[z > z_threshold].index.min()
            degraded.append(DegradedVar(
                column=col, z_score=float(max_z), onset=onset,
                baseline_mean=float(b_mean), baseline_std=float(b_std),
                peak=float(recent[col].max()),
            ))
    return degraded


def column_baseline(window: pd.DataFrame, column: str, baseline_fraction: float = config.BASELINE_FRACTION) -> tuple[float, float]:
    """Front-half mean/std for one column, regardless of whether it was
    flagged degraded — used as a verification fallback when the exact
    column checked by validate.py wasn't itself over the z-score bar."""
    n = len(window)
    split = max(1, int(n * baseline_fraction))
    baseline = window[column].iloc[:split]
    mean, std = float(baseline.mean()), float(baseline.std())
    return mean, _noise_floor(column, mean, std)


# packet_loss_pct sits so close to zero at rest (~0.05%) that a bare 5%-of-
# mean floor is a fraction of a percentage point — small enough that
# ordinary jitter alone crosses a z=3 threshold and false-triggers watch
# mode on a perfectly calm network. An absolute floor per metric fixes
# this without needing a metric-specific z-threshold; latency_ms's own
# baseline (tens of ms) is large enough that a floor barely matters there.
_ABSOLUTE_NOISE_FLOOR = {"packet_loss_pct": 0.05, "latency_ms": 2.0}


def _noise_floor(column: str, mean: float, std: float) -> float:
    if not np.isfinite(std) or std == 0:
        std = abs(mean) * 0.05
    metric = column.split("_", 1)[1] if "_" in column else column
    floor = _ABSOLUTE_NOISE_FLOOR.get(metric, 1e-6)
    return max(std, floor)


def _node_of(column: str) -> str:
    return column.split("_", 1)[0]


def rank_root_causes(graph: nx.DiGraph, window: pd.DataFrame, top_n: int = 3) -> list[RootCauseCandidate]:
    degraded = find_degraded(window)
    if not degraded:
        return []
    degraded_cols = {d.column for d in degraded}

    def onset_key(d: DegradedVar) -> float:
        return d.onset.value if d.onset is not None else float("inf")

    onset_order = sorted(degraded, key=onset_key)
    onset_rank = {d.column: i for i, d in enumerate(onset_order)}

    # How badly is each *node* actually degraded (its worst column's
    # z-score)? Graph topology alone (out/in-degree to other degraded
    # vars) is easy noise to game on a dense, weakly-thresholded graph —
    # observed live: a node with a barely-crossed z~5 spillover blip
    # outranking a node at z~180 because it happened to pick up a couple
    # more spurious edges. Severity has to actually count.
    z_by_node: dict[str, float] = {}
    for d in degraded:
        node = _node_of(d.column)
        z_by_node[node] = max(z_by_node.get(node, 0.0), d.z_score)

    per_column: list[RootCauseCandidate] = []
    for col in graph.nodes:
        succs = set(graph.successors(col)) if col in graph else set()
        preds = set(graph.predecessors(col)) if col in graph else set()
        out_to_degraded = len((succs & degraded_cols) - {col})
        in_from_degraded = len((preds & degraded_cols) - {col})

        if out_to_degraded == 0 and col not in degraded_cols:
            continue  # not implicated in any degraded symptom at all

        # upstream (points at the trouble, isn't pointed at by it) scores
        # highest; being the earliest-onset degraded variable adds a bonus
        # since that's evidence of being the original trigger; how badly
        # degraded this node actually is (log-scaled, so a 180 vs 5
        # z-score gap dominates ties without letting one outlier sample
        # swamp everything) breaks topology-only ties correctly.
        score = out_to_degraded - in_from_degraded
        score += math.log10(z_by_node.get(_node_of(col), 0.0) + 1) * 5.0
        rank = onset_rank.get(col)
        if rank is not None:
            score += (len(onset_order) - rank) * 0.5

        per_column.append(
            RootCauseCandidate(
                node=_node_of(col), column=col, score=score,
                out_to_degraded=out_to_degraded, in_from_degraded=in_from_degraded,
            )
        )

    # collapse to one (best-scoring) candidate per node — callers want to
    # know "which node", not "which of its five metric columns"
    best_per_node: dict[str, RootCauseCandidate] = {}
    for c in per_column:
        if c.node not in best_per_node or c.score > best_per_node[c.node].score:
            best_per_node[c.node] = c

    ranked = sorted(best_per_node.values(), key=lambda c: c.score, reverse=True)
    return ranked[:top_n]

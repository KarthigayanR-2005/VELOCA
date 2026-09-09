"""Ranks candidate root causes for the currently-degraded metrics, using
the causal graph's structure (who's upstream vs downstream of the trouble)
plus which degraded variable's anomaly started earliest."""
from __future__ import annotations

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
        if not np.isfinite(b_std) or b_std == 0:
            b_std = max(abs(b_mean) * 0.05, 1e-6)  # near-constant baseline: assume a 5% noise floor
        z = (recent[col] - b_mean) / b_std
        max_z = z.max()
        if max_z > z_threshold:
            onset = z[z > z_threshold].index.min()
            degraded.append(DegradedVar(column=col, z_score=float(max_z), onset=onset))
    return degraded


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
        # since that's evidence of being the original trigger.
        score = out_to_degraded - in_from_degraded
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

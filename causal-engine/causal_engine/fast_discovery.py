"""Fast path: pairwise Granger causality across every variable pair, short
lag — cheap enough to run on every diagnosis, used while the network is
changing quickly and there's no time for PCMCI's full search."""
from __future__ import annotations

import time
import warnings

import networkx as nx
import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import InfeasibleTestError
from statsmodels.tsa.stattools import grangercausalitytests

from causal_engine import config


def run_fast_discovery(
    window: pd.DataFrame,
    tau_max: int = config.TAU_MAX_FAST,
    p_threshold: float = config.GRANGER_P_THRESHOLD,
) -> tuple[nx.DiGraph, float]:
    """Returns (graph, wall_clock_seconds). An edge x -> y exists if x
    Granger-causes y at p < p_threshold for at least one lag in
    [1, tau_max]; its weight is -log10(best p-value found) — higher means
    stronger evidence.
    """
    start = time.perf_counter()
    graph = nx.DiGraph()
    graph.add_nodes_from(window.columns)

    cols = list(window.columns)
    for y in cols:
        for x in cols:
            if x == y:
                continue
            data = window[[y, x]].to_numpy()  # statsmodels convention: [target, predictor]
            if np.allclose(data.std(axis=0), 0):
                continue  # a constant series has no meaningful Granger test

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    result = grangercausalitytests(data, maxlag=tau_max)
            except (np.linalg.LinAlgError, InfeasibleTestError):
                continue  # genuinely ill-conditioned for this pair (e.g. collinear/constant columns) — skip it

            best_p = min(result[lag][0]["ssr_ftest"][1] for lag in result)
            if best_p < p_threshold:
                graph.add_edge(x, y, weight=float(-np.log10(max(best_p, 1e-300))), p_value=float(best_p))

    elapsed = time.perf_counter() - start
    return graph, elapsed

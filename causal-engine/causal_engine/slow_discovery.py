"""Slow path: PCMCI (Tigramite) with ParCorr, a longer max lag — a proper
causal discovery search rather than the fast path's pairwise screening.
Used when the network isn't changing quickly enough to need an instant
(but cruder) answer, and to background-refine a fast-path verdict.

Tigramite's p_matrix/val_matrix/graph arrays are indexed [i, j, tau]: a
link i -> j at lag tau. Verified against a synthetic x[t-1] -> y[t]
example before writing this (p_matrix[0, 1, 1] was significant, graph[0,
1, 1] == "-->", with x at index 0, y at index 1).
"""
from __future__ import annotations

import logging
import time

import networkx as nx
import pandas as pd
from tigramite import data_processing as pp
from tigramite.independence_tests.parcorr import ParCorr
from tigramite.pcmci import PCMCI

from causal_engine import config

logger = logging.getLogger(__name__)


def run_slow_discovery(
    window: pd.DataFrame,
    tau_max: int = config.TAU_MAX_SLOW,
    alpha: float = config.PCMCI_ALPHA,
) -> tuple[nx.DiGraph, float]:
    """Returns (graph, wall_clock_seconds). Edge i -> j exists if PCMCI
    found a significant link at any lag in [1, tau_max]; lagged links for
    the same (i, j) pair collapse to one edge keeping the strongest
    (lowest p-value) lag, recorded as edge attribute "lag".
    """
    start = time.perf_counter()

    var_names = list(window.columns)
    dataframe = pp.DataFrame(window.to_numpy(), var_names=var_names)
    pcmci = PCMCI(dataframe=dataframe, cond_ind_test=ParCorr(significance="analytic"), verbosity=0)
    results = pcmci.run_pcmci(tau_max=tau_max, pc_alpha=alpha)

    p_matrix = results["p_matrix"]
    val_matrix = results["val_matrix"]
    n = len(var_names)

    graph = nx.DiGraph()
    graph.add_nodes_from(var_names)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            best_tau, best_p = None, None
            for tau in range(1, tau_max + 1):
                p = p_matrix[i, j, tau]
                if p < alpha and (best_p is None or p < best_p):
                    best_p, best_tau = p, tau
            if best_tau is not None:
                graph.add_edge(
                    var_names[i], var_names[j],
                    weight=float(abs(val_matrix[i, j, best_tau])),
                    p_value=float(best_p),
                    lag=best_tau,
                )

    elapsed = time.perf_counter() - start
    logger.info("slow_discovery: PCMCI over %d vars, tau_max=%d took %.2fs", n, tau_max, elapsed)
    return graph, elapsed

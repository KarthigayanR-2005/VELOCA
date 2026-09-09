"""Counterfactual validation: given a proposed remediation action, estimate
its effect on the target metric via DoWhy and decide whether it should be
approved.

DoWhy's linear_regression estimator gives a *per-unit* causal effect
(d(outcome)/d(treatment)) from the observed window. We translate that into
a prediction for the specific action ("cap load to X") by shifting every
sample of the outcome by effect_per_unit * (cap_value - observed_treatment),
then comparing the resulting p95 to the actual p95 — a simple, inspectable
way to get a p95-level answer out of a mean-effect estimator without
building a full distributional causal model.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import networkx as nx
import pandas as pd
from dowhy import CausalModel

from causal_engine import config


@dataclass
class ValidationResult:
    treatment: str
    outcome: str
    baseline_p95: float
    predicted_p95: float
    estimated_effect: float  # positive = predicted improvement (lower latency)
    per_unit_effect: float | None
    refuter_effect: float | None
    approved: bool
    reason: str
    runtime_s: float


def _graph_to_dot(graph: nx.DiGraph) -> str:
    nodes = ";".join(f'"{n}"' for n in graph.nodes())
    edges = ";".join(f'"{u}" -> "{v}"' for u, v in graph.edges())
    return f"digraph {{ {nodes}; {edges} }}"


def _make_acyclic(graph: nx.DiGraph) -> nx.DiGraph:
    """DoWhy's identifier requires a DAG, but Granger/PCMCI routinely
    report cycles. Most of these are simple mutual pairs (A->B and B->A
    both significant) rather than genuine longer loops, so resolve those
    first and deterministically (keep only the stronger direction) —
    picking an arbitrary cycle to break via nx.find_cycle() in a dense
    graph can just as easily pick a longer cycle that happens to route
    through a pair's *stronger* edge, discarding exactly the evidence we
    want to keep. Only fall back to that arbitrary-cycle removal for
    whatever longer cycles remain after mutual pairs are resolved.
    """
    g = graph.copy()
    for u, v in list(g.edges()):
        if g.has_edge(u, v) and g.has_edge(v, u):
            w_uv = g.edges[u, v].get("weight", 0.0)
            w_vu = g.edges[v, u].get("weight", 0.0)
            g.remove_edge(v, u) if w_uv >= w_vu else g.remove_edge(u, v)

    while True:
        try:
            cycle = nx.find_cycle(g)
        except nx.NetworkXNoCycle:
            return g
        weakest = min(cycle, key=lambda e: g.edges[e[0], e[1]].get("weight", 0.0))
        g.remove_edge(*weakest)


def validate_action(
    graph: nx.DiGraph,
    window: pd.DataFrame,
    action: dict,
    min_gain: float = config.MIN_GAIN,
) -> ValidationResult:
    """action = {"node": "n1", "cap_mbps": 120.0, "target_node": "n1"}
    (target_node defaults to node — whose p95 latency we're trying to fix)."""
    start = time.perf_counter()

    treatment = f"{action['node']}_offered_load_mbps"
    target_node = action.get("target_node", action["node"])
    outcome = f"{target_node}_latency_ms"

    def done(**kwargs) -> ValidationResult:
        kwargs.setdefault("per_unit_effect", None)
        kwargs.setdefault("refuter_effect", None)
        return ValidationResult(treatment=treatment, outcome=outcome, runtime_s=time.perf_counter() - start, **kwargs)

    if treatment not in window.columns or outcome not in window.columns:
        return done(
            baseline_p95=float("nan"), predicted_p95=float("nan"), estimated_effect=0.0,
            approved=False, reason="treatment or outcome column missing from the window",
        )

    baseline_p95 = float(window[outcome].quantile(0.95))
    graph = _make_acyclic(graph)

    if treatment not in graph.nodes or not nx.has_path(graph, treatment, outcome):
        return done(
            baseline_p95=baseline_p95, predicted_p95=baseline_p95, estimated_effect=0.0,
            approved=False,
            reason=f"no causal path {treatment} -> {outcome} in the discovered graph; refusing to act on an unsupported claim",
        )

    if "cap_mbps" not in action:
        return done(
            baseline_p95=baseline_p95, predicted_p95=baseline_p95, estimated_effect=0.0,
            approved=False, reason="action is missing cap_mbps",
        )

    model = CausalModel(
        data=window.reset_index(drop=True),
        treatment=treatment,
        outcome=outcome,
        graph=_graph_to_dot(graph),
    )
    identified = model.identify_effect(proceed_when_unidentifiable=True)
    estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")
    per_unit_effect = float(estimate.value)  # d(outcome)/d(treatment)

    cap_value = float(action["cap_mbps"])
    delta = cap_value - window[treatment]
    predicted_series = window[outcome] + per_unit_effect * delta
    predicted_p95 = float(predicted_series.quantile(0.95))
    estimated_effect = baseline_p95 - predicted_p95  # positive = latency improves

    refuter_effect = None
    refuter_ok = True
    refuter_note = ""
    try:
        refute = model.refute_estimate(
            identified, estimate, method_name="placebo_treatment_refuter",
            placebo_type="permute", num_simulations=20,
        )
        refuter_effect = float(refute.new_effect)
        # a trustworthy effect should be clearly bigger than what a placebo
        # (randomly shuffled) treatment produces from noise alone
        refuter_ok = abs(per_unit_effect) < 1e-9 or abs(refuter_effect) < 0.5 * abs(per_unit_effect)
        if not refuter_ok:
            refuter_note = f" (placebo refuter found a comparable effect {refuter_effect:.4f} from noise alone)"
    except Exception as exc:
        refuter_note = f" (placebo refuter failed to run: {exc}; not held against the estimate)"

    min_gain_abs = min_gain * baseline_p95
    approved = estimated_effect >= min_gain_abs and refuter_ok

    if approved:
        reason = f"predicted p95 latency improves by {estimated_effect:.2f}ms (>= {min_gain_abs:.2f}ms required){refuter_note}"
    elif estimated_effect < min_gain_abs:
        reason = f"predicted improvement {estimated_effect:.2f}ms is below the required {min_gain_abs:.2f}ms{refuter_note}"
    else:
        reason = f"rejected by the placebo refuter{refuter_note}"

    return done(
        baseline_p95=baseline_p95, predicted_p95=predicted_p95, estimated_effect=estimated_effect,
        per_unit_effect=per_unit_effect, refuter_effect=refuter_effect,
        approved=approved, reason=reason,
    )

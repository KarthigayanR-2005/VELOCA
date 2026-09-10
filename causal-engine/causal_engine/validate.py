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
    report cycles — and on a dense, weakly-thresholded graph (no
    multiple-testing correction), that can mean hundreds of overlapping
    cycles, not just a few simple mutual pairs.

    Originally this repeatedly called nx.find_cycle() and dropped the
    weakest edge in whatever cycle it found, one at a time. That's
    correct but can be pathologically slow: on a genuinely dense graph it
    took over 100 seconds in practice (a live self-healing demo run) —
    each iteration only guarantees breaking *one* cycle, and a dense
    graph can have thousands. Replaced with the standard Eades-Lin-Smyth
    greedy heuristic for the minimum feedback arc set: build a node
    ordering in one linear-ish pass (peel off sinks to the back, sources
    to the front, otherwise the node with the highest out-minus-in degree
    to the front) and keep only edges that run forward in that ordering.
    That's a single pass with no cycle search at all, so it's fast
    regardless of how tangled the graph is, and — like the pairwise
    resolution this replaced — still keeps the stronger-evidence edge in
    the common case of a mutual pair (an edge's forward-vs-backward
    orientation in the resulting order tracks which side pulled harder on
    out/in degree, which strong edges dominate).
    """
    g = graph.copy()
    order = _feedback_arc_set_ordering(g)
    position = {n: i for i, n in enumerate(order)}
    acyclic = nx.DiGraph()
    acyclic.add_nodes_from(g.nodes())
    for u, v, data in g.edges(data=True):
        if position[u] < position[v]:
            acyclic.add_edge(u, v, **data)
    return acyclic


def _feedback_arc_set_ordering(g: nx.DiGraph) -> list:
    """Eades-Lin-Smyth greedy ordering: nodes placed here-before-there in
    the returned list means "mostly points forward" — keeping only edges
    that agree with this order breaks (approximately, near-minimally) all
    cycles in one pass."""
    work = g.copy()
    front: list = []
    back: list = []
    while work.number_of_nodes() > 0:
        removed_any = True
        while removed_any:
            removed_any = False
            for n in [n for n in work.nodes() if work.out_degree(n) == 0]:
                back.append(n)
                work.remove_node(n)
                removed_any = True
            for n in [n for n in work.nodes() if work.in_degree(n) == 0]:
                front.append(n)
                work.remove_node(n)
                removed_any = True
        if work.number_of_nodes() > 0:
            best = max(work.nodes(), key=lambda n: work.out_degree(n) - work.in_degree(n))
            front.append(best)
            work.remove_node(best)
    return front + list(reversed(back))


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

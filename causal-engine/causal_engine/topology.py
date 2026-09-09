"""Reads infra/topology.yaml — the same file agent/ and control-plane/ read
— so node IDs and baseline throughput values live in exactly one place."""
import os
from functools import lru_cache

import yaml

TOPOLOGY_PATH = os.environ.get("TOPOLOGY_PATH", "../infra/topology.yaml")


@lru_cache(maxsize=1)
def load_topology(path: str = TOPOLOGY_PATH) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def node_ids(path: str = TOPOLOGY_PATH) -> list[str]:
    return [n["id"] for n in load_topology(path)["nodes"]]


def baseline_throughput(node_id: str, path: str = TOPOLOGY_PATH) -> float:
    for n in load_topology(path)["nodes"]:
        if n["id"] == node_id:
            return float(n["baseline"]["throughput_mbps"])
    raise KeyError(f"node {node_id!r} not found in topology {path}")

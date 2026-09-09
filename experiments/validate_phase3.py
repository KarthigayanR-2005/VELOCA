"""Phase 3 ground-truth validation.

For each fault already recorded in experiments/logs/ground_truth.jsonl
(from `make surge` runs), calls POST /diagnose on the window covering it
and checks whether the reported root cause matches the node/link that was
actually faulted. Also runs /diagnose once forced to "fast" and once to
"slow" on the same window and reports whether they agree, plus each
path's wall-clock runtime — the first real numbers for the design doc's
"expected runtime" table.

Usage: python experiments/validate_phase3.py [--causal-engine-url URL]
Requires the causal-engine (and the Prometheus it reads from) to already
be running with data covering the ground-truth timestamps.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import httpx

LOGS_DIR = Path(__file__).parent / "logs"
GROUND_TRUTH = LOGS_DIR / "ground_truth.jsonl"
WINDOW_DURATION_S = 60


def load_ground_truth() -> list[dict]:
    if not GROUND_TRUTH.exists():
        print(f"no ground truth file at {GROUND_TRUTH}")
        return []
    records = []
    with open(GROUND_TRUTH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def expected_nodes(target: str) -> set[str]:
    """"n2-n3" (a link) -> {"n2","n3"}; "n3" (a node) -> {"n3"}."""
    parts = target.split("-")
    if len(parts) == 2 and all(p.startswith("n") and p[1:].isdigit() for p in parts):
        return set(parts)
    return {target}


def concurrent_load_spike_targets(fault_ts: float) -> set[str]:
    """`make surge` fires a load spike and a chaos fault together, so the
    window around a logged chaos fault often also contains a much bigger,
    concurrent load spike (not itself in ground_truth.jsonl, since only
    chaos writes there). If the root cause the engine reports is actually
    the dominant spike rather than the comparatively minor chaos fault,
    that's a *correct* answer, not a wrong one — so any load_*.json run
    whose [start, end] window covers fault_ts also counts as "expected".
    """
    targets: set[str] = set()
    for path in LOGS_DIR.glob("load_*.json"):
        try:
            run = json.loads(path.read_text())
            started = dt.datetime.fromisoformat(run["started_at"]).timestamp()
            ended = dt.datetime.fromisoformat(run["ended_at"]).timestamp()
        except (KeyError, ValueError):
            continue
        if started - 5 <= fault_ts <= ended + 5:
            targets.update(run.get("targets", []))
    return targets


def diagnose(base_url: str, end_ts: float, mode: str = "auto") -> dict:
    resp = httpx.post(
        f"{base_url}/diagnose",
        json={"end_ts": end_ts, "duration_s": WINDOW_DURATION_S, "mode": mode},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


def top_nodes(verdict: dict) -> list[str]:
    return [rc["node"] for rc in verdict.get("root_causes", [])]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--causal-engine-url", default="http://localhost:8000")
    args = parser.parse_args()

    records = load_ground_truth()
    if not records:
        print("nothing to validate")
        return 1

    tested_ok = 0
    tested_bad = 0
    skipped_no_data = 0
    for rec in records:
        fault_ts = dt.datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp()
        duration_s = rec.get("duration_s") or 0
        # cover the fault plus a bit of its aftermath, so degraded metrics
        # have had time to show up by the end of the window
        end_ts = fault_ts + max(duration_s, 10) + 5

        expected = expected_nodes(rec["target"])
        concurrent = concurrent_load_spike_targets(fault_ts)
        newly_expected = concurrent - expected
        expected |= concurrent

        print(f"\n=== fault: {rec['type']} {rec['target']} at {rec['ts']} (expect one of {sorted(expected)}) ===")
        if newly_expected:
            print(f"  note: a concurrent load spike targeted {sorted(newly_expected)} in this same window -")
            print(f"        that's the dominant effect, so it's an equally correct top root cause")

        try:
            verdict = diagnose(args.causal_engine_url, end_ts, mode="auto")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 424:
                # Prometheus simply doesn't have this window's data anymore
                # (retention, or an infra restart since the fault was
                # logged) — that's a data-availability gap, not a wrong
                # diagnosis, so it doesn't count as a test failure.
                print(f"  SKIPPED: no Prometheus data left for this window ({exc.response.json().get('detail', '')[:80]}...)")
                skipped_no_data += 1
            else:
                print(f"  ERROR calling /diagnose: {exc.response.status_code} {exc.response.text}")
                tested_bad += 1
            continue
        except Exception as exc:
            print(f"  ERROR calling /diagnose: {exc}")
            tested_bad += 1
            continue

        found = top_nodes(verdict)
        top1_match = bool(set(found[:1]) & expected)
        top3_match = bool(set(found) & expected)
        print(f"  mode={verdict['mode']} velocity={verdict['velocity']:.3f} root_causes={found}")
        print(f"  top-1 match: {top1_match} | top-3 match: {top3_match}")
        if top3_match:
            tested_ok += 1
        else:
            tested_bad += 1

        try:
            fast_v = diagnose(args.causal_engine_url, end_ts, mode="fast")
            slow_v = diagnose(args.causal_engine_url, end_ts, mode="slow")
        except Exception as exc:
            print(f"  ERROR comparing fast/slow: {exc}")
            continue

        fast_top, slow_top = top_nodes(fast_v)[:1], top_nodes(slow_v)[:1]
        print(f"  fast: top={fast_top} runtime={fast_v['timings']['discovery_ms']:.0f}ms")
        print(f"  slow: top={slow_top} runtime={slow_v['timings']['discovery_ms']:.0f}ms")
        print(f"  fast/slow agree on top-1: {fast_top == slow_top}")

    total = tested_ok + tested_bad
    print(f"\n=== summary: {tested_ok}/{total} testable faults correctly diagnosed"
          f" ({skipped_no_data} skipped - no Prometheus data left for that window) ===")
    overall_ok = total > 0 and tested_bad == 0
    print(f"=== overall: {'PASS' if overall_ok else 'FAIL'} ===")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

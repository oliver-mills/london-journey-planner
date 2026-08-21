"""Measures what the A* heuristic buys over plain Dijkstra.

Both runs go through the same `shortest_route`: passing station positions
enables the straight-line heuristic, withholding them leaves it at zero,
which is exactly Dijkstra. So this compares one implementation against
itself with the heuristic switched off, rather than two separate searches
that might differ for unrelated reasons.

Every pair is checked for an identical journey time. A heuristic that
overestimates would show up here as a faster search returning worse routes,
which is the failure mode worth guarding against.

Run with: python scripts/benchmark_pathfinding.py [pairs]
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tube_planner.graph import load_graph, load_positions  # noqa: E402
from tube_planner.pathfinding import max_speed_km_per_min, shortest_route  # noqa: E402

DEFAULT_PAIRS = 2000
SEED = 20240718  # fixed, so the reported numbers are reproducible


def run(graph, positions, pairs):
    # Derived once, exactly as the API does when serving requests.
    speed = max_speed_km_per_min(graph)

    totals = {"dijkstra": 0, "astar": 0}
    elapsed = {"dijkstra": 0.0, "astar": 0.0}
    mismatches = []

    for start, end in pairs:
        began = time.perf_counter()
        baseline = shortest_route(graph, start, end)
        elapsed["dijkstra"] += time.perf_counter() - began

        began = time.perf_counter()
        guided = shortest_route(
            graph, start, end, positions=positions, network_max_speed=speed
        )
        elapsed["astar"] += time.perf_counter() - began

        totals["dijkstra"] += baseline.states_expanded
        totals["astar"] += guided.states_expanded

        if abs(baseline.total_time_min - guided.total_time_min) > 1e-6:
            mismatches.append((start, end, baseline.total_time_min, guided.total_time_min))

    return totals, elapsed, mismatches


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PAIRS

    graph = load_graph()
    positions = load_positions()
    stations = sorted(graph)

    rng = random.Random(SEED)
    pairs = []
    while len(pairs) < count:
        start, end = rng.sample(stations, 2)
        pairs.append((start, end))

    totals, elapsed, mismatches = run(graph, positions, pairs)

    n = len(pairs)
    saved = 1 - totals["astar"] / totals["dijkstra"]
    faster = 1 - elapsed["astar"] / elapsed["dijkstra"]

    print(f"{len(stations)} stations, {n} random journeys\n")
    print(f"{'':<12}{'states expanded':>18}{'mean':>10}{'total time':>14}")
    print("-" * 54)
    for name, label in (("dijkstra", "Dijkstra"), ("astar", "A*")):
        print(
            f"{label:<12}{totals[name]:>18,}{totals[name] / n:>10.1f}"
            f"{elapsed[name]:>13.2f}s"
        )
    print("-" * 54)
    print(f"A* explores {saved:.1%} fewer states and runs {faster:.1%} faster.")

    if mismatches:
        print(f"\nWARNING: {len(mismatches)} routes disagreed on journey time:")
        for start, end, a, b in mismatches[:5]:
            print(f"  {start} -> {end}: Dijkstra {a}, A* {b}")
        raise SystemExit(1)
    print(f"All {n} routes returned identical journey times.")


if __name__ == "__main__":
    main()

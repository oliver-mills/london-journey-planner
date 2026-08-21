"""Correctness of the A* search and of the live-conditions weighting.

The load-bearing test here is that A* and a zero-heuristic Dijkstra return
routes of identical cost. A* is only worth having if it is provably the same
answer, faster -- an admissible heuristic that turns out not to be admissible
shows up as a cheaper-but-wrong route, which is exactly what this compares.
"""
import math

import pytest

from tube_planner.geo import Position, haversine_km
from tube_planner.graph import Edge
from tube_planner.pathfinding import (
    NoRouteError,
    max_speed_km_per_min,
    shortest_route,
)


def make_graph(edges):
    """edges: list of (line, a, b, distance_km, time_min) -> bidirectional graph"""
    graph = {}
    for line, a, b, distance_km, time_min in edges:
        graph.setdefault(a, [])
        graph.setdefault(b, [])
        graph[a].append(Edge(line, b, distance_km, time_min))
        graph[b].append(Edge(line, a, distance_km, time_min))
    return graph


@pytest.fixture(scope="module")
def grid():
    """A 6x6 grid of stations with real geography.

    Rows and columns are separate lines, so crossing the grid diagonally
    forces interchanges and the search has genuinely competing options.
    Journey times vary per edge so no two routes are trivially tied.
    """
    size = 6
    positions = {}
    for row in range(size):
        for col in range(size):
            positions[f"R{row}C{col}"] = Position(
                lat=51.40 + row * 0.02, lon=-0.30 + col * 0.04
            )

    edges = []
    for row in range(size):
        for col in range(size):
            here = f"R{row}C{col}"
            if col + 1 < size:
                right = f"R{row}C{col + 1}"
                distance = haversine_km(positions[here], positions[right])
                # A deterministic wobble in speed, so edge times are not all
                # in constant proportion to distance.
                edges.append((f"Row{row}", here, right, distance, distance * (1.4 + 0.1 * ((row + col) % 4))))
            if row + 1 < size:
                below = f"R{row + 1}C{col}"
                distance = haversine_km(positions[here], positions[below])
                edges.append((f"Col{col}", here, below, distance, distance * (1.5 + 0.1 * ((row * col) % 3))))

    return make_graph(edges), positions


def test_astar_agrees_with_dijkstra_on_every_pair(grid):
    """Same optimal cost for all 1260 ordered pairs, with and without the heuristic."""
    graph, positions = grid
    stations = sorted(graph)

    for start in stations:
        for end in stations:
            if start == end:
                continue
            dijkstra = shortest_route(graph, start, end)
            astar = shortest_route(graph, start, end, positions=positions)
            assert astar.total_time_min == pytest.approx(dijkstra.total_time_min), (
                f"{start} -> {end}"
            )


def test_astar_never_explores_more_than_dijkstra(grid):
    graph, positions = grid
    stations = sorted(graph)

    for start in stations[::7]:
        for end in stations[::5]:
            if start == end:
                continue
            dijkstra = shortest_route(graph, start, end)
            astar = shortest_route(graph, start, end, positions=positions)
            assert astar.states_expanded <= dijkstra.states_expanded


def test_astar_actually_prunes_the_search(grid):
    """Guards against a heuristic that is admissible but uselessly weak."""
    graph, positions = grid
    corner_to_corner = dict(start="R0C0", end="R5C5")

    dijkstra = shortest_route(graph, **corner_to_corner)
    astar = shortest_route(graph, **corner_to_corner, positions=positions)
    assert astar.states_expanded < dijkstra.states_expanded


def test_heuristic_never_overestimates_the_true_cost(grid):
    """Admissibility, checked directly against the optimal remaining time."""
    graph, positions = grid
    goal = "R5C5"
    speed = max_speed_km_per_min(graph)

    for station in sorted(graph):
        if station == goal:
            continue
        estimate = haversine_km(positions[station], positions[goal]) / speed
        actual = shortest_route(graph, station, goal, positions=positions).total_time_min
        assert estimate <= actual + 1e-9, station


def test_positions_are_optional(grid):
    """A station with no coordinates must not break the search."""
    graph, positions = grid
    partial = {k: v for k, v in positions.items() if not k.startswith("R2")}

    full = shortest_route(graph, "R0C0", "R5C5", positions=positions)
    sparse = shortest_route(graph, "R0C0", "R5C5", positions=partial)
    assert sparse.total_time_min == pytest.approx(full.total_time_min)


def test_unknown_destination_position_falls_back_to_dijkstra(grid):
    graph, positions = grid
    without_goal = {k: v for k, v in positions.items() if k != "R5C5"}

    route = shortest_route(graph, "R0C0", "R5C5", positions=without_goal)
    baseline = shortest_route(graph, "R0C0", "R5C5")
    assert route.total_time_min == pytest.approx(baseline.total_time_min)
    assert route.states_expanded == baseline.states_expanded


# ---------- Live service conditions ----------


def delayed_network():
    """A fast direct line, and a slower two-hop alternative alongside it."""
    return make_graph(
        [
            ("Direct", "A", "B", 2.0, 10.0),
            ("Alt", "A", "X", 1.0, 6.0),
            ("Alt", "X", "B", 1.0, 6.0),
        ]
    )


def test_undisrupted_route_takes_the_fast_line():
    route = shortest_route(delayed_network(), "A", "B")
    assert route.stations == ["A", "B"]


def test_a_delayed_line_is_abandoned_once_it_is_slower():
    # 10 min * 2.5 = 25 min direct, against 12 min on the alternative.
    route = shortest_route(
        delayed_network(), "A", "B", line_multipliers={"Direct": 2.5}
    )
    assert route.stations == ["A", "X", "B"]


def test_a_delayed_line_is_still_used_when_the_delay_is_mild():
    # 10 min * 1.15 = 11.5 min direct still beats 12 min via the change.
    route = shortest_route(
        delayed_network(), "A", "B", line_multipliers={"Direct": 1.15}
    )
    assert route.stations == ["A", "B"]


def test_a_delayed_line_is_still_used_when_it_is_the_only_way():
    """Degrading a line must never strand the stations it serves."""
    graph = make_graph([("Only", "A", "B", 1.0, 5.0)])
    route = shortest_route(graph, "A", "B", line_multipliers={"Only": 4.0})
    assert route.stations == ["A", "B"]
    assert route.total_time_min == pytest.approx(20.0)


def test_reported_time_includes_the_delay():
    """The journey time shown is the one the route was chosen on."""
    graph = make_graph([("Slowed", "A", "B", 1.0, 4.0)])
    route = shortest_route(graph, "A", "B", line_multipliers={"Slowed": 2.0})
    assert route.total_time_min == pytest.approx(8.0)
    assert route.legs[0].time_min == pytest.approx(8.0)
    # Distance is a property of the track, not of today's service.
    assert route.total_distance_km == pytest.approx(1.0)


def test_a_multiplier_below_one_is_ignored():
    """A line cannot be faster than its timetable; that would break the heuristic."""
    graph = make_graph([("Fast", "A", "B", 1.0, 4.0)])
    route = shortest_route(graph, "A", "B", line_multipliers={"Fast": 0.1})
    assert route.total_time_min == pytest.approx(4.0)


def test_blocked_beats_delayed_when_a_line_is_both():
    """A blocked line is unusable however its multiplier reads."""
    graph = make_graph([("Down", "A", "B", 1.0, 5.0)])
    with pytest.raises(NoRouteError):
        shortest_route(
            graph,
            "A",
            "B",
            blocked_lines=frozenset({"Down"}),
            line_multipliers={"Down": 2.0},
        )


def test_delays_and_the_heuristic_coexist(grid):
    """Multipliers only raise costs, so A* must stay optimal alongside them."""
    graph, positions = grid
    multipliers = {"Row0": 3.0, "Col3": 2.0, "Row4": 1.5}

    for end in ["R5C5", "R0C5", "R3C2"]:
        dijkstra = shortest_route(graph, "R0C0", end, line_multipliers=multipliers)
        astar = shortest_route(
            graph, "R0C0", end, line_multipliers=multipliers, positions=positions
        )
        assert astar.total_time_min == pytest.approx(dijkstra.total_time_min)


def test_max_speed_ignores_degenerate_edges():
    graph = make_graph([("Zero", "A", "B", 0.0, 0.0), ("Real", "B", "C", 2.0, 4.0)])
    assert max_speed_km_per_min(graph) == pytest.approx(0.5)


def test_max_speed_falls_back_when_nothing_is_measurable():
    graph = make_graph([("Zero", "A", "B", 0.0, 0.0)])
    assert math.isfinite(max_speed_km_per_min(graph))

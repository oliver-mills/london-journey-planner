import pytest

from tube_planner.graph import Edge
from tube_planner.pathfinding import (
    NoRouteError,
    UnknownStationError,
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


def test_direct_route_on_one_line():
    graph = make_graph(
        [
            ("Central", "A", "B", 1.0, 2.0),
            ("Central", "B", "C", 1.0, 2.0),
        ]
    )
    route = shortest_route(graph, "A", "C")
    assert route.stations == ["A", "B", "C"]
    assert route.total_time_min == 4.0
    assert route.interchanges == []


def test_picks_faster_route_over_fewer_stops():
    graph = make_graph(
        [
            ("Slow", "A", "B", 1.0, 10.0),
            ("Fast", "A", "C", 1.0, 1.0),
            ("Fast", "C", "B", 1.0, 1.0),
        ]
    )
    route = shortest_route(graph, "A", "B")
    assert route.stations == ["A", "C", "B"]


def test_charges_interchange_penalty_for_line_changes():
    # Direct line is slightly slower than the fastest per-leg time via a
    # change, but the interchange penalty should make staying on one line
    # win once it's cheap enough.
    graph = make_graph(
        [
            ("Direct", "A", "B", 1.0, 5.0),
            ("Line1", "A", "X", 1.0, 1.0),
            ("Line2", "X", "B", 1.0, 1.0),
        ]
    )
    route = shortest_route(graph, "A", "B", interchange_penalty_min=10.0)
    assert route.stations == ["A", "B"]

    route = shortest_route(graph, "A", "B", interchange_penalty_min=0.0)
    assert route.stations == ["A", "X", "B"]


def test_records_interchange_metadata():
    graph = make_graph(
        [
            ("Red", "A", "B", 1.0, 1.0),
            ("Blue", "B", "C", 1.0, 1.0),
        ]
    )
    route = shortest_route(graph, "A", "C")
    assert len(route.interchanges) == 1
    interchange = route.interchanges[0]
    assert interchange.station == "B"
    assert interchange.from_line == "Red"
    assert interchange.to_line == "Blue"


def test_respects_blocked_lines():
    graph = make_graph(
        [
            ("Suspended", "A", "B", 1.0, 1.0),
            ("Working", "A", "C", 1.0, 1.0),
            ("Working", "C", "B", 1.0, 1.0),
        ]
    )
    route = shortest_route(graph, "A", "B", blocked_lines=frozenset({"Suspended"}))
    assert route.stations == ["A", "C", "B"]


def test_raises_when_no_route_exists():
    graph = make_graph([("Central", "A", "B", 1.0, 1.0)])
    graph["Island"] = []
    with pytest.raises(NoRouteError):
        shortest_route(graph, "A", "Island")


def test_raises_for_unknown_station():
    graph = make_graph([("Central", "A", "B", 1.0, 1.0)])
    with pytest.raises(UnknownStationError):
        shortest_route(graph, "A", "Nowhere")


def test_same_start_and_end_is_a_trivial_route():
    graph = make_graph([("Central", "A", "B", 1.0, 1.0)])
    route = shortest_route(graph, "A", "A")
    assert route.stations == ["A"]
    assert route.total_time_min == 0.0
    assert route.legs == []

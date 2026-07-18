from tube_planner.graph import load_graph
from tube_planner.pathfinding import shortest_route


def test_loads_real_station_network():
    graph = load_graph()
    assert "KINGS CROSS ST PANCRAS" in graph
    assert "OXFORD CIRCUS" in graph
    assert len(graph) > 250


def test_graph_is_undirected():
    graph = load_graph()
    for station, edges in graph.items():
        for edge in edges:
            back_edges = graph[edge.to]
            assert any(b.to == station and b.line == edge.line for b in back_edges)


def test_kings_cross_interchange_is_routable_across_all_its_lines():
    # Regression test for a real bug in the source spreadsheet: "Kings
    # Cross" and "Kings Cross St Pancras" were two disconnected nodes,
    # so no route could interchange between the Victoria/Northern/
    # Piccadilly group and the Circle/H&C/Metropolitan group there.
    graph = load_graph()
    route = shortest_route(graph, "EUSTON", "FARRINGDON")
    assert "KINGS CROSS ST PANCRAS" in route.stations


def test_finds_a_known_route():
    graph = load_graph()
    route = shortest_route(graph, "BAKER STREET", "OXFORD CIRCUS")
    assert route.stations[0] == "BAKER STREET"
    assert route.stations[-1] == "OXFORD CIRCUS"
    assert route.total_time_min > 0

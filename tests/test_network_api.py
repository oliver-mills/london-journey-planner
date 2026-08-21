import pytest
from fastapi.testclient import TestClient

from tube_planner import api
from tube_planner.geo import Position
from tube_planner.graph import Edge


@pytest.fixture
def client(monkeypatch):
    test_graph = {
        "A": [Edge("Red", "B", 1.0, 2.0)],
        "B": [Edge("Red", "A", 1.0, 2.0), Edge("Blue", "C", 1.0, 3.0)],
        "C": [Edge("Blue", "B", 1.0, 3.0)],
    }
    positions = {
        "A": Position(lat=51.4, lon=-0.4, zone="3"),
        "B": Position(lat=51.5, lon=-0.1, zone="1"),
        "C": Position(lat=51.6, lon=0.2, zone=None),
    }
    monkeypatch.setattr(api, "_graph", test_graph)
    monkeypatch.setattr(api, "_positions", positions)
    monkeypatch.setattr(api, "_network", None)
    return TestClient(api.app)


def test_network_returns_every_station(client):
    body = client.get("/api/network").json()
    assert {s["id"] for s in body["stations"]} == {"A", "B", "C"}


def test_network_stations_carry_display_names_zones_and_lines(client):
    body = client.get("/api/network").json()
    station_b = next(s for s in body["stations"] if s["id"] == "B")

    assert station_b["name"] == "B"
    assert station_b["zone"] == "1"
    assert station_b["lines"] == ["Blue", "Red"]


def test_network_allows_a_station_without_a_zone(client):
    body = client.get("/api/network").json()
    station_c = next(s for s in body["stations"] if s["id"] == "C")
    assert station_c["zone"] is None


def test_network_emits_each_edge_once_per_line(client):
    body = client.get("/api/network").json()
    # The graph stores both directions of A-B and B-C; the map wants one
    # segment for each, not two overlapping copies.
    assert len(body["edges"]) == 2
    assert {e["line"] for e in body["edges"]} == {"Red", "Blue"}


def test_network_edge_endpoints_match_station_positions(client):
    body = client.get("/api/network").json()
    points = {s["id"]: (s["x"], s["y"]) for s in body["stations"]}
    red = next(e for e in body["edges"] if e["line"] == "Red")

    assert {(red["x1"], red["y1"]), (red["x2"], red["y2"])} == {points["A"], points["B"]}


def test_network_stations_sit_inside_the_viewbox(client):
    body = client.get("/api/network").json()
    for station in body["stations"]:
        assert 0 <= station["x"] <= body["width"]
        assert 0 <= station["y"] <= body["height"]


def test_network_omits_stations_that_have_no_position(client, monkeypatch):
    """A station with no coordinates should drop off the map, not break it."""
    monkeypatch.setattr(
        api, "_positions", {"A": Position(lat=51.4, lon=-0.4), "B": Position(lat=51.5, lon=-0.1)}
    )
    monkeypatch.setattr(api, "_network", None)

    body = client.get("/api/network").json()
    assert {s["id"] for s in body["stations"]} == {"A", "B"}
    # The Blue line only connects B to the unplaceable C, so it cannot be drawn.
    assert {e["line"] for e in body["edges"]} == {"Red"}


def test_route_returns_station_ids_alongside_display_names(client):
    body = client.post("/api/route", json={"start": "A", "end": "C", "avoid_disruptions": False})
    assert body.status_code == 200
    payload = body.json()

    assert payload["station_ids"] == ["A", "B", "C"]
    assert len(payload["station_ids"]) == len(payload["stations"])
    assert payload["end_station_id"] == "C"


def test_max_speed_follows_the_graph_it_was_derived_from(client, monkeypatch):
    """A cached speed bound from another graph would break A* optimality."""
    slow = {"P": [Edge("L", "Q", 1.0, 10.0)], "Q": [Edge("L", "P", 1.0, 10.0)]}
    fast = {"P": [Edge("L", "Q", 10.0, 1.0)], "Q": [Edge("L", "P", 10.0, 1.0)]}

    monkeypatch.setattr(api, "_graph", slow)
    monkeypatch.setattr(api, "_max_speed", None)
    assert api.get_max_speed() == pytest.approx(0.1)

    monkeypatch.setattr(api, "_graph", fast)
    assert api.get_max_speed() == pytest.approx(10.0)

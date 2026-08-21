"""Live TfL status feeding into routing, end to end through the API."""
import pytest
from fastapi.testclient import TestClient

from tube_planner import api, tfl_client
from tube_planner.graph import Edge


@pytest.fixture
def client(monkeypatch):
    # A fast direct line, and a slower alternative running beside it.
    test_graph = {
        "A": [Edge("Direct", "B", 2.0, 10.0), Edge("Alt", "X", 1.0, 7.0)],
        "B": [Edge("Direct", "A", 2.0, 10.0), Edge("Alt", "X", 1.0, 7.0)],
        "X": [Edge("Alt", "A", 1.0, 7.0), Edge("Alt", "B", 1.0, 7.0)],
    }
    monkeypatch.setattr(api, "_graph", test_graph)
    monkeypatch.setattr(api, "_positions", {})
    monkeypatch.setattr(tfl_client, "_cache", {})
    return TestClient(api.app)


def set_statuses(monkeypatch, *pairs):
    statuses = [tfl_client.LineStatus(line, status) for line, status in pairs]
    monkeypatch.setattr(tfl_client, "fetch_line_statuses", lambda use_cache=True: statuses)


def route(client, avoid=True):
    response = client.post(
        "/api/route", json={"start": "A", "end": "B", "avoid_disruptions": avoid}
    )
    assert response.status_code == 200
    return response.json()


def test_good_service_leaves_the_fast_route_alone(client, monkeypatch):
    set_statuses(monkeypatch, ("Direct", "Good Service"), ("Alt", "Good Service"))
    body = route(client)

    assert body["stations"] == ["A", "B"]
    assert body["disruptions"] == []
    assert body["live_status_used"] is True


def test_severe_delays_push_the_route_onto_the_alternative(client, monkeypatch):
    set_statuses(monkeypatch, ("Direct", "Severe Delays"), ("Alt", "Good Service"))
    body = route(client)

    assert body["stations"] == ["A", "X", "B"]
    assert body["total_time_min"] == pytest.approx(14.0)


def test_minor_delays_are_not_enough_to_reroute(client, monkeypatch):
    """A 25% slowdown on a 10 minute hop still beats a 14 minute detour."""
    set_statuses(monkeypatch, ("Direct", "Minor Delays"), ("Alt", "Good Service"))
    body = route(client)

    assert body["stations"] == ["A", "B"]
    assert body["total_time_min"] == pytest.approx(12.5)


def test_a_suspended_line_is_excluded_outright(client, monkeypatch):
    set_statuses(monkeypatch, ("Direct", "Suspended"), ("Alt", "Good Service"))
    body = route(client)

    assert body["stations"] == ["A", "X", "B"]
    direct = next(d for d in body["disruptions"] if d["line"] == "Direct")
    assert direct["avoided"] is True
    assert direct["on_route"] is False


def test_disruptions_explain_a_line_the_route_still_uses(client, monkeypatch):
    set_statuses(monkeypatch, ("Direct", "Minor Delays"), ("Alt", "Good Service"))
    body = route(client)

    direct = next(d for d in body["disruptions"] if d["line"] == "Direct")
    assert direct["status"] == "Minor Delays"
    assert direct["slowdown"] == pytest.approx(1.25)
    assert direct["avoided"] is False
    assert direct["on_route"] is True
    assert direct["colour"].startswith("#")


def test_undisrupted_lines_are_not_reported(client, monkeypatch):
    set_statuses(monkeypatch, ("Direct", "Severe Delays"), ("Alt", "Good Service"))
    body = route(client)
    assert [d["line"] for d in body["disruptions"]] == ["Direct"]


def test_part_suspended_degrades_rather_than_stranding_the_line(client, monkeypatch):
    """TfL never says which part, so the line stays usable as a last resort."""
    set_statuses(monkeypatch, ("Direct", "Part Suspended"), ("Alt", "Suspended"))
    body = route(client)

    assert body["stations"] == ["A", "B"]
    assert body["total_time_min"] == pytest.approx(40.0)


def test_opting_out_ignores_live_status_entirely(client, monkeypatch):
    set_statuses(monkeypatch, ("Direct", "Severe Delays"), ("Alt", "Good Service"))
    body = route(client, avoid=False)

    assert body["stations"] == ["A", "B"]
    assert body["total_time_min"] == pytest.approx(10.0)
    assert body["live_status_used"] is False
    assert body["disruptions"] == []


def test_routing_survives_the_tfl_api_being_down(client, monkeypatch):
    def boom(use_cache=True):
        raise tfl_client.TflApiError("upstream is down")

    monkeypatch.setattr(tfl_client, "fetch_line_statuses", boom)
    body = route(client)

    assert body["stations"] == ["A", "B"]
    assert body["live_status_used"] is False
    assert body["disruptions"] == []

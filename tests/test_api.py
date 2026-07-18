import pytest
from fastapi.testclient import TestClient

from tube_planner import api, tfl_client
from tube_planner.graph import Edge


@pytest.fixture
def client(monkeypatch):
    test_graph = {
        "A": [Edge("Red", "B", 1.0, 2.0)],
        "B": [Edge("Red", "A", 1.0, 2.0), Edge("Blue", "C", 1.0, 3.0)],
        "C": [Edge("Blue", "B", 1.0, 3.0)],
    }
    monkeypatch.setattr(api, "_graph", test_graph)
    monkeypatch.setattr(tfl_client, "_cache", {})
    return TestClient(api.app)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_list_stations(client):
    response = client.get("/api/stations")
    assert response.status_code == 200
    ids = {s["id"] for s in response.json()}
    assert ids == {"A", "B", "C"}


def test_find_route(client, monkeypatch):
    monkeypatch.setattr(
        tfl_client, "fetch_line_statuses", lambda use_cache=True: []
    )
    response = client.post("/api/route", json={"start": "A", "end": "C"})
    assert response.status_code == 200
    body = response.json()
    assert body["stations"] == ["A", "B", "C"]
    assert body["end_station_id"] == "C"
    assert len(body["legs"]) == 2
    assert len(body["interchanges"]) == 1


def test_route_unknown_station_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        tfl_client, "fetch_line_statuses", lambda use_cache=True: []
    )
    response = client.post("/api/route", json={"start": "A", "end": "NOWHERE"})
    assert response.status_code == 404


def test_route_avoids_blocked_lines(client, monkeypatch):
    monkeypatch.setattr(
        tfl_client,
        "fetch_line_statuses",
        lambda use_cache=True: [tfl_client.LineStatus("Blue", "Suspended")],
    )
    response = client.post("/api/route", json={"start": "A", "end": "C"})
    assert response.status_code == 422


def test_route_degrades_gracefully_when_tfl_api_down(client, monkeypatch):
    def raise_error(use_cache=True):
        raise tfl_client.TflApiError("boom")

    monkeypatch.setattr(tfl_client, "fetch_line_statuses", raise_error)
    response = client.post("/api/route", json={"start": "A", "end": "C"})
    assert response.status_code == 200


def test_review_round_trip(client, monkeypatch):
    added = []

    def fake_add_review(station, author, rating, comment):
        added.append((station, author, rating, comment))
        from tube_planner.reviews import Review

        return Review(author or "Anonymous", rating, comment, "2026-01-01 00:00:00")

    def fake_reviews_for_station(station, limit=25):
        from tube_planner.reviews import Review

        return [Review("Alex", 5, "Great station", "2026-01-01 00:00:00")]

    monkeypatch.setattr(api.reviews_store, "add_review", fake_add_review)
    monkeypatch.setattr(api.reviews_store, "reviews_for_station", fake_reviews_for_station)

    post_response = client.post(
        "/api/reviews/A", json={"author": "Alex", "rating": 5, "comment": "Great station"}
    )
    assert post_response.status_code == 200
    assert added == [("A", "Alex", 5, "Great station")]

    get_response = client.get("/api/reviews/A")
    assert get_response.status_code == 200
    assert get_response.json()[0]["comment"] == "Great station"


def test_review_rejects_invalid_rating(client):
    response = client.post("/api/reviews/A", json={"rating": 9, "comment": "too high"})
    assert response.status_code == 422

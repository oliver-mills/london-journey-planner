from tube_planner import tfl_client


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetch_line_statuses_parses_response(monkeypatch):
    tfl_client._cache.clear()
    payload = [
        {"name": "Central", "lineStatuses": [{"statusSeverityDescription": "Good Service"}]},
        {"name": "Northern", "lineStatuses": [{"statusSeverityDescription": "Minor Delays"}]},
    ]
    monkeypatch.setattr(tfl_client.requests, "get", lambda *a, **k: FakeResponse(payload))

    statuses = tfl_client.fetch_line_statuses(use_cache=False)

    assert statuses == [
        tfl_client.LineStatus("Central", "Good Service"),
        tfl_client.LineStatus("Northern", "Minor Delays"),
    ]


def test_blocked_lines_only_includes_blocking_severities():
    statuses = [
        tfl_client.LineStatus("Central", "Good Service"),
        tfl_client.LineStatus("Northern", "Minor Delays"),
        tfl_client.LineStatus("Circle", "Suspended"),
        tfl_client.LineStatus("Jubilee", "Planned Closure"),
    ]
    assert tfl_client.blocked_lines(statuses) == frozenset({"Circle", "Jubilee"})


def test_results_are_cached_between_calls(monkeypatch):
    tfl_client._cache.clear()
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return FakeResponse(
            [{"name": "Central", "lineStatuses": [{"statusSeverityDescription": "Good Service"}]}]
        )

    monkeypatch.setattr(tfl_client.requests, "get", fake_get)

    tfl_client.fetch_line_statuses()
    tfl_client.fetch_line_statuses()

    assert len(calls) == 1

"""Client for the TfL Unified API's tube line status endpoint.

Works without an API key (subject to TfL's public rate limit); set
TFL_APP_KEY to raise that limit. Responses are cached briefly so refreshing
the page repeatedly doesn't hammer the upstream API.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests
import truststore

# Verify TLS certificates against the OS trust store rather than certifi's
# bundled list. On networks that do TLS interception (school/corporate
# firewalls, some antivirus software), certifi often doesn't trust the
# interception root cert even though the OS already does, which otherwise
# surfaces as a confusing SSLCertVerificationError.
truststore.inject_into_ssl()

STATUS_URL = "https://api.tfl.gov.uk/Line/Mode/tube/Status"
CACHE_TTL_SECONDS = 60

# Severities under which no train runs at all, so the line cannot form part
# of any route.
BLOCKING_SEVERITIES = {
    "Suspended",
    "Closed",
    "Planned Closure",
    "Service Closed",
    "Not Running",
}

# Severities where the line still runs, but not as timetabled. These scale a
# line's travel times so the planner treats it as the slower option it has
# become, and routes around it only when doing so is genuinely quicker.
#
# "Part Suspended" and "Part Closure" are deliberately here rather than in
# BLOCKING_SEVERITIES: TfL does not say *which* part is affected, and
# discarding a whole line on that basis strands stations it still serves --
# a route that warns you is more useful than no route at all. The multiplier
# is large enough that any working alternative wins.
DELAY_MULTIPLIERS = {
    "Part Suspended": 4.0,
    "Part Closure": 3.0,
    "Bus Service": 3.0,
    "Severe Delays": 2.5,
    "Reduced Service": 1.6,
    "Diverted": 1.5,
    "Minor Delays": 1.25,
    "Special Service": 1.2,
    "Change of frequency": 1.15,
}


class TflApiError(Exception):
    pass


@dataclass(frozen=True)
class LineStatus:
    line: str
    status: str


_cache: dict[str, tuple[float, list[LineStatus]]] = {}


def fetch_line_statuses(use_cache: bool = True) -> list[LineStatus]:
    now = time.time()
    if use_cache and "statuses" in _cache:
        cached_at, statuses = _cache["statuses"]
        if now - cached_at < CACHE_TTL_SECONDS:
            return statuses

    params = {}
    app_key = os.environ.get("TFL_APP_KEY")
    if app_key:
        params["app_key"] = app_key

    try:
        response = requests.get(STATUS_URL, params=params, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TflApiError(str(exc)) from exc

    statuses = [
        LineStatus(
            line=entry["name"],
            status=entry["lineStatuses"][0]["statusSeverityDescription"],
        )
        for entry in response.json()
    ]
    _cache["statuses"] = (now, statuses)
    return statuses


def blocked_lines(statuses: list[LineStatus]) -> frozenset[str]:
    """Lines that cannot be used at all right now."""
    return frozenset(s.line for s in statuses if s.status in BLOCKING_SEVERITIES)


def line_multipliers(statuses: list[LineStatus]) -> dict[str, float]:
    """Travel-time multipliers for lines running below their timetable.

    Only degraded lines appear; anything running normally is simply absent,
    which the planner reads as a multiplier of 1.0. Blocked lines are left
    out too -- they are excluded by `blocked_lines`, not merely slowed.
    """
    return {
        s.line: DELAY_MULTIPLIERS[s.status]
        for s in statuses
        if s.status in DELAY_MULTIPLIERS and s.status not in BLOCKING_SEVERITIES
    }

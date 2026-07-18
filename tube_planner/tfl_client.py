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

# Severities under which TfL considers the line effectively unusable for
# journey planning purposes.
BLOCKING_SEVERITIES = {
    "Suspended",
    "Part Suspended",
    "Planned Closure",
    "Service Closed",
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
    return frozenset(s.line for s in statuses if s.status in BLOCKING_SEVERITIES)

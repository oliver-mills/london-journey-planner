"""Fetches station coordinates and fare zones from the TfL Unified API and
caches them to data/raw/station_coordinates.json.

The raw spreadsheet the station graph is built from carries no geography at
all -- only line, station pair, distance and time -- so there is nothing in
it to draw a map with. This script enriches the network with real lat/lon
positions (and fare zones) pulled from TfL's StopPoint data.

The result is committed to the repo rather than fetched at build time, so
`build_database.py` stays reproducible and works offline. Re-run this script
only when you want to refresh the upstream data:

    python scripts/fetch_station_coordinates.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

import requests
import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "raw" / "station_coordinates.json"
DB_PATH = ROOT / "data" / "tube.db"

# Tube lines, plus the Overground lines that carry the stations our historic
# source data still files under the old "East London" line. TfL split the
# Overground into named lines (Windrush, Mildmay, ...) in 2024, so there is
# no longer a single "london-overground" id to query.
LINE_IDS = [
    "bakerloo",
    "central",
    "circle",
    "district",
    "hammersmith-city",
    "jubilee",
    "metropolitan",
    "northern",
    "piccadilly",
    "victoria",
    "waterloo-city",
    "windrush",
    "mildmay",
    "lioness",
    "weaver",
    "suffragette",
    "liberty",
]

STOP_POINTS_URL = "https://api.tfl.gov.uk/Line/{line_id}/StopPoints"

# Unauthenticated callers get a low request quota, and this script makes one
# request per line. Setting TFL_APP_KEY raises the quota; without it, backing
# off and retrying is usually enough to get through all of them.
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 5

# Station names that don't survive normalisation into a match, resolved by
# hand against TfL's official station list. Keyed by our normalised name.
COORDINATE_ALIASES: dict[str, str] = {
    # Our source data predates these renamings.
    "HEATHROW 123": "HEATHROW TERMINALS 2 AND 3",
    "HEATHROW TERMINAL FOUR": "HEATHROW TERMINAL 4",
    "HIGHBURY": "HIGHBURY AND ISLINGTON",
    "WALTHAMSTOW": "WALTHAMSTOW CENTRAL",
    "ST JAMES PARK": "ST JAMESS PARK",
    "NEW CROSS": "NEW CROSS ELL",
    # Shoreditch (East London line) closed in 2006; Shoreditch High Street
    # opened ~300m away as its replacement. Close enough to plot.
    "SHOREDITCH": "SHOREDITCH HIGH STREET",
}

_NOISE_WORDS = re.compile(r"\b(UNDERGROUND|OVERGROUND|RAIL|DLR|STATION)\b")
_PARENTHETICAL = re.compile(r"\(([^)]*)\)")


def normalise(name: str) -> str:
    """Reduces a station name to a comparable key.

    TfL's `commonName` ("King's Cross St. Pancras Underground Station")
    and our spreadsheet's ("KINGS CROSS ST PANCRAS") describe the same
    station in quite different registers, so both sides get flattened:
    punctuation dropped, "&" spelled out, and the "Underground Station"
    boilerplate and any parenthetical qualifier removed.
    """
    text = name.upper()
    text = _PARENTHETICAL.sub(" ", text)
    text = _NOISE_WORDS.sub(" ", text)
    text = text.replace("&", " AND ")
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    return " ".join(text.split())


def _get(url: str, params: dict[str, str]) -> requests.Response:
    """GETs `url`, retrying with linear backoff when TfL rate-limits us."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.get(url, params=params, timeout=30)
        if response.status_code != 429 or attempt == MAX_ATTEMPTS:
            response.raise_for_status()
            return response
        wait = BACKOFF_SECONDS * attempt
        print(f"  rate-limited, retrying in {wait}s ({attempt}/{MAX_ATTEMPTS - 1})")
        time.sleep(wait)
    raise AssertionError("unreachable")


def fetch_stop_points() -> dict[str, dict]:
    """Returns {normalised name: {name, lat, lon, zone}} across every line."""
    params = {}
    app_key = os.environ.get("TFL_APP_KEY")
    if app_key:
        params["app_key"] = app_key

    stops: dict[str, dict] = {}
    for line_id in LINE_IDS:
        response = _get(STOP_POINTS_URL.format(line_id=line_id), params)
        for stop in response.json():
            # Stripping the parenthetical qualifier collapses the likes of
            # "Edgware Road (Circle Line)" and "Edgware Road (Bakerloo)"
            # onto one key. Our graph models those as a single node too, and
            # the two are ~100m apart, so first-seen wins is fine here.
            key = normalise(stop["commonName"])
            if key in stops:
                continue
            zone = next(
                (
                    prop["value"]
                    for prop in stop.get("additionalProperties", [])
                    if prop.get("key") == "Zone"
                ),
                None,
            )
            stops[key] = {
                "tfl_name": stop["commonName"],
                "lat": round(stop["lat"], 6),
                "lon": round(stop["lon"], 6),
                "zone": zone,
            }
    return stops


def station_names() -> list[str]:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} not found. Run `python scripts/build_database.py` first."
        )
    conn = sqlite3.connect(DB_PATH)
    try:
        return [row[0] for row in conn.execute("SELECT name FROM stations ORDER BY name")]
    finally:
        conn.close()


def match(names: list[str], stops: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    matched: dict[str, dict] = {}
    unmatched: list[str] = []
    for name in names:
        key = normalise(name)
        key = COORDINATE_ALIASES.get(key, key)
        stop = stops.get(key)
        if stop is None:
            unmatched.append(name)
            continue
        matched[name] = {"lat": stop["lat"], "lon": stop["lon"], "zone": stop["zone"]}
    return matched, unmatched


def main() -> None:
    names = station_names()
    stops = fetch_stop_points()
    matched, unmatched = match(names, stops)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(matched, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote {OUT_PATH} with {len(matched)}/{len(names)} stations located")
    if unmatched:
        print("Unmatched (no coordinates, will not be drawn on the map):")
        for name in unmatched:
            print(f"  {name}")


if __name__ == "__main__":
    main()

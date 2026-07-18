"""Builds data/tube.db from the raw TfL station spreadsheet.

The source spreadsheet (data/raw/station_database.xlsx) lists each line as a
set of directed rows, one per direction of travel (e.g. "Bakerloo Southbound"
and "Bakerloo Northbound"), and station names are inconsistently split across
platform/branch qualifiers. This script normalises that into a clean,
undirected station graph stored in SQLite:

  stations(id, name)
  edges(id, line, station_a_id, station_b_id, distance_km, time_min)

Run with: python scripts/build_database.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import openpyxl

RAW_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "station_database.xlsx"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tube.db"

# Some rows in the source data name the same physical station differently
# depending on which branch/platform/line the row was recorded for. Left
# unmerged, these silently split a single real station into disconnected
# graph nodes. The most striking case: "KINGS CROSS" (Victoria/Northern/
# Piccadilly rows) and "KINGS CROSS ST PANCRAS" (Circle/H&C/Metropolitan
# rows) are the same interchange station, but with the raw data no route
# could ever change between those two groups of lines there.
STATION_ALIASES: dict[str, str] = {
    "KINGS CROSS": "KINGS CROSS ST PANCRAS",
    "BAKER STREET (CIRCLE)": "BAKER STREET",
    "BAKER STREET (MET)": "BAKER STREET",
    "BAKER STREET (METROPOLITAN)": "BAKER STREET",
    "EUSTON (CITY)": "EUSTON",
    "EUSTON (CX)": "EUSTON",
    "FINCHLEY CENTRAL (HB)": "FINCHLEY CENTRAL",
    "HAMMERSMITH (DISTRICT)": "HAMMERSMITH",
    "HAMMERSMITH (H&C)": "HAMMERSMITH",
    "KENNINGTON (CITY)": "KENNINGTON",
    "KENNINGTON (CX)": "KENNINGTON",
    "PADDINGTON (CIRCLE)": "PADDINGTON",
    "PADDINGTON (Dis)": "PADDINGTON",
    "PADDINGTON (H&C)": "PADDINGTON",
    # "KENSINGTON (OLYMPIA)" is a genuine, distinct official station name
    # and is intentionally left alone.
}

LINE_NAME_FIXES: dict[str, str] = {
    "H & C": "Hammersmith & City",
}


def normalise_station(raw: str) -> str:
    name = raw.strip()
    return STATION_ALIASES.get(name, name)


def normalise_line(raw: str) -> str:
    name = raw.strip()
    return LINE_NAME_FIXES.get(name, name)


def read_rows() -> list[tuple[str, str, str, float, float]]:
    """Returns (line, station_a, station_b, distance_km, time_min) tuples,
    deduplicated per line so that direction/branch variants of the same
    physical edge collapse into one undirected edge with averaged weights.
    """
    wb = openpyxl.load_workbook(RAW_PATH, read_only=True, data_only=True)
    ws = wb.active

    grouped: dict[tuple[str, frozenset[str]], list[tuple[float, float]]] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        line, _direction, station_a, station_b, distance_km, time_min = row[:6]
        if line is None or station_a is None or station_b is None:
            continue

        line = normalise_line(line)
        station_a = normalise_station(station_a)
        station_b = normalise_station(station_b)
        if station_a == station_b:
            continue

        key = (line, frozenset((station_a, station_b)))
        grouped.setdefault(key, []).append((float(distance_km), float(time_min)))

    edges = []
    for (line, pair), weights in grouped.items():
        station_a, station_b = sorted(pair)
        avg_distance = sum(w[0] for w in weights) / len(weights)
        avg_time = sum(w[1] for w in weights) / len(weights)
        edges.append((line, station_a, station_b, round(avg_distance, 3), round(avg_time, 3)))

    return edges


def build_database(edges: list[tuple[str, str, str, float, float]]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE stations (
            id   INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE edges (
            id            INTEGER PRIMARY KEY,
            line          TEXT NOT NULL,
            station_a_id  INTEGER NOT NULL REFERENCES stations(id),
            station_b_id  INTEGER NOT NULL REFERENCES stations(id),
            distance_km   REAL NOT NULL,
            time_min      REAL NOT NULL
        );

        CREATE TABLE reviews (
            id          INTEGER PRIMARY KEY,
            station_id  INTEGER NOT NULL REFERENCES stations(id),
            author      TEXT NOT NULL,
            rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment     TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )

    station_ids: dict[str, int] = {}

    def station_id(name: str) -> int:
        if name not in station_ids:
            cur = conn.execute("INSERT INTO stations (name) VALUES (?)", (name,))
            station_ids[name] = cur.lastrowid
        return station_ids[name]

    for line, station_a, station_b, distance_km, time_min in edges:
        a_id = station_id(station_a)
        b_id = station_id(station_b)
        conn.execute(
            "INSERT INTO edges (line, station_a_id, station_b_id, distance_km, time_min) "
            "VALUES (?, ?, ?, ?, ?)",
            (line, a_id, b_id, distance_km, time_min),
        )

    conn.commit()
    conn.close()


def main() -> None:
    edges = read_rows()
    build_database(edges)
    print(f"Built {DB_PATH} with {len(edges)} edges")


if __name__ == "__main__":
    main()

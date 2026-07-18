"""Station review storage, backed by the same SQLite database as the
station graph (see scripts/build_database.py for the reviews table schema).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .graph import DB_PATH


class UnknownStationError(KeyError):
    pass


@dataclass(frozen=True)
class Review:
    author: str
    rating: int
    comment: str
    created_at: str


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def _station_id(conn: sqlite3.Connection, station: str) -> int:
    row = conn.execute("SELECT id FROM stations WHERE name = ?", (station,)).fetchone()
    if row is None:
        raise UnknownStationError(station)
    return row[0]


def add_review(
    station: str,
    author: str,
    rating: int,
    comment: str,
    db_path: Path = DB_PATH,
) -> Review:
    if not 1 <= rating <= 5:
        raise ValueError("rating must be between 1 and 5")
    if not comment.strip():
        raise ValueError("comment must not be empty")

    conn = _connect(db_path)
    try:
        station_id = _station_id(conn, station)
        conn.execute(
            "INSERT INTO reviews (station_id, author, rating, comment) VALUES (?, ?, ?, ?)",
            (station_id, author.strip() or "Anonymous", rating, comment.strip()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT author, rating, comment, created_at FROM reviews WHERE id = last_insert_rowid()"
        ).fetchone()
        return Review(*row)
    finally:
        conn.close()


def reviews_for_station(station: str, limit: int = 25, db_path: Path = DB_PATH) -> list[Review]:
    conn = _connect(db_path)
    try:
        station_id = _station_id(conn, station)
        rows = conn.execute(
            "SELECT author, rating, comment, created_at FROM reviews "
            "WHERE station_id = ? ORDER BY id DESC LIMIT ?",
            (station_id, limit),
        ).fetchall()
        return [Review(*row) for row in rows]
    finally:
        conn.close()

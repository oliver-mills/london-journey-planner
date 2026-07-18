"""Loads the station network from data/tube.db into an in-memory adjacency
list graph, which is what the pathfinding module actually operates on.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tube.db"


@dataclass(frozen=True)
class Edge:
    line: str
    to: str
    distance_km: float
    time_min: float


Graph = dict[str, list[Edge]]


def load_graph(db_path: Path = DB_PATH) -> Graph:
    if not db_path.exists():
        raise FileNotFoundError(
            f"{db_path} not found. Run `python scripts/build_database.py` first."
        )

    conn = sqlite3.connect(db_path)
    try:
        stations = dict(conn.execute("SELECT id, name FROM stations"))
        graph: Graph = {name: [] for name in stations.values()}

        rows = conn.execute(
            "SELECT line, station_a_id, station_b_id, distance_km, time_min FROM edges"
        )
        for line, a_id, b_id, distance_km, time_min in rows:
            a, b = stations[a_id], stations[b_id]
            graph[a].append(Edge(line, b, distance_km, time_min))
            graph[b].append(Edge(line, a, distance_km, time_min))

        return graph
    finally:
        conn.close()


def all_lines(graph: Graph) -> list[str]:
    return sorted({edge.line for edges in graph.values() for edge in edges})

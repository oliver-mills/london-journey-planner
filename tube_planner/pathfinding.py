"""Shortest-route pathfinding over the station graph.

This is a state-space Dijkstra: each queue entry is keyed on
(station, line_currently_on), not just station. That's what lets it charge a
realistic interchange time penalty only when a route actually changes line,
rather than treating every hop as equally free the way a plain single-graph
Dijkstra over station nodes would.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

from .graph import Edge, Graph

INTERCHANGE_PENALTY_MIN = 3.0
NO_LINE = ""  # sentinel meaning "not yet boarded a line" (only true at the origin)


class UnknownStationError(KeyError):
    pass


class NoRouteError(Exception):
    pass


@dataclass(frozen=True)
class Leg:
    line: str
    from_station: str
    to_station: str
    time_min: float
    distance_km: float


@dataclass(frozen=True)
class Interchange:
    station: str
    from_line: str
    to_line: str


@dataclass(frozen=True)
class Route:
    stations: list[str]
    legs: list[Leg]
    interchanges: list[Interchange]
    total_time_min: float
    total_distance_km: float


def shortest_route(
    graph: Graph,
    start: str,
    end: str,
    blocked_lines: frozenset[str] = frozenset(),
    interchange_penalty_min: float = INTERCHANGE_PENALTY_MIN,
) -> Route:
    """Finds the fastest route from `start` to `end`, minimising travel time
    plus a fixed penalty for every line change.

    Raises UnknownStationError if either station isn't in the graph, or
    NoRouteError if the two stations aren't connected (e.g. every line
    between them is in `blocked_lines`).
    """
    if start not in graph:
        raise UnknownStationError(start)
    if end not in graph:
        raise UnknownStationError(end)

    State = tuple[str, str]  # (station, line arrived on)
    start_state: State = (start, NO_LINE)

    best_time: dict[State, float] = {start_state: 0.0}
    came_from: dict[State, tuple[State, Edge]] = {}
    visited: set[State] = set()

    queue: list[tuple[float, str, str]] = [(0.0, start, NO_LINE)]

    goal_state: State | None = None
    while queue:
        time_so_far, station, line = heapq.heappop(queue)
        state = (station, line)
        if state in visited:
            continue
        visited.add(state)

        if station == end:
            goal_state = state
            break

        for edge in graph[station]:
            if edge.line in blocked_lines:
                continue
            next_state = (edge.to, edge.line)
            if next_state in visited:
                continue

            penalty = interchange_penalty_min if line not in (NO_LINE, edge.line) else 0.0
            new_time = time_so_far + edge.time_min + penalty

            if new_time < best_time.get(next_state, float("inf")):
                best_time[next_state] = new_time
                came_from[next_state] = (state, edge)
                heapq.heappush(queue, (new_time, edge.to, edge.line))

    if goal_state is None:
        raise NoRouteError(f"No route found between {start!r} and {end!r}")

    legs: list[Leg] = []
    state = goal_state
    while state != start_state:
        prev_state, edge = came_from[state]
        legs.append(Leg(edge.line, prev_state[0], state[0], edge.time_min, edge.distance_km))
        state = prev_state
    legs.reverse()

    stations = [start] + [leg.to_station for leg in legs]

    interchanges = [
        Interchange(legs[i].from_station, legs[i - 1].line, legs[i].line)
        for i in range(1, len(legs))
        if legs[i].line != legs[i - 1].line
    ]

    return Route(
        stations=stations,
        legs=legs,
        interchanges=interchanges,
        total_time_min=round(sum(leg.time_min for leg in legs), 1),
        total_distance_km=round(sum(leg.distance_km for leg in legs), 2),
    )

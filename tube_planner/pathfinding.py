"""Shortest-route pathfinding over the station graph.

This is a state-space A*: each queue entry is keyed on
(station, line_currently_on), not just station. That's what lets it charge a
realistic interchange time penalty only when a route actually changes line,
rather than treating every hop as equally free the way a plain search over
station nodes would.

The heuristic is straight-line distance to the destination divided by the
fastest speed anywhere on the network, which is admissible: no real journey
can beat flying directly there at the network's top speed. Passing no station
positions leaves the heuristic at zero, which degrades the search back into
exactly the Dijkstra it replaced -- useful for benchmarking, and what happens
automatically for any station whose coordinates are missing.

Live service conditions feed in as two separate ideas:

  * `blocked_lines` -- lines that cannot be used at all (suspended, closed),
    which are skipped outright.
  * `line_multipliers` -- lines that still run but slower than scheduled, so
    their travel times are scaled up. Because these only ever make edges more
    expensive, the heuristic stays admissible with them in play.
"""
from __future__ import annotations

import heapq
from collections.abc import Mapping
from dataclasses import dataclass

from .geo import Position, haversine_km
from .graph import Edge, Graph

INTERCHANGE_PENALTY_MIN = 3.0
NO_LINE = ""  # sentinel meaning "not yet boarded a line" (only true at the origin)

# Fallback for a graph with no usable edge speeds; only reachable in tests
# built from degenerate data.
FALLBACK_SPEED_KM_PER_MIN = 1.0


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
    # How many states the search settled before reaching the goal. Carried
    # for benchmarking A* against the zero-heuristic (Dijkstra) case.
    states_expanded: int = 0


def max_speed_km_per_min(graph: Graph) -> float:
    """The fastest speed on any edge, which bounds how good the future can be.

    Dividing straight-line distance by this is what keeps the heuristic
    admissible: nothing on the network travels faster, so the estimate can
    never exceed the true remaining time.
    """
    speeds = [
        edge.distance_km / edge.time_min
        for edges in graph.values()
        for edge in edges
        if edge.time_min > 0 and edge.distance_km > 0
    ]
    return max(speeds) if speeds else FALLBACK_SPEED_KM_PER_MIN


def _make_heuristic(
    graph: Graph,
    positions: Mapping[str, Position] | None,
    end: str,
    network_max_speed: float | None = None,
):
    """Builds h(station): an optimistic minutes-remaining estimate.

    Returns a constant zero when the destination has no known position, or
    when no positions were supplied at all -- a zero heuristic is trivially
    admissible, so the search stays correct and simply explores more.
    """
    goal = positions.get(end) if positions else None
    if goal is None:
        return lambda station: 0.0

    speed = network_max_speed or max_speed_km_per_min(graph)
    # A station is relaxed once per edge arriving at it, but its distance to
    # the goal never changes during a search. Without this cache the trig
    # bill dominates: on a network this small it costs more than the states
    # the heuristic saves.
    cache: dict[str, float] = {}

    def heuristic(station: str) -> float:
        estimate = cache.get(station)
        if estimate is None:
            position = positions.get(station)
            estimate = haversine_km(position, goal) / speed if position else 0.0
            cache[station] = estimate
        return estimate

    return heuristic


def shortest_route(
    graph: Graph,
    start: str,
    end: str,
    blocked_lines: frozenset[str] = frozenset(),
    line_multipliers: Mapping[str, float] | None = None,
    positions: Mapping[str, Position] | None = None,
    interchange_penalty_min: float = INTERCHANGE_PENALTY_MIN,
    network_max_speed: float | None = None,
) -> Route:
    """Finds the fastest route from `start` to `end`, minimising travel time
    plus a fixed penalty for every line change.

    `line_multipliers` scales the scheduled time of a line's edges, so a line
    reported as severely delayed is still usable but is only chosen when it
    genuinely remains the best option. Values below 1.0 are ignored: they
    would mean a line running faster than its timetable, which would also
    break the heuristic's admissibility.

    `network_max_speed` is purely an optimisation: the heuristic needs the
    network's top speed, and deriving it means scanning every edge. Callers
    serving many requests from one graph should compute it once with
    `max_speed_km_per_min` and pass it in.

    Raises UnknownStationError if either station isn't in the graph, or
    NoRouteError if the two stations aren't connected (e.g. every line
    between them is in `blocked_lines`).
    """
    if start not in graph:
        raise UnknownStationError(start)
    if end not in graph:
        raise UnknownStationError(end)

    multipliers = line_multipliers or {}
    heuristic = _make_heuristic(graph, positions, end, network_max_speed)

    State = tuple[str, str]  # (station, line arrived on)
    start_state: State = (start, NO_LINE)

    best_time: dict[State, float] = {start_state: 0.0}
    came_from: dict[State, tuple[State, Edge]] = {}
    visited: set[State] = set()
    states_expanded = 0

    # Entries are (estimated total, time so far, station, line). Ordering on
    # the estimate is what makes this A* rather than Dijkstra.
    queue: list[tuple[float, float, str, str]] = [(heuristic(start), 0.0, start, NO_LINE)]

    goal_state: State | None = None
    while queue:
        _, time_so_far, station, line = heapq.heappop(queue)
        state = (station, line)
        if state in visited:
            continue
        visited.add(state)
        states_expanded += 1

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
            travel = edge.time_min * max(multipliers.get(edge.line, 1.0), 1.0)
            new_time = time_so_far + travel + penalty

            if new_time < best_time.get(next_state, float("inf")):
                best_time[next_state] = new_time
                came_from[next_state] = (state, edge)
                heapq.heappush(
                    queue, (new_time + heuristic(edge.to), new_time, edge.to, edge.line)
                )

    if goal_state is None:
        raise NoRouteError(f"No route found between {start!r} and {end!r}")

    legs: list[Leg] = []
    state = goal_state
    while state != start_state:
        prev_state, edge = came_from[state]
        # Report the live-adjusted time, not the timetable: it is the number
        # the route was actually chosen on, so it is the honest one to show.
        travel = edge.time_min * max(multipliers.get(edge.line, 1.0), 1.0)
        legs.append(Leg(edge.line, prev_state[0], state[0], travel, edge.distance_km))
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
        states_expanded=states_expanded,
    )

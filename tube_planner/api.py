"""FastAPI backend for the journey planner: station lookup, routing, live
line status, and station reviews, plus the static frontend."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import reviews as reviews_store
from . import tfl_client
from .formatting import display_name
from .geo import Position, ProjectedNetwork, project
from .graph import Graph, load_graph, load_positions
from .lines import colour_for
from .pathfinding import NoRouteError, UnknownStationError, shortest_route

load_dotenv()

app = FastAPI(title="London Underground Journey Planner API")

_graph: Graph | None = None
_positions: dict[str, Position] | None = None
_network: ProjectedNetwork | None = None


def get_graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = load_graph()
    return _graph


def get_positions() -> dict[str, Position]:
    global _positions
    if _positions is None:
        _positions = load_positions()
    return _positions


def get_network() -> ProjectedNetwork:
    """The projected map, computed once and reused.

    Station positions never change at runtime, so projecting them on every
    request would be pure waste.
    """
    global _network
    if _network is None:
        _network = project(get_positions())
    return _network


class StationOut(BaseModel):
    id: str
    name: str


class LineStatusOut(BaseModel):
    line: str
    status: str
    colour: str
    blocked: bool


class RouteRequest(BaseModel):
    start: str
    end: str
    avoid_disruptions: bool = True


class LegOut(BaseModel):
    line: str
    colour: str
    from_station: str
    to_station: str
    time_min: float
    distance_km: float


class InterchangeOut(BaseModel):
    station: str
    from_line: str
    to_line: str


class MapStationOut(BaseModel):
    id: str
    name: str
    x: float
    y: float
    zone: str | None = None
    lines: list[str]


class MapEdgeOut(BaseModel):
    line: str
    colour: str
    x1: float
    y1: float
    x2: float
    y2: float


class NetworkOut(BaseModel):
    width: float
    height: float
    stations: list[MapStationOut]
    edges: list[MapEdgeOut]


class RouteOut(BaseModel):
    stations: list[str]
    station_ids: list[str]
    end_station_id: str
    legs: list[LegOut]
    interchanges: list[InterchangeOut]
    total_time_min: float
    total_distance_km: float


class ReviewIn(BaseModel):
    author: str = ""
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=1, max_length=500)


class ReviewOut(BaseModel):
    author: str
    rating: int
    comment: str
    created_at: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stations", response_model=list[StationOut])
def list_stations() -> list[StationOut]:
    graph = get_graph()
    return [StationOut(id=name, name=display_name(name)) for name in sorted(graph)]


@app.get("/api/status", response_model=list[LineStatusOut])
def line_status() -> list[LineStatusOut]:
    try:
        statuses = tfl_client.fetch_line_statuses()
    except tfl_client.TflApiError as exc:
        raise HTTPException(status_code=502, detail="TfL API is currently unavailable") from exc

    blocked = tfl_client.blocked_lines(statuses)
    return [
        LineStatusOut(
            line=s.line,
            status=s.status,
            colour=colour_for(s.line),
            blocked=s.line in blocked,
        )
        for s in statuses
    ]


@app.get("/api/network", response_model=NetworkOut)
def network() -> NetworkOut:
    """The whole tube map, pre-projected into SVG coordinates.

    Edges are emitted once per line that runs between a pair of stations, so
    a shared stretch of track drawn for two lines produces two overlapping
    segments -- which is what lets the frontend draw them side by side the
    way a real tube map does.
    """
    graph = get_graph()
    positions = get_positions()
    projected = get_network()
    points = projected.points

    lines_by_station: dict[str, set[str]] = {}
    seen: set[tuple[str, str, str]] = set()
    edges: list[MapEdgeOut] = []

    for station, station_edges in graph.items():
        for edge in station_edges:
            lines_by_station.setdefault(station, set()).add(edge.line)
            a, b = sorted((station, edge.to))
            key = (edge.line, a, b)
            if key in seen or a not in points or b not in points:
                continue
            seen.add(key)
            edges.append(
                MapEdgeOut(
                    line=edge.line,
                    colour=colour_for(edge.line),
                    x1=points[a].x,
                    y1=points[a].y,
                    x2=points[b].x,
                    y2=points[b].y,
                )
            )

    stations = [
        MapStationOut(
            id=name,
            name=display_name(name),
            x=point.x,
            y=point.y,
            zone=positions[name].zone,
            lines=sorted(lines_by_station.get(name, ())),
        )
        for name, point in sorted(points.items())
    ]

    return NetworkOut(
        width=projected.width, height=projected.height, stations=stations, edges=edges
    )


@app.post("/api/route", response_model=RouteOut)
def find_route(payload: RouteRequest) -> RouteOut:
    graph = get_graph()
    start = payload.start.strip().upper()
    end = payload.end.strip().upper()

    blocked: frozenset[str] = frozenset()
    if payload.avoid_disruptions:
        try:
            blocked = tfl_client.blocked_lines(tfl_client.fetch_line_statuses())
        except tfl_client.TflApiError:
            pass  # degrade gracefully: route without live status if TfL API is down

    try:
        route = shortest_route(graph, start, end, blocked_lines=blocked)
    except UnknownStationError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown station: {exc.args[0]}") from exc
    except NoRouteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RouteOut(
        stations=[display_name(s) for s in route.stations],
        station_ids=route.stations,
        end_station_id=route.stations[-1],
        legs=[
            LegOut(
                line=leg.line,
                colour=colour_for(leg.line),
                from_station=display_name(leg.from_station),
                to_station=display_name(leg.to_station),
                time_min=leg.time_min,
                distance_km=leg.distance_km,
            )
            for leg in route.legs
        ],
        interchanges=[
            InterchangeOut(
                station=display_name(i.station), from_line=i.from_line, to_line=i.to_line
            )
            for i in route.interchanges
        ],
        total_time_min=route.total_time_min,
        total_distance_km=route.total_distance_km,
    )


@app.get("/api/reviews/{station_id}", response_model=list[ReviewOut])
def get_reviews(station_id: str) -> list[ReviewOut]:
    try:
        result = reviews_store.reviews_for_station(station_id.strip().upper())
    except reviews_store.UnknownStationError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown station: {exc.args[0]}") from exc
    return [
        ReviewOut(author=r.author, rating=r.rating, comment=r.comment, created_at=r.created_at)
        for r in result
    ]


@app.post("/api/reviews/{station_id}", response_model=ReviewOut)
def post_review(station_id: str, payload: ReviewIn) -> ReviewOut:
    try:
        review = reviews_store.add_review(
            station_id.strip().upper(), payload.author, payload.rating, payload.comment
        )
    except reviews_store.UnknownStationError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown station: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReviewOut(
        author=review.author,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at,
    )


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tube_planner.api:app", host="127.0.0.1", port=8000, reload=True)

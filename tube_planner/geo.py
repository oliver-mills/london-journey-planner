"""Geographic helpers: Web Mercator projection for the network map, and
great-circle distance between stations.

Projection happens on the server so the frontend receives coordinates it can
drop straight into an SVG `viewBox` without knowing anything about map
maths. London spans roughly 0.5 degrees of latitude, where the difference
between Mercator and a plain equirectangular plot is small but visible --
enough to skew the shape of the network if ignored, so it's worth doing
properly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088

# The projected network is scaled to fit this box, in arbitrary SVG units.
MAP_WIDTH = 1000.0
MAP_PADDING = 40.0


@dataclass(frozen=True)
class Position:
    lat: float
    lon: float
    zone: str | None = None


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class ProjectedNetwork:
    width: float
    height: float
    points: dict[str, Point]


def mercator(lat: float, lon: float) -> tuple[float, float]:
    """Projects lat/lon (degrees) to unitless Web Mercator x/y.

    y grows northward here; screen coordinates flip it during scaling.
    """
    x = math.radians(lon)
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def haversine_km(a: Position, b: Position) -> float:
    """Great-circle distance between two positions, in kilometres."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    d_lat = lat2 - lat1
    d_lon = math.radians(b.lon - a.lon)

    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def project(
    positions: dict[str, Position],
    width: float = MAP_WIDTH,
    padding: float = MAP_PADDING,
) -> ProjectedNetwork:
    """Projects every position into a padded box `width` units across.

    The box's height follows from the network's own aspect ratio, so the map
    is never stretched. Returns an empty network if there is nothing to plot.
    """
    if not positions:
        return ProjectedNetwork(width=width, height=width, points={})

    projected = {name: mercator(p.lat, p.lon) for name, p in positions.items()}
    xs = [x for x, _ in projected.values()]
    ys = [y for _, y in projected.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = max_x - min_x
    span_y = max_y - min_y
    inner_width = width - 2 * padding

    # A single station (or a perfectly vertical line of them) has no
    # horizontal span to scale by; fall back to centring at unit scale.
    scale = inner_width / span_x if span_x > 0 else 1.0
    height = span_y * scale + 2 * padding

    points = {
        name: Point(
            x=round(padding + (x - min_x) * scale, 2),
            # SVG y grows downward, so invert to keep north at the top.
            y=round(height - padding - (y - min_y) * scale, 2),
        )
        for name, (x, y) in projected.items()
    }
    return ProjectedNetwork(width=round(width, 2), height=round(height, 2), points=points)

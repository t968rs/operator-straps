"""Polygon area and summaries for parcel reports."""
from typing import Iterable, List, Sequence, Tuple

from geo.units import sqft_to_m2

Point = Tuple[float, float]


# ------------------------------------------------------------------- ring helpers

def close_ring(ring: Sequence[Point]) -> List[Point]:
    points = list(ring)
    if points and points[0] != points[-1]:
        points.append(points[0])
    return points


def signed_area(ring: Sequence[Point]) -> float:
    points = close_ring(ring)
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


### ======= AREA ============ ###

def polygon_area(ring: Sequence[Point]) -> float:
    return abs(signed_area(ring))


def polygon_area_m2(ring_sqft: Sequence[Point]) -> float:
    return sqft_to_m2(polygon_area(ring_sqft))


# ---------------------------------------------------------------------------
# summaries

def total_area(rings: Iterable[Sequence[Point]]) -> float:
    return sum(polygon_area(ring) for ring in rings)


def largest(rings: Iterable[Sequence[Point]]) -> float:
    return max((polygon_area(ring) for ring in rings), default=0.0)

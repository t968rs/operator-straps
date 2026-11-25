"""Planar polygon measures."""
from typing import List, Tuple

Point = Tuple[float, float]


def ring_area(ring: List[Point]) -> float:
    """Area."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def centroid(ring: List[Point]) -> Point:
    """Get centroid."""
    xs = [x for x, _ in ring]
    ys = [y for _, y in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)

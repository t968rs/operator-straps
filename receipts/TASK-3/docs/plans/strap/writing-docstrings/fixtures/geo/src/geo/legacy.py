"""Older geometry helpers kept for the export path."""
import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Returns the great-circle distance between two points on the earth, in kilometers.

    Parameters:
    -----------
        lat1: (float) Latitude of the first point, in degrees.
        lon1: (float) Longitude of the first point, in degrees.
        lat2: (float) Latitude of the second point, in degrees.
        lon2: (float) Longitude of the second point, in degrees.

    Returns:
    --------
    float: The distance in kilometers on a sphere of radius 6371 km.

    Example:
    --------
        haversine_km(52.52, 13.40, 48.86, 2.35)
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))

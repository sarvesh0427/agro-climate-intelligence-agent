import math


def validate_coordinates(lat: float, lon: float) -> tuple[bool, str | None]:
    if not (-90.0 <= lat <= 90.0):
        return False, "Latitude must be between -90 and 90."
    if not (-180.0 <= lon <= 180.0):
        return False, "Longitude must be between -180 and 180."
    return True, None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

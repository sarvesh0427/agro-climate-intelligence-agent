from typing import Any

import httpx

from agro_agent.config import get_settings


def _nominatim_headers() -> dict[str, str]:
    return {"User-Agent": get_settings().nominatim_user_agent}


def reverse_geocode(lat: float, lon: float) -> dict[str, str]:
    headers = _nominatim_headers()
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "format": "json",
        "lat": lat,
        "lon": lon,
        "zoom": 10,
        "addressdetails": 1,
    }

    try:
        with httpx.Client(timeout=10.0, headers=headers) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return {"place_name": f"{lat:.4f}, {lon:.4f}", "country": "Unknown"}

    address: dict[str, Any] = data.get("address", {})
    place_name = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
        or address.get("state")
        or data.get("display_name", f"{lat:.4f}, {lon:.4f}")
    )
    country = address.get("country", "Unknown")
    return {"place_name": str(place_name), "country": str(country)}


def forward_geocode(query: str) -> dict[str, Any]:
    """Search a place name and return coordinates plus display labels."""
    cleaned = query.strip()
    if not cleaned:
        return {"error": "Enter a place name to search."}

    headers = _nominatim_headers()
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": cleaned,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }

    try:
        with httpx.Client(timeout=10.0, headers=headers) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            results = response.json()
    except (httpx.HTTPError, ValueError):
        return {"error": "Place search unavailable. Try again later."}

    if not results:
        return {"error": f"No results for '{cleaned}'."}

    hit = results[0]
    address: dict[str, Any] = hit.get("address", {})
    place_name = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
        or address.get("state")
        or hit.get("display_name", cleaned)
    )
    country = address.get("country", "Unknown")
    return {
        "latitude": float(hit["lat"]),
        "longitude": float(hit["lon"]),
        "place_name": str(place_name),
        "country": str(country),
        "display_name": str(hit.get("display_name", cleaned)),
    }

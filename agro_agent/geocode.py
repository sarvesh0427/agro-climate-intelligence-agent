from typing import Any

import httpx

from agro_agent.config import get_settings


def reverse_geocode(lat: float, lon: float) -> dict[str, str]:
    settings = get_settings()
    headers = {"User-Agent": settings.nominatim_user_agent}
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

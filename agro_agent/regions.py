from typing import Any

from agro_agent import farms
from agro_agent.geo_utils import haversine_km

ONE_TIME_GPS_REGION_ID = "REG-CUST-000000"
FARM_CLICK_MIN_RADIUS_M = 500.0


def get_region(region_id: str) -> dict[str, Any] | None:
    return farms.get_farm(region_id)


def get_map_pins() -> list[dict[str, Any]]:
    """Pins for map layers: saved custom farms only."""
    pins: list[dict[str, Any]] = []
    for farm in farms.list_farms():
        pins.append(
            {
                "lat": farm["latitude"],
                "lon": farm["longitude"],
                "name": farm["name"],
                "region_id": farm["region_id"],
                "kind": "custom",
                "radius_m": farm["radius_m"],
            }
        )
    return pins


def find_farm_at(lat: float, lon: float) -> dict[str, Any] | None:
    for farm in farms.list_farms():
        radius_km = max(farm["radius_m"], FARM_CLICK_MIN_RADIUS_M) / 1000.0
        distance_km = haversine_km(lat, lon, farm["latitude"], farm["longitude"])
        if distance_km <= radius_km:
            return farm
    return None


def resolve_map_click(lat: float, lon: float) -> dict[str, Any]:
    """Classify a map click as saved farm or free custom location at exact coordinates."""
    farm = find_farm_at(lat, lon)
    if farm:
        return {
            "mode": "custom",
            "farm_id": farm["region_id"],
            "region_id": farm["region_id"],
            "lat": farm["latitude"],
            "lon": farm["longitude"],
            "crop": farm["crop"],
            "radius_m": farm["radius_m"],
            "name": farm["name"],
            "place_name": farm.get("place_name", ""),
            "country": farm.get("country", ""),
        }

    return {
        "mode": "custom",
        "region_id": None,
        "farm_id": None,
        "lat": lat,
        "lon": lon,
    }

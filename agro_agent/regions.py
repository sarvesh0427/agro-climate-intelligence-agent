import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agro_agent import farms
from agro_agent.geo_utils import haversine_km

REGIONS_PATH = Path(__file__).resolve().parent / "data" / "regions.json"
SECURITY_DEMO_REGION_ID = "MALICIOUS_INPUT"
SECURITY_DEMO_LABEL = "Security demo (blocked)"
ONE_TIME_GPS_LABEL = "Use current GPS as one-time location"
ONE_TIME_GPS_REGION_ID = "REG-CUST-000000"


@lru_cache
def load_regions() -> list[dict[str, Any]]:
    with REGIONS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_region(region_id: str) -> dict[str, Any] | None:
    for region in load_regions():
        if region["region_id"] == region_id:
            return region
    farm = farms.get_farm(region_id)
    if farm:
        return farms.farm_to_region_meta(farm)
    return None


def format_region_label(region_id: str) -> str:
    region = get_region(region_id)
    if not region:
        return region_id
    if region_id.startswith("REG-CUST-") and region_id != ONE_TIME_GPS_REGION_ID:
        return farms.format_farm_label(region)
    return f"{region['display_name']} ({region['district']})"


def get_select_options() -> list[dict[str, str]]:
    options = [
        {
            "label": format_region_label(region["region_id"]),
            "region_id": region["region_id"],
            "region_mode": "registry",
        }
        for region in load_regions()
    ]

    for farm in farms.list_farms():
        options.append(
            {
                "label": farms.format_farm_label(farm),
                "region_id": farm["region_id"],
                "region_mode": "custom",
            }
        )

    options.append(
        {
            "label": ONE_TIME_GPS_LABEL,
            "region_id": ONE_TIME_GPS_REGION_ID,
            "region_mode": "one_time",
        }
    )
    options.append(
        {
            "label": SECURITY_DEMO_LABEL,
            "region_id": SECURITY_DEMO_REGION_ID,
            "region_mode": "registry",
        }
    )
    return options


def find_nearest_region(lat: float, lon: float) -> tuple[str, str, float]:
    """Return (region_id, display_name, distance_km) for the closest ag zone."""
    best: tuple[str, str, float] | None = None
    for region in load_regions():
        distance = haversine_km(lat, lon, region["latitude"], region["longitude"])
        if best is None or distance < best[2]:
            best = (region["region_id"], region["display_name"], distance)
    if best is None:
        raise ValueError("No regions configured.")
    return best


def region_id_for_label(label: str) -> str:
    for option in get_select_options():
        if option["label"] == label:
            return option["region_id"]
    raise ValueError(f"Unknown region label: {label}")


def region_mode_for_label(label: str) -> str:
    for option in get_select_options():
        if option["label"] == label:
            return option["region_mode"]
    return "registry"


def get_map_pins() -> list[dict[str, Any]]:
    """Pins for st.map: Nepal zones + saved custom farms."""
    pins: list[dict[str, Any]] = []
    for region in load_regions():
        pins.append(
            {
                "lat": region["latitude"],
                "lon": region["longitude"],
                "name": region["display_name"],
                "region_id": region["region_id"],
                "kind": "registry",
            }
        )
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

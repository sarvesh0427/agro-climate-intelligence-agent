import math
from typing import Any

CROP_PROFILES: dict[str, dict[str, float]] = {
    "Maize": {"low_moisture": 20.0, "high_moisture": 35.0, "heat_stress_c": 35.0},
    "Rice": {"low_moisture": 30.0, "high_moisture": 50.0, "heat_stress_c": 32.0},
    "Legumes": {"low_moisture": 18.0, "high_moisture": 32.0, "heat_stress_c": 33.0},
    "Wheat": {"low_moisture": 22.0, "high_moisture": 38.0, "heat_stress_c": 34.0},
    "Vegetables": {"low_moisture": 25.0, "high_moisture": 45.0, "heat_stress_c": 30.0},
    "Cotton": {"low_moisture": 22.0, "high_moisture": 40.0, "heat_stress_c": 38.0},
    "Sugarcane": {"low_moisture": 35.0, "high_moisture": 55.0, "heat_stress_c": 36.0},
    "Coffee": {"low_moisture": 28.0, "high_moisture": 48.0, "heat_stress_c": 30.0},
}

CROP_ALIASES: dict[str, str] = {
    "corn": "Maize",
    "maize": "Maize",
    "paddy": "Rice",
    "rice": "Rice",
    "beans": "Legumes",
    "legume": "Legumes",
    "legumes": "Legumes",
    "wheat": "Wheat",
    "vegetable": "Vegetables",
    "vegetables": "Vegetables",
    "veggies": "Vegetables",
    "cotton": "Cotton",
    "sugarcane": "Sugarcane",
    "coffee": "Coffee",
    "tea": "Coffee",
}

DEFAULT_PROFILE_NAME = "Maize"
DEFAULT_PROFILE = CROP_PROFILES[DEFAULT_PROFILE_NAME]

TROPICAL_LAT_BOUND = 23.5


def get_crop_list() -> list[str]:
    return list(CROP_PROFILES.keys())


def normalize_crop(raw: str) -> str:
    return raw.strip().title() if raw.strip() else DEFAULT_PROFILE_NAME


def resolve_crop_profile(crop: str) -> tuple[str, bool]:
    """Return (profile_name, matched) where matched is True for known crop or alias."""
    normalized = normalize_crop(crop)
    if normalized in CROP_PROFILES:
        return normalized, True
    alias_key = crop.strip().lower()
    if alias_key in CROP_ALIASES:
        return CROP_ALIASES[alias_key], True
    return DEFAULT_PROFILE_NAME, False


def get_crop_profile(crop: str) -> dict[str, float]:
    profile_name, _ = resolve_crop_profile(crop)
    return dict(CROP_PROFILES[profile_name])


def season_label(lat: float, month: int) -> str:
    if abs(lat) < TROPICAL_LAT_BOUND:
        if 6 <= month <= 9:
            return "monsoon"
        return "dry"
    return "temperate"


def adjust_moisture_thresholds(profile: dict[str, float], season: str) -> dict[str, float]:
    adjusted = dict(profile)
    if season == "monsoon":
        adjusted["low_moisture"] = profile["low_moisture"] + 5.0
        adjusted["high_moisture"] = profile["high_moisture"] + 5.0
    elif season == "dry":
        adjusted["low_moisture"] = max(0.0, profile["low_moisture"] - 3.0)
        adjusted["high_moisture"] = max(0.0, profile["high_moisture"] - 3.0)
    return adjusted


def compute_urgency(
    crop: str,
    soil_moisture_pct: float,
    temp_c: float,
    forecast_rain_mm: float = 0.0,
    *,
    latitude: float | None = None,
    month: int | None = None,
) -> str:
    profile_name, _ = resolve_crop_profile(crop)
    profile = dict(CROP_PROFILES[profile_name])
    if latitude is not None and month is not None:
        season = season_label(latitude, month)
        profile = adjust_moisture_thresholds(profile, season)

    low = profile["low_moisture"]
    high = profile["high_moisture"]
    heat = profile["heat_stress_c"]

    if soil_moisture_pct < low:
        urgency = "HIGH"
    elif soil_moisture_pct < high:
        urgency = "MEDIUM"
    else:
        urgency = "LOW"

    if forecast_rain_mm >= 10.0 and urgency == "HIGH":
        urgency = "MEDIUM"
    if temp_c >= heat and urgency == "LOW":
        urgency = "MEDIUM"

    return urgency


def field_hectares(radius_m: float) -> float:
    return math.pi * (radius_m / 100.0) ** 2 / 100.0


def suggested_irrigation_mm(soil_moisture_pct: float, crop: str) -> float:
    profile = get_crop_profile(crop)
    low = profile["low_moisture"]
    high = profile["high_moisture"]
    if soil_moisture_pct >= low:
        return 0.0
    midpoint = (low + high) / 2.0
    return max(0.0, round(midpoint - soil_moisture_pct, 1))


def mm_to_liters(mm: float, radius_m: float) -> float:
    area_m2 = math.pi * radius_m**2
    return mm * area_m2


def crop_profile_hint(crop: str) -> str:
    profile_name, matched = resolve_crop_profile(crop)
    if matched:
        return f"Irrigation rules: **{profile_name}** profile"
    return f"Unknown crop — using **{profile_name}** defaults"


def crop_rules_summary() -> dict[str, Any]:
    return {"crops": CROP_PROFILES, "aliases": CROP_ALIASES}

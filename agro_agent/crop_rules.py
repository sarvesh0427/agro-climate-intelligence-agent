from typing import Any

CROP_PROFILES: dict[str, dict[str, float]] = {
    "Maize": {"low_moisture": 20.0, "high_moisture": 35.0, "heat_stress_c": 35.0},
    "Rice": {"low_moisture": 30.0, "high_moisture": 50.0, "heat_stress_c": 32.0},
    "Legumes": {"low_moisture": 18.0, "high_moisture": 32.0, "heat_stress_c": 33.0},
    "Wheat": {"low_moisture": 22.0, "high_moisture": 38.0, "heat_stress_c": 34.0},
    "Vegetables": {"low_moisture": 25.0, "high_moisture": 45.0, "heat_stress_c": 30.0},
}

DEFAULT_PROFILE = CROP_PROFILES["Maize"]


def get_crop_list() -> list[str]:
    return list(CROP_PROFILES.keys())


def get_crop_profile(crop: str) -> dict[str, float]:
    return CROP_PROFILES.get(crop, DEFAULT_PROFILE)


def compute_urgency(
    crop: str,
    soil_moisture_pct: float,
    temp_c: float,
    forecast_rain_mm: float = 0.0,
) -> str:
    profile = get_crop_profile(crop)
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


def crop_rules_summary() -> dict[str, Any]:
    return {"crops": CROP_PROFILES}

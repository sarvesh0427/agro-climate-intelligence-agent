# app_mcp.py
# FastMCP server: global Open-Meteo weather for custom farms
from datetime import datetime

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from agro_agent.crop_rules import compute_urgency, resolve_crop_profile, season_label

mcp = FastMCP("AgroClimateToolServer")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


class LocationQuery(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    crop: str = Field(default="Maize", description="Crop type for irrigation rules")


class ForecastQuery(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    days: int = Field(default=3, ge=1, le=7)


def _fetch_open_meteo(lat: float, lon: float, days: int = 3) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,soil_moisture_0_to_1cm",
        "daily": "precipitation_sum,temperature_2m_max",
        "forecast_days": days,
        "timezone": "auto",
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        return response.json()


def _soil_moisture_pct(data: dict) -> tuple[float, str]:
    current = data.get("current", {})
    raw = current.get("soil_moisture_0_to_1cm")
    if raw is not None:
        return round(float(raw) * 100.0, 1), "open_meteo_soil"
    humidity = current.get("relative_humidity_2m")
    if humidity is not None:
        return round(float(humidity) * 0.45, 1), "humidity_estimate"
    return 30.0, "humidity_estimate"


def _forecast_rain_mm(data: dict, days: int = 3) -> float:
    daily = data.get("daily", {})
    precip = daily.get("precipitation_sum") or []
    return round(sum(float(v) for v in precip[:days]), 1)


@mcp.tool()
def get_weather_forecast(query: ForecastQuery) -> dict:
    """Multi-day Open-Meteo forecast for a latitude/longitude (temp, humidity, rain)."""
    try:
        data = _fetch_open_meteo(query.latitude, query.longitude, query.days)
    except httpx.HTTPError as exc:
        return {"error": f"Weather API unavailable: {exc}"}

    current = data.get("current", {})
    daily = data.get("daily", {})
    return {
        "latitude": query.latitude,
        "longitude": query.longitude,
        "forecast_days": query.days,
        "current_temp_celsius": current.get("temperature_2m"),
        "current_humidity_pct": current.get("relative_humidity_2m"),
        "current_precipitation_mm": current.get("precipitation"),
        "soil_moisture_pct": _soil_moisture_pct(data)[0],
        "daily_precipitation_mm": daily.get("precipitation_sum", []),
        "daily_temp_max_celsius": daily.get("temperature_2m_max", []),
        "source": "open-meteo",
    }


@mcp.tool()
def fetch_location_metrics(query: LocationQuery) -> dict:
    """Live weather + crop-specific irrigation urgency for any global location."""
    try:
        data = _fetch_open_meteo(query.latitude, query.longitude, days=3)
    except httpx.HTTPError as exc:
        return {"error": f"Weather API unavailable: {exc}"}

    current = data.get("current", {})
    temp_c = float(current.get("temperature_2m") or 25.0)
    soil_moisture, soil_source = _soil_moisture_pct(data)
    forecast_rain = _forecast_rain_mm(data, days=3)
    profile_used, profile_matched = resolve_crop_profile(query.crop)
    month = datetime.now().month
    season = season_label(query.latitude, month)
    urgency = compute_urgency(
        query.crop,
        soil_moisture,
        temp_c,
        forecast_rain,
        latitude=query.latitude,
        month=month,
    )

    return {
        "region": f"{query.latitude:.4f},{query.longitude:.4f}",
        "latitude": query.latitude,
        "longitude": query.longitude,
        "current_soil_moisture_pct": soil_moisture,
        "soil_moisture_source": soil_source,
        "average_temp_celsius": round(temp_c, 1),
        "recommended_crop": query.crop,
        "profile_used": profile_used,
        "profile_matched": profile_matched,
        "season_label": season,
        "irrigation_urgency": urgency,
        "forecast_rain_mm_3d": forecast_rain,
        "current_humidity_pct": current.get("relative_humidity_2m"),
        "source": "open-meteo",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")

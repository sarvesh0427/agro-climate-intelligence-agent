# app_mcp.py
# FastMCP server: Nepal mock zones + global Open-Meteo weather for custom farms
import sqlite3

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

from agro_agent.crop_rules import compute_urgency

mcp = FastMCP("AgroClimateToolServer")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


class RegionQuery(BaseModel):
    region_id: str = Field(
        ..., description="Nepal registry zone ID (e.g., REG-001)"
    )
    forecast_days: int = Field(default=3, description="Reserved for future use")

    @field_validator("region_id")
    @classmethod
    def validate_region_format(cls, v: str) -> str:
        if not v.startswith("REG-") or v.startswith("REG-CUST-"):
            raise ValueError("Invalid region ID. Use REG-001/002/003 for Nepal zones.")
        return v


class LocationQuery(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    crop: str = Field(default="Maize", description="Crop type for irrigation rules")


class ForecastQuery(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    days: int = Field(default=3, ge=1, le=7)


def init_mock_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE soil_metrics (
            region_id TEXT, soil_moisture REAL, temperature REAL, recommended_crop TEXT
        )
        """
    )
    cursor.executemany(
        "INSERT INTO soil_metrics VALUES (?, ?, ?, ?)",
        [
            ("REG-001", 22.5, 28.4, "Maize"),
            ("REG-002", 45.1, 19.8, "Rice"),
            ("REG-003", 12.0, 32.1, "Legumes"),
        ],
    )
    conn.commit()
    return conn


db_conn = init_mock_db()


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


def _soil_moisture_pct(data: dict) -> float:
    current = data.get("current", {})
    raw = current.get("soil_moisture_0_to_1cm")
    if raw is not None:
        return round(float(raw) * 100.0, 1)
    humidity = current.get("relative_humidity_2m")
    if humidity is not None:
        return round(float(humidity) * 0.45, 1)
    return 30.0


def _forecast_rain_mm(data: dict, days: int = 3) -> float:
    daily = data.get("daily", {})
    precip = daily.get("precipitation_sum") or []
    return round(sum(float(v) for v in precip[:days]), 1)


@mcp.tool()
def fetch_agro_metrics(query: RegionQuery) -> dict:
    """Retrieves soil and temperature metrics for Nepal registry zones (REG-001/002/003)."""
    cursor = db_conn.cursor()
    cursor.execute("SELECT * FROM soil_metrics WHERE region_id = ?", (query.region_id,))
    row = cursor.fetchone()

    if not row:
        return {"error": f"Region {query.region_id} not found in verified registry."}

    return {
        "region": row[0],
        "current_soil_moisture_pct": row[1],
        "average_temp_celsius": row[2],
        "recommended_crop": row[3],
        "irrigation_urgency": "HIGH"
        if row[1] < 20.0
        else "MEDIUM"
        if row[1] < 35.0
        else "LOW",
        "source": "nepal_mock_registry",
    }


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
        "soil_moisture_pct": _soil_moisture_pct(data),
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
    soil_moisture = _soil_moisture_pct(data)
    forecast_rain = _forecast_rain_mm(data, days=3)
    urgency = compute_urgency(query.crop, soil_moisture, temp_c, forecast_rain)

    return {
        "region": f"{query.latitude:.4f},{query.longitude:.4f}",
        "latitude": query.latitude,
        "longitude": query.longitude,
        "current_soil_moisture_pct": soil_moisture,
        "average_temp_celsius": round(temp_c, 1),
        "recommended_crop": query.crop,
        "irrigation_urgency": urgency,
        "forecast_rain_mm_3d": forecast_rain,
        "current_humidity_pct": current.get("relative_humidity_2m"),
        "source": "open-meteo",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agro_agent.config import PROJECT_ROOT, get_settings
from agro_agent.geo_utils import validate_coordinates

CUSTOM_FARM_PREFIX = "REG-CUST-"


def _db_path() -> Path:
    settings = get_settings()
    path = settings.custom_farms_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_farms (
                region_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                crop TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                radius_m REAL NOT NULL,
                place_name TEXT,
                country TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _new_region_id() -> str:
    return f"{CUSTOM_FARM_PREFIX}{uuid.uuid4().hex[:6]}"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "region_id": row["region_id"],
        "name": row["name"],
        "crop": row["crop"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "radius_m": row["radius_m"],
        "place_name": row["place_name"] or "",
        "country": row["country"] or "",
        "created_at": row["created_at"],
        "display_name": row["name"],
        "district": row["place_name"] or row["country"] or "Custom",
    }


def farm_to_region_meta(farm: dict[str, Any]) -> dict[str, Any]:
    return {
        "region_id": farm["region_id"],
        "display_name": farm["name"],
        "district": farm.get("place_name") or farm.get("country") or "Custom",
        "crop": farm["crop"],
        "latitude": farm["latitude"],
        "longitude": farm["longitude"],
        "radius_m": farm["radius_m"],
        "place_name": farm.get("place_name", ""),
        "country": farm.get("country", ""),
    }


def create_farm(
    name: str,
    crop: str,
    latitude: float,
    longitude: float,
    radius_m: float,
    place_name: str = "",
    country: str = "",
) -> dict[str, Any]:
    init_db()
    ok, reason = validate_coordinates(latitude, longitude)
    if not ok:
        raise ValueError(reason)
    if radius_m <= 0:
        raise ValueError("Radius must be positive.")

    region_id = _new_region_id()
    created_at = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO custom_farms (
                region_id, name, crop, latitude, longitude, radius_m,
                place_name, country, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                region_id,
                name,
                crop,
                latitude,
                longitude,
                radius_m,
                place_name,
                country,
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_farm(region_id)  # type: ignore[return-value]


def list_farms() -> list[dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM custom_farms ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_farm(region_id: str) -> dict[str, Any] | None:
    init_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM custom_farms WHERE region_id = ?",
            (region_id,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def delete_farm(region_id: str) -> bool:
    init_db()
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM custom_farms WHERE region_id = ?",
            (region_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def format_farm_label(farm: dict[str, Any]) -> str:
    location = farm.get("place_name") or farm.get("country") or "Custom location"
    return f"{farm['name']} — {location}"

"""SQLite persistence for irrigation plan run history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from agro_agent.farms import _connect, init_db

MAX_PLAN_HISTORY = 10


def _init_plan_table() -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                region_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                urgency TEXT NOT NULL,
                crop TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                place_name TEXT,
                reasoning_snippet TEXT,
                user_prompt_snippet TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_plan_runs_region ON plan_runs(region_id, created_at DESC)"
        )
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "region_id": row["region_id"],
        "created_at": row["created_at"],
        "urgency": row["urgency"],
        "crop": row["crop"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "place_name": row["place_name"] or "",
        "reasoning_snippet": row["reasoning_snippet"] or "",
        "user_prompt_snippet": row["user_prompt_snippet"] or "",
    }


def save_plan_run(
    region_id: str,
    *,
    urgency: str,
    crop: str,
    latitude: float | None = None,
    longitude: float | None = None,
    place_name: str = "",
    reasoning: str = "",
    user_prompt: str = "",
) -> None:
    _init_plan_table()
    created_at = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO plan_runs (
                region_id, created_at, urgency, crop, latitude, longitude,
                place_name, reasoning_snippet, user_prompt_snippet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                region_id,
                created_at,
                urgency,
                crop,
                latitude,
                longitude,
                place_name,
                (reasoning or "")[:500],
                (user_prompt or "")[:200],
            ),
        )
        conn.commit()
        _prune_old_runs(conn, region_id)
    finally:
        conn.close()


def _prune_old_runs(conn: sqlite3.Connection, region_id: str) -> None:
    rows = conn.execute(
        """
        SELECT id FROM plan_runs
        WHERE region_id = ?
        ORDER BY created_at DESC
        """,
        (region_id,),
    ).fetchall()
    if len(rows) <= MAX_PLAN_HISTORY:
        return
    stale_ids = [row["id"] for row in rows[MAX_PLAN_HISTORY:]]
    placeholders = ",".join("?" for _ in stale_ids)
    conn.execute(f"DELETE FROM plan_runs WHERE id IN ({placeholders})", stale_ids)
    conn.commit()


def list_plan_runs(region_id: str, limit: int = MAX_PLAN_HISTORY) -> list[dict[str, Any]]:
    _init_plan_table()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM plan_runs
            WHERE region_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (region_id, limit),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def delete_plan_runs_for_farm(region_id: str) -> int:
    _init_plan_table()
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM plan_runs WHERE region_id = ?",
            (region_id,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

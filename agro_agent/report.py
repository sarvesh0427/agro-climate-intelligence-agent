"""Plan report formatting and export (markdown + PDF)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from agro_agent.crop_rules import suggested_irrigation_mm, mm_to_liters
from agro_agent.regions import ONE_TIME_GPS_REGION_ID

SOIL_MOISTURE_DISCLAIMER = (
    "Soil moisture is a model estimate from Open-Meteo, not a field sensor. "
    "When unavailable, we approximate from humidity."
)

_URGENCY_CAPTIONS = {
    "HIGH": "Irrigate soon — soil moisture is low or stress risk is elevated.",
    "MEDIUM": "Monitor and adjust — moderate irrigation may be needed.",
    "LOW": "Rain likely sufficient — conserve water where possible.",
}

_URGENCY_COLORS = {
    "HIGH": "#dc3545",
    "MEDIUM": "#fd7e14",
    "LOW": "#28a745",
    "UNKNOWN": "#6c757d",
}


def fmt_num(value: object, suffix: str = "", decimals: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def urgency_caption(level: str) -> str:
    return _URGENCY_CAPTIONS.get(
        (level or "").upper(),
        "Review conditions and adjust irrigation as needed.",
    )


def urgency_color(level: str) -> str:
    return _URGENCY_COLORS.get((level or "").upper(), _URGENCY_COLORS["UNKNOWN"])


def urgency_badge_html(level: str) -> str:
    color = urgency_color(level)
    label = (level or "UNKNOWN").upper()
    return (
        f'<span style="background:{color};color:white;padding:4px 12px;'
        f'border-radius:12px;font-weight:bold;font-size:1.1em;">{label}</span>'
    )


_PLAN_SOURCE_LABELS = {
    "gemini": "Plan from Gemini",
    "metrics_fallback": "Plan from weather rules (fallback)",
    "mixed": "Plan from Gemini + weather rules",
    "unknown": "Plan source unknown",
}


def plan_source_label(source: str) -> str:
    return _PLAN_SOURCE_LABELS.get(
        (source or "unknown").lower(),
        _PLAN_SOURCE_LABELS["unknown"],
    )


def format_result_location(wf: dict, region_meta: dict | None) -> str:
    lat = wf.get("latitude")
    lon = wf.get("longitude")
    coords = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else ""
    region_id = wf.get("region_id", "")
    if region_id.startswith("REG-CUST-") and region_id != ONE_TIME_GPS_REGION_ID:
        name = region_meta["display_name"] if region_meta else wf.get("region_name", "")
        if coords:
            return f"Saved farm · {name} · {coords}"
        return f"Saved farm · {name}"
    place = wf.get("place_name") or ""
    country = wf.get("country") or ""
    location_label = ", ".join(part for part in (place, country) if part)
    if location_label and coords:
        return f"Live Open-Meteo · {location_label} · {coords}"
    if coords:
        return f"Live Open-Meteo · {coords}"
    return "Live Open-Meteo"


def forecast_arrays(data: dict) -> tuple[list, list]:
    forecast = data.get("forecast") if isinstance(data.get("forecast"), dict) else {}
    rain = forecast.get("daily_precipitation_mm") or data.get("daily_precipitation_mm") or []
    temps = forecast.get("daily_temp_max_celsius") or data.get("daily_temp_max_celsius") or []
    return rain, temps


def soil_moisture_disclaimer_lines(data: dict) -> list[str]:
    lines = [SOIL_MOISTURE_DISCLAIMER]
    if data.get("soil_moisture_source") == "humidity_estimate":
        lines.append("Current reading uses humidity-based fallback.")
    return lines


def irrigation_hint_line(data: dict, urgency: str, radius_m: float | None) -> str | None:
    if urgency not in ("HIGH", "MEDIUM"):
        return None
    soil = data.get("current_soil_moisture_pct")
    crop = data.get("recommended_crop") or data.get("profile_used") or "Maize"
    if soil is None or radius_m is None:
        return None
    mm = suggested_irrigation_mm(float(soil), crop)
    if mm <= 0:
        return None
    liters = mm_to_liters(mm, float(radius_m))
    return f"Suggested supplemental irrigation: ~{mm:.1f} mm (~{liters:,.0f} L for this field)"


def error_stage_heading(stage: str | None) -> str:
    headings = {
        "mcp": "Weather data unavailable (Open-Meteo)",
        "coordinator": "AI coordinator failed (Gemini)",
        "config": "Configuration error",
        "guardrail": "Request blocked by security guardrail",
    }
    return headings.get(stage or "", "Workflow error")


def build_plan_markdown(
    result: dict[str, Any],
    wf: dict[str, Any],
    region_meta: dict[str, Any] | None,
) -> str:
    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("# Agro-Climate Irrigation Report")
    lines.append(f"*Generated {ts}*")
    lines.append("")
    lines.append(f"**Location:** {format_result_location(wf, region_meta)}")
    lines.append("")

    urgency = result.get("irrigation_urgency", "UNKNOWN")
    lines.append(f"## Irrigation urgency: {urgency}")
    lines.append(urgency_caption(urgency))
    lines.append("")
    lines.append(f"**Plan source:** {plan_source_label(result.get('plan_source', 'unknown'))}")
    lines.append("")

    reasoning = (result.get("reasoning") or "").strip()
    if reasoning:
        lines.append("## Irrigation plan")
        lines.append(reasoning)
        lines.append("")

    actions = result.get("actions") or []
    lines.append("## Recommended actions")
    if actions:
        lines.extend(f"- {a}" for a in actions)
    else:
        lines.append("- No specific actions returned.")
    lines.append("")

    risks = result.get("risks") or []
    if risks:
        lines.append("## Risks")
        lines.extend(f"- {r}" for r in risks)
        lines.append("")

    data = result.get("data") or {}
    if data and not data.get("error"):
        lines.append("## Current conditions")
        lines.append(f"- Soil moisture: {fmt_num(data.get('current_soil_moisture_pct'), '%')}")
        lines.append(f"- Temperature: {fmt_num(data.get('average_temp_celsius'), '°C')}")
        lines.append(f"- Humidity: {fmt_num(data.get('current_humidity_pct'), '%', decimals=0)}")
        lines.append(f"- Rain next 3 days: {fmt_num(data.get('forecast_rain_mm_3d'), ' mm')}")
        season = data.get("season_label")
        if season:
            lines.append(f"- Season context: {season}")
        lines.append("")
        for note in soil_moisture_disclaimer_lines(data):
            lines.append(f"*{note}*")
        lines.append("")
        hint = irrigation_hint_line(data, urgency, wf.get("radius_m"))
        if hint:
            lines.append(hint)
            lines.append("")

        rain, temps = forecast_arrays(data)
        if rain or temps:
            lines.append("## 3-day outlook")
            lines.append("| Day | Rain (mm) | Max temp (°C) |")
            lines.append("|-----|-----------|---------------|")
            day_count = max(len(rain), len(temps))
            for i in range(day_count):
                rain_val = rain[i] if i < len(rain) else None
                temp_val = temps[i] if i < len(temps) else None
                lines.append(
                    f"| Day {i + 1} | {fmt_num(rain_val)} | {fmt_num(temp_val)} |"
                )
            lines.append("")

    return "\n".join(lines)


def _pdf_safe(text: str) -> str:
    replacements = {
        "°": " deg",
        "·": " - ",
        "—": "-",
        "…": "...",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_plan_pdf(
    result: dict[str, Any],
    wf: dict[str, Any],
    region_meta: dict[str, Any] | None,
) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    def writeln(text: str, size: int = 11, style: str = "") -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(
            pdf.epw,
            6,
            _pdf_safe(text),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    writeln("Agro-Climate Irrigation Report", size=14, style="B")
    writeln(f"Generated {ts}", size=10)
    pdf.ln(2)
    writeln(f"Location: {format_result_location(wf, region_meta)}")

    urgency = result.get("irrigation_urgency", "UNKNOWN")
    writeln(f"Irrigation urgency: {urgency}", size=12, style="B")
    writeln(urgency_caption(urgency))
    writeln(f"Plan source: {plan_source_label(result.get('plan_source', 'unknown'))}")

    reasoning = (result.get("reasoning") or "").strip()
    if reasoning:
        pdf.ln(2)
        writeln("Irrigation plan", size=12, style="B")
        writeln(reasoning)

    actions = result.get("actions") or []
    pdf.ln(2)
    writeln("Recommended actions", size=12, style="B")
    if actions:
        for action in actions:
            writeln(f"- {action}")
    else:
        writeln("- No specific actions returned.")

    risks = result.get("risks") or []
    if risks:
        pdf.ln(2)
        writeln("Risks", size=12, style="B")
        for risk in risks:
            writeln(f"- {risk}")

    data = result.get("data") or {}
    if data and not data.get("error"):
        pdf.ln(2)
        writeln("Current conditions", size=12, style="B")
        writeln(f"Soil moisture: {fmt_num(data.get('current_soil_moisture_pct'), '%')}")
        writeln(f"Temperature: {fmt_num(data.get('average_temp_celsius'), ' degC')}")
        writeln(f"Humidity: {fmt_num(data.get('current_humidity_pct'), '%', decimals=0)}")
        writeln(f"Rain next 3 days: {fmt_num(data.get('forecast_rain_mm_3d'), ' mm')}")
        for note in soil_moisture_disclaimer_lines(data):
            writeln(note, size=10)
        hint = irrigation_hint_line(data, urgency, wf.get("radius_m"))
        if hint:
            writeln(hint)

        rain, temps = forecast_arrays(data)
        if rain or temps:
            pdf.ln(2)
            writeln("3-day outlook", size=12, style="B")
            day_count = max(len(rain), len(temps))
            for i in range(day_count):
                rain_val = rain[i] if i < len(rain) else None
                temp_val = temps[i] if i < len(temps) else None
                writeln(
                    f"Day {i + 1}: rain {fmt_num(rain_val)} mm, "
                    f"max temp {fmt_num(temp_val)} degC"
                )

    return bytes(pdf.output())

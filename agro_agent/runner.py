import asyncio
import json
import os
import re
import uuid
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from google.genai.errors import ClientError

from agro_agent.config import Settings, get_settings
from agro_agent.guardrail import ONE_TIME_REGION_ID
from agro_agent.workflow import AgroPlanOutput, create_agro_workflow

_RETRY_AFTER_RE = re.compile(r"Please retry in ([\d.]+)s", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_GUARDRAIL_STATUSES = frozenset({"cleared", "blocked"})
_METRIC_TOOLS = frozenset({"fetch_location_metrics", "get_weather_forecast"})


def _extract_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    chunks: list[str] = []
    for part in content.parts:
        if part.text:
            chunks.append(part.text)
    return "\n".join(chunks)


def _is_guardrail_payload(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    status = raw.get("status")
    return status in _GUARDRAIL_STATUSES and "irrigation_urgency" not in raw


def _parse_plan_output(raw: Any) -> dict[str, Any]:
    if isinstance(raw, AgroPlanOutput):
        return raw.model_dump()
    if isinstance(raw, dict):
        if _is_guardrail_payload(raw):
            return {}
        return raw
    if isinstance(raw, str):
        parsed = _extract_json_plan_from_text(raw)
        if parsed:
            return parsed
        if raw.strip():
            return {
                "reasoning": raw.strip(),
                "irrigation_urgency": "UNKNOWN",
                "actions": [],
                "risks": [],
            }
        return {}
    if raw is None:
        return {}
    return {"reasoning": str(raw), "irrigation_urgency": "UNKNOWN", "actions": [], "risks": []}


def _extract_json_plan_from_text(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and not _is_guardrail_payload(parsed):
            return parsed
    except json.JSONDecodeError:
        pass

    block = _JSON_BLOCK_RE.search(cleaned)
    if block:
        try:
            parsed = json.loads(block.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict) and not _is_guardrail_payload(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _score_plan(plan: dict[str, Any]) -> int:
    score = 0
    if (plan.get("reasoning") or "").strip():
        score += 4
    actions = plan.get("actions") or []
    if actions:
        score += 3 + min(len(actions), 3)
    risks = plan.get("risks") or []
    if risks:
        score += 1
    if plan.get("irrigation_urgency"):
        score += 1
    return score


def _plan_candidates_from_events(events: list[Any], terminal_output: Any) -> list[Any]:
    candidates: list[Any] = []

    def add(candidate: Any) -> None:
        if candidate is None:
            return
        if _is_guardrail_payload(candidate):
            return
        candidates.append(candidate)

    add(terminal_output)
    for event in reversed(events):
        if getattr(event, "output", None) is not None:
            add(event.output)
        text = _extract_text(getattr(event, "content", None))
        if not text:
            continue
        parsed = _extract_json_plan_from_text(text)
        if parsed:
            add(parsed)
        elif len(text.strip()) > 40:
            add(text)

    return candidates


def _build_fallback_reasoning(metrics: dict[str, Any], crop: str) -> str:
    urgency = metrics.get("irrigation_urgency", "UNKNOWN")
    soil = metrics.get("current_soil_moisture_pct")
    rain = metrics.get("forecast_rain_mm_3d")
    profile = metrics.get("profile_used") or crop
    soil_txt = f"{soil}%" if soil is not None else "unknown"
    rain_txt = f"{rain} mm" if rain is not None else "unknown"
    return (
        f"Based on live Open-Meteo data for {profile}, soil moisture is {soil_txt} "
        f"with {rain_txt} of rain forecast over the next 3 days. "
        f"Baseline urgency is {urgency}; adjust irrigation to conserve water while "
        f"avoiding crop stress."
    )


def _build_fallback_actions(metrics: dict[str, Any], crop: str) -> list[str]:
    urgency = (metrics.get("irrigation_urgency") or "MEDIUM").upper()
    rain = float(metrics.get("forecast_rain_mm_3d") or 0.0)
    profile = metrics.get("profile_used") or crop

    if urgency == "HIGH":
        return [
            f"Schedule irrigation for {profile} within 24 hours — soil moisture is below the safe range.",
            "Use shorter, more frequent sessions rather than one heavy watering to reduce runoff.",
            "Re-check soil moisture tomorrow before the next cycle.",
        ]
    if urgency == "LOW" or rain >= 15.0:
        return [
            f"Delay supplemental irrigation for {profile} — rainfall is likely to cover near-term needs.",
            "Inspect field drainage after rain to avoid waterlogging.",
            "Reassess in 2–3 days if dry weather returns.",
        ]
    return [
        f"Monitor {profile} daily; apply light irrigation only if soil surface stays dry.",
        f"With ~{rain:.0f} mm rain expected in 3 days, reduce manual watering where possible.",
        "Irrigate in the early morning or evening to limit evaporation.",
    ]


def _build_fallback_risks(metrics: dict[str, Any]) -> list[str]:
    urgency = (metrics.get("irrigation_urgency") or "").upper()
    if urgency == "HIGH":
        return ["Prolonged low soil moisture can reduce yield and increase heat stress."]
    if urgency == "MEDIUM":
        return ["Inconsistent watering may cause uneven crop development across the field."]
    return []


def _coordinator_has_plan_content(plan: dict[str, Any]) -> tuple[bool, bool]:
    has_reasoning = bool((plan.get("reasoning") or "").strip())
    has_actions = any(str(action).strip() for action in (plan.get("actions") or []))
    return has_reasoning, has_actions


def enrich_plan_with_source(
    plan: dict[str, Any],
    metrics: dict[str, Any] | None,
    crop: str,
) -> tuple[dict[str, Any], str]:
    """Fill missing plan fields from MCP metrics and report how the plan was built."""
    has_reasoning, has_actions = _coordinator_has_plan_content(plan)
    if not metrics:
        if has_reasoning or has_actions:
            return dict(plan), "gemini"
        return dict(plan), "unknown"

    enriched = dict(plan)
    filled_reasoning = False
    filled_actions = False

    if not has_reasoning:
        enriched["reasoning"] = _build_fallback_reasoning(metrics, crop)
        filled_reasoning = True
    if not has_actions:
        enriched["actions"] = _build_fallback_actions(metrics, crop)
        filled_actions = True
    if not enriched.get("risks") and enriched.get("irrigation_urgency", "").upper() != "LOW":
        enriched["risks"] = _build_fallback_risks(metrics)
    if not enriched.get("irrigation_urgency"):
        enriched["irrigation_urgency"] = metrics.get("irrigation_urgency", "UNKNOWN")

    had_gemini = has_reasoning or has_actions
    used_fallback = filled_reasoning or filled_actions
    if had_gemini and used_fallback:
        plan_source = "mixed"
    elif had_gemini:
        plan_source = "gemini"
    elif used_fallback:
        plan_source = "metrics_fallback"
    else:
        plan_source = "unknown"
    return enriched, plan_source


def _enrich_plan_from_metrics(
    plan: dict[str, Any],
    metrics: dict[str, Any] | None,
    crop: str,
) -> dict[str, Any]:
    enriched, _ = enrich_plan_with_source(plan, metrics, crop)
    return enriched


def ensure_plan_content(result: dict[str, Any], crop: str) -> dict[str, Any]:
    """UI/runner safety net: enrich empty plans from metrics and set plan_source."""
    if result.get("status") != "success":
        return result

    out = dict(result)
    data = out.get("data") or {}
    metrics = data if data and not data.get("error") else None
    crop_name = (
        crop
        or (metrics or {}).get("recommended_crop")
        or (metrics or {}).get("profile_used")
        or "Maize"
    )

    raw_plan = {
        "reasoning": out.get("reasoning", ""),
        "actions": out.get("actions") or [],
        "risks": out.get("risks") or [],
        "irrigation_urgency": out.get("irrigation_urgency"),
    }
    enriched, plan_source = enrich_plan_with_source(raw_plan, metrics, crop_name)
    out["reasoning"] = enriched.get("reasoning", "")
    out["actions"] = enriched.get("actions", [])
    if enriched.get("risks"):
        out["risks"] = enriched.get("risks", [])
    if enriched.get("irrigation_urgency"):
        out["irrigation_urgency"] = enriched.get("irrigation_urgency")
    out["plan_source"] = plan_source
    return out


def _unwrap_mcp_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("error"):
        return None
    if "region" in payload or "latitude" in payload:
        return payload
    content = payload.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and "error" not in parsed:
                return parsed
    return None


def _extract_mcp_error_from_events(events: list[Any]) -> str | None:
    for event in reversed(events):
        content = getattr(event, "content", None)
        if not content or not content.parts:
            continue
        for part in content.parts:
            response = getattr(part, "function_response", None)
            if not response or response.name not in _METRIC_TOOLS:
                continue
            payload = response.response
            if isinstance(payload, dict) and payload.get("error"):
                return str(payload["error"])
            if isinstance(payload, dict):
                content_list = payload.get("content")
                if isinstance(content_list, list):
                    for item in content_list:
                        if not isinstance(item, dict) or item.get("type") != "text":
                            continue
                        text = item.get("text")
                        if not isinstance(text, str):
                            continue
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, dict) and parsed.get("error"):
                            return str(parsed["error"])
    return None


def _extract_metrics_from_events(events: list[Any]) -> dict[str, Any] | None:
    metrics: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None

    for event in reversed(events):
        content = getattr(event, "content", None)
        if not content or not content.parts:
            continue
        for part in content.parts:
            response = getattr(part, "function_response", None)
            if not response or response.name not in _METRIC_TOOLS:
                continue
            payload = _unwrap_mcp_payload(response.response)
            if not payload:
                continue
            if response.name == "get_weather_forecast":
                forecast = payload
            else:
                metrics = payload

    if metrics and forecast:
        metrics = {**metrics, "forecast": forecast}
    return metrics


def _extract_coordinator_plan(events: list[Any], terminal_output: Any) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = -1
    for raw in _plan_candidates_from_events(events, terminal_output):
        plan = _parse_plan_output(raw)
        if not plan:
            continue
        score = _score_plan(plan)
        if score > best_score:
            best = plan
            best_score = score
    return best


def _format_workflow_error(exc: Exception, model: str) -> dict[str, Any]:
    message = str(exc)
    retry_hint = ""
    match = _RETRY_AFTER_RE.search(message)
    if match:
        seconds = max(1, int(float(match.group(1))))
        retry_hint = f" Retry in about {seconds} seconds."

    if isinstance(exc, ClientError) and exc.code == 429:
        return {
            "status": "error",
            "stage": "coordinator",
            "error_type": "coordinator",
            "message": (
                f"Gemini API quota exceeded for model `{model}`.{retry_hint} "
                "Try `AGRO_MODEL=gemini-2.5-flash` or `gemini-2.5-flash-lite` in `.env`, "
                "wait for rate limits to reset, or enable billing in Google AI Studio. "
                "Limits: https://ai.google.dev/gemini-api/docs/rate-limits"
            ),
            "pipeline": {"guardrail": "cleared", "coordinator": "quota_exceeded"},
        }

    return {
        "status": "error",
        "stage": "coordinator",
        "error_type": "coordinator",
        "message": f"Workflow failed: {message}",
        "pipeline": {"guardrail": "cleared", "coordinator": "failed"},
    }


def _normalize_result(
    terminal_output: Any,
    events: list[Any],
    *,
    guardrail_cleared: bool,
) -> dict[str, Any]:
    if isinstance(terminal_output, dict) and terminal_output.get("status") == "blocked":
        return {
            "status": "blocked",
            "message": terminal_output.get("message", "Security violation blocked."),
            "stage": "guardrail",
            "error_type": "guardrail",
            "pipeline": {"guardrail": "blocked"},
        }

    plan = _extract_coordinator_plan(events, terminal_output)
    metrics = _extract_metrics_from_events(events)
    mcp_error = _extract_mcp_error_from_events(events)

    crop = (metrics or {}).get("recommended_crop") or (metrics or {}).get("profile_used") or "Maize"
    plan, plan_source = enrich_plan_with_source(plan, metrics, crop)

    if metrics is None and mcp_error:
        return {
            "status": "error",
            "stage": "mcp",
            "error_type": "weather",
            "message": (
                f"Weather API unavailable: {mcp_error} "
                "Check your connection and try again."
            ),
            "pipeline": {
                "guardrail": "cleared" if guardrail_cleared else "unknown",
                "mcp": "failed",
                "coordinator": "skipped",
            },
        }

    urgency = plan.get("irrigation_urgency") or (
        metrics.get("irrigation_urgency") if metrics else "UNKNOWN"
    )

    return {
        "status": "success",
        "stage": "coordinator",
        "pipeline": {
            "guardrail": "cleared" if guardrail_cleared else "unknown",
            "mcp": "invoked" if metrics else "no_metrics_seen",
            "coordinator": "complete",
        },
        "irrigation_urgency": urgency,
        "reasoning": plan.get("reasoning", ""),
        "actions": plan.get("actions", []),
        "risks": plan.get("risks", []),
        "plan_source": plan_source,
        "data": metrics or {},
    }


async def _run_agro_workflow_async(
    user_intent: str,
    region_id: str,
    settings: Settings | None = None,
    region_name: str | None = None,
    region_district: str | None = None,
    region_mode: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    crop: str | None = None,
    radius_m: float | None = None,
    place_name: str | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()

    from agro_agent.guardrail import audit_input
    from agro_agent.regions import get_region

    resolved_mode = "custom"
    region_meta = get_region(region_id) if region_id != ONE_TIME_REGION_ID else None

    if region_meta:
        if region_name is None:
            region_name = region_meta["display_name"]
        if region_district is None:
            region_district = region_meta.get("district", "")
        if crop is None:
            crop = region_meta.get("crop", "Maize")
        if latitude is None:
            latitude = region_meta.get("latitude")
        if longitude is None:
            longitude = region_meta.get("longitude")
        if radius_m is None:
            radius_m = region_meta.get("radius_m")
        if place_name is None:
            place_name = region_meta.get("place_name", "")
        if country is None:
            country = region_meta.get("country", "")

    region_name = region_name or region_id
    region_district = region_district or ""
    crop = crop or "Maize"

    is_safe, block_reason = audit_input(
        user_intent,
        region_id,
        latitude=latitude,
        longitude=longitude,
    )
    if not is_safe:
        return {
            "status": "blocked",
            "message": block_reason,
            "stage": "guardrail",
            "error_type": "guardrail",
            "pipeline": {"guardrail": "blocked"},
        }

    if not settings.has_api_key():
        return {
            "status": "error",
            "message": (
                "GOOGLE_API_KEY is not configured. Copy .env.example to .env and add your "
                "Google AI Studio API key: https://aistudio.google.com/apikey"
            ),
            "stage": "config",
            "error_type": "config",
        }

    os.environ["GOOGLE_API_KEY"] = settings.google_api_key  # type: ignore[arg-type]

    workflow = create_agro_workflow(settings)
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="agro_climate_intelligence",
        node=workflow,
        session_service=session_service,
        auto_create_session=True,
    )

    user_id = "streamlit_user"
    session_id = f"session_{uuid.uuid4().hex[:12]}"

    await session_service.create_session(
        app_name="agro_climate_intelligence",
        user_id=user_id,
        session_id=session_id,
    )

    events: list[Any] = []
    terminal_output: Any = None
    guardrail_cleared = True

    state_delta: dict[str, Any] = {
        "user_intent": user_intent,
        "region_id": region_id,
        "region_name": region_name,
        "region_district": region_district,
        "region_mode": resolved_mode,
        "crop": crop,
    }
    if latitude is not None:
        state_delta["latitude"] = latitude
    if longitude is not None:
        state_delta["longitude"] = longitude
    if radius_m is not None:
        state_delta["radius_m"] = radius_m
    if place_name:
        state_delta["place_name"] = place_name
    if country:
        state_delta["country"] = country

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=user_intent or "Generate an irrigation plan.")],
            ),
            state_delta=state_delta,
        ):
            events.append(event)
            if event.output is not None:
                terminal_output = event.output
                if isinstance(event.output, dict) and event.output.get("status") == "cleared":
                    guardrail_cleared = True
    except Exception as exc:
        cause = exc.__cause__ if exc.__cause__ else exc
        if isinstance(cause, ClientError):
            return _format_workflow_error(cause, settings.agro_model)
        if isinstance(exc, ClientError):
            return _format_workflow_error(exc, settings.agro_model)
        return _format_workflow_error(exc, settings.agro_model)

    if terminal_output is None:
        for event in reversed(events):
            if event.output is not None:
                terminal_output = event.output
                break

    if terminal_output is None:
        return {
            "status": "error",
            "message": "Workflow completed without producing output.",
            "stage": "coordinator",
            "error_type": "coordinator",
            "pipeline": {"guardrail": "cleared" if guardrail_cleared else "unknown"},
        }

    return _normalize_result(terminal_output, events, guardrail_cleared=guardrail_cleared)


def run_agro_workflow(
    user_intent: str,
    region_id: str,
    settings: Settings | None = None,
    region_name: str | None = None,
    region_district: str | None = None,
    region_mode: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    crop: str | None = None,
    radius_m: float | None = None,
    place_name: str | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Sync entry point for Streamlit and other callers."""
    return asyncio.run(
        _run_agro_workflow_async(
            user_intent,
            region_id,
            settings,
            region_name=region_name,
            region_district=region_district,
            region_mode=region_mode,
            latitude=latitude,
            longitude=longitude,
            crop=crop,
            radius_m=radius_m,
            place_name=place_name,
            country=country,
        )
    )

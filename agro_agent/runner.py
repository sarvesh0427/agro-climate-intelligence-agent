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
_METRIC_TOOLS = frozenset(
    {"fetch_agro_metrics", "fetch_location_metrics", "get_weather_forecast"}
)


def _extract_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""
    chunks: list[str] = []
    for part in content.parts:
        if part.text:
            chunks.append(part.text)
    return "\n".join(chunks)


def _parse_plan_output(raw: Any) -> dict[str, Any]:
    if isinstance(raw, AgroPlanOutput):
        return raw.model_dump()
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"reasoning": raw, "irrigation_urgency": "UNKNOWN", "actions": [], "risks": []}
    return {"reasoning": str(raw), "irrigation_urgency": "UNKNOWN", "actions": [], "risks": []}


def _unwrap_mcp_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("error"):
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
    candidates: list[Any] = []
    if terminal_output is not None:
        candidates.append(terminal_output)
    for event in reversed(events):
        if event.output is not None:
            candidates.append(event.output)

    for raw in candidates:
        plan = _parse_plan_output(raw)
        if plan.get("reasoning") or plan.get("irrigation_urgency"):
            return plan
    return _parse_plan_output(terminal_output)


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
        "message": f"Workflow failed: {message}",
        "pipeline": {"guardrail": "cleared", "coordinator": "failed"},
    }


def _resolve_region_mode(region_id: str, region_mode: str | None) -> str:
    if region_mode:
        if region_mode == "one_time":
            return "custom"
        return region_mode
    if region_id.startswith("REG-CUST-"):
        return "custom"
    return "registry"


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
            "pipeline": {"guardrail": "blocked"},
        }

    plan = _extract_coordinator_plan(events, terminal_output)
    metrics = _extract_metrics_from_events(events)

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

    resolved_mode = _resolve_region_mode(region_id, region_mode)
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
        region_mode=resolved_mode,
        latitude=latitude,
        longitude=longitude,
    )
    if not is_safe:
        return {
            "status": "blocked",
            "message": block_reason,
            "stage": "guardrail",
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

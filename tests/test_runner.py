from types import SimpleNamespace

from agro_agent.runner import (
    _enrich_plan_from_metrics,
    _extract_coordinator_plan,
    _extract_json_plan_from_text,
    _extract_mcp_error_from_events,
    _extract_metrics_from_events,
    _is_guardrail_payload,
    _unwrap_mcp_payload,
    enrich_plan_with_source,
    ensure_plan_content,
)


def test_unwrap_mcp_payload_direct():
    payload = {"latitude": 1.0, "current_soil_moisture_pct": 20.0}
    assert _unwrap_mcp_payload(payload) == payload


def test_unwrap_mcp_payload_error_returns_none():
    assert _unwrap_mcp_payload({"error": "failed"}) is None


def test_unwrap_mcp_payload_nested_json():
    payload = {
        "content": [
            {"type": "text", "text": '{"latitude": 2.0, "source": "open-meteo"}'}
        ]
    }
    result = _unwrap_mcp_payload(payload)
    assert result is not None
    assert result["latitude"] == 2.0


def test_extract_mcp_error_from_events():
    response = SimpleNamespace(
        name="fetch_location_metrics",
        response={"error": "Weather API unavailable: timeout"},
    )
    part = SimpleNamespace(function_response=response)
    content = SimpleNamespace(parts=[part])
    event = SimpleNamespace(content=content)
    assert _extract_mcp_error_from_events([event]) == "Weather API unavailable: timeout"


def test_extract_metrics_from_events():
    response = SimpleNamespace(
        name="fetch_location_metrics",
        response={
            "latitude": 19.9,
            "longitude": 80.5,
            "current_soil_moisture_pct": 21.0,
            "source": "open-meteo",
        },
    )
    part = SimpleNamespace(function_response=response)
    content = SimpleNamespace(parts=[part])
    event = SimpleNamespace(content=content)
    metrics = _extract_metrics_from_events([event])
    assert metrics is not None
    assert metrics["latitude"] == 19.9


def test_is_guardrail_payload():
    assert _is_guardrail_payload({"status": "cleared", "stage": "guardrail"})
    assert not _is_guardrail_payload(
        {"irrigation_urgency": "MEDIUM", "reasoning": "Water soon."}
    )


def test_extract_json_plan_from_text_codeblock():
    text = '```json\n{"reasoning": "Plan here.", "actions": ["A"], "irrigation_urgency": "HIGH"}\n```'
    plan = _extract_json_plan_from_text(text)
    assert plan is not None
    assert plan["reasoning"] == "Plan here."
    assert plan["actions"] == ["A"]


def test_extract_coordinator_plan_from_content_text():
    guardrail = SimpleNamespace(
        output={"status": "cleared", "stage": "guardrail"},
        content=None,
    )
    model_text = (
        '{"irrigation_urgency": "MEDIUM", "reasoning": "Soil is moderate.", '
        '"actions": ["Irrigate lightly tonight."], "risks": ["Uneven growth"]}'
    )
    part = SimpleNamespace(text=model_text, function_response=None)
    content = SimpleNamespace(parts=[part])
    coordinator = SimpleNamespace(
        output=None,
        content=content,
    )
    plan = _extract_coordinator_plan([guardrail, coordinator], {"status": "cleared"})
    assert plan["reasoning"] == "Soil is moderate."
    assert plan["actions"] == ["Irrigate lightly tonight."]


def test_enrich_plan_from_metrics_fills_empty_plan():
    metrics = {
        "irrigation_urgency": "MEDIUM",
        "current_soil_moisture_pct": 22.0,
        "forecast_rain_mm_3d": 10.0,
        "profile_used": "Rice",
    }
    enriched = _enrich_plan_from_metrics({}, metrics, "Rice")
    assert enriched["reasoning"]
    assert len(enriched["actions"]) >= 2
    assert enriched["irrigation_urgency"] == "MEDIUM"


def test_enrich_plan_with_source_gemini_when_coordinator_filled():
    plan = {
        "reasoning": "Gemini wrote this.",
        "actions": ["Water tonight."],
        "irrigation_urgency": "HIGH",
    }
    metrics = {"irrigation_urgency": "HIGH", "profile_used": "Rice"}
    enriched, source = enrich_plan_with_source(plan, metrics, "Rice")
    assert source == "gemini"
    assert enriched["reasoning"] == "Gemini wrote this."


def test_enrich_plan_with_source_metrics_fallback_when_empty():
    metrics = {
        "irrigation_urgency": "LOW",
        "forecast_rain_mm_3d": 20.0,
        "profile_used": "Maize",
    }
    enriched, source = enrich_plan_with_source({}, metrics, "Maize")
    assert source == "metrics_fallback"
    assert enriched["reasoning"]
    assert enriched["actions"]


def test_enrich_plan_with_source_mixed_when_partial():
    plan = {"reasoning": "Only summary from Gemini.", "actions": []}
    metrics = {"irrigation_urgency": "MEDIUM", "forecast_rain_mm_3d": 5.0}
    enriched, source = enrich_plan_with_source(plan, metrics, "Wheat")
    assert source == "mixed"
    assert enriched["reasoning"] == "Only summary from Gemini."
    assert enriched["actions"]


def test_ensure_plan_content_fills_ui_result():
    result = {
        "status": "success",
        "irrigation_urgency": "HIGH",
        "reasoning": "",
        "actions": [],
        "data": {
            "irrigation_urgency": "HIGH",
            "current_soil_moisture_pct": 12.0,
            "forecast_rain_mm_3d": 0.0,
            "profile_used": "Rice",
        },
    }
    out = ensure_plan_content(result, "Rice")
    assert out["plan_source"] == "metrics_fallback"
    assert out["reasoning"]
    assert out["actions"]

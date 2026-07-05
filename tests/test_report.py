from agro_agent.report import (
    build_plan_markdown,
    build_plan_pdf,
    forecast_arrays,
    format_result_location,
    urgency_color,
)


def test_format_result_location_live():
    wf = {
        "region_id": "REG-CUST-000000",
        "place_name": "London",
        "country": "UK",
        "latitude": 51.5,
        "longitude": -0.12,
    }
    label = format_result_location(wf, None)
    assert "London" in label
    assert "51.5000" in label


def test_forecast_arrays_nested():
    data = {
        "forecast": {
            "daily_precipitation_mm": [1.0, 2.0],
            "daily_temp_max_celsius": [20.0, 22.0],
        }
    }
    rain, temps = forecast_arrays(data)
    assert len(rain) == 2
    assert len(temps) == 2


def test_build_plan_markdown_includes_urgency():
    result = {
        "irrigation_urgency": "MEDIUM",
        "plan_source": "gemini",
        "reasoning": "Monitor soil moisture.",
        "actions": ["Irrigate lightly in the evening."],
        "risks": [],
        "data": {
            "current_soil_moisture_pct": 22.0,
            "average_temp_celsius": 24.0,
            "current_humidity_pct": 90,
            "forecast_rain_mm_3d": 10.0,
            "soil_moisture_source": "open_meteo_soil",
        },
    }
    wf = {
        "region_id": "REG-CUST-000000",
        "place_name": "Test",
        "country": "Land",
        "latitude": 1.0,
        "longitude": 2.0,
        "radius_m": 500.0,
    }
    md = build_plan_markdown(result, wf, None)
    assert "MEDIUM" in md
    assert "Plan from Gemini" in md
    assert "Monitor soil moisture" in md
    assert "Irrigate lightly" in md


def test_build_plan_markdown_includes_fallback_plan_source():
    result = {
        "irrigation_urgency": "HIGH",
        "plan_source": "metrics_fallback",
        "reasoning": "Fallback plan text.",
        "actions": ["Water soon."],
        "risks": [],
        "data": {},
    }
    wf = {
        "region_id": "REG-CUST-000000",
        "latitude": 1.0,
        "longitude": 2.0,
        "radius_m": 500.0,
    }
    md = build_plan_markdown(result, wf, None)
    assert "Plan from weather rules (fallback)" in md


def test_urgency_color_mapping():
    assert urgency_color("HIGH") == "#dc3545"
    assert urgency_color("LOW") == "#28a745"


def test_build_plan_pdf_full_layout():
    result = {
        "irrigation_urgency": "LOW",
        "plan_source": "gemini",
        "reasoning": "Rain likely sufficient for the next few days.",
        "actions": [],
        "risks": [],
        "data": {
            "current_soil_moisture_pct": 40.0,
            "average_temp_celsius": 22.0,
            "current_humidity_pct": 70,
            "forecast_rain_mm_3d": 12.0,
            "soil_moisture_source": "open_meteo_soil",
            "forecast": {
                "daily_precipitation_mm": [4.0, 5.0, 3.0],
                "daily_temp_max_celsius": [23.0, 24.0, 22.0],
            },
        },
    }
    wf = {
        "region_id": "REG-CUST-000000",
        "place_name": "Pokhara",
        "country": "Nepal",
        "latitude": 28.27,
        "longitude": 83.97,
        "radius_m": 500.0,
    }
    pdf = build_plan_pdf(result, wf, None)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1500
    result = {
        "irrigation_urgency": "LOW",
        "reasoning": "All good.",
        "actions": [],
        "risks": [],
        "data": {},
    }
    wf = {
        "region_id": "REG-CUST-000000",
        "latitude": 1.0,
        "longitude": 2.0,
        "radius_m": 500.0,
    }
    pdf = build_plan_pdf(result, wf, None)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"

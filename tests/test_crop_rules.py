import pytest

from agro_agent.crop_rules import (
    adjust_moisture_thresholds,
    compute_urgency,
    mm_to_liters,
    resolve_crop_profile,
    season_label,
    suggested_irrigation_mm,
)


def test_new_crop_cotton_resolves():
    name, matched = resolve_crop_profile("cotton")
    assert name == "Cotton"
    assert matched is True


def test_season_label_monsoon():
    assert season_label(20.0, 7) == "monsoon"
    assert season_label(20.0, 1) == "dry"
    assert season_label(45.0, 7) == "temperate"


def test_adjust_moisture_monsoon_raises_thresholds():
    base = {"low_moisture": 20.0, "high_moisture": 35.0, "heat_stress_c": 35.0}
    adjusted = adjust_moisture_thresholds(base, "monsoon")
    assert adjusted["low_moisture"] == 25.0


def test_compute_urgency_high_when_dry():
    assert compute_urgency("Maize", 10.0, 25.0, 0.0) == "HIGH"


def test_compute_urgency_rain_reduces_high():
    assert compute_urgency("Maize", 10.0, 25.0, 15.0) == "MEDIUM"


def test_suggested_irrigation_mm_when_below_low():
    mm = suggested_irrigation_mm(10.0, "Maize")
    assert mm > 0


def test_suggested_irrigation_mm_zero_when_ok():
    assert suggested_irrigation_mm(30.0, "Maize") == 0.0


def test_mm_to_liters():
    liters = mm_to_liters(10.0, 100.0)
    assert liters == pytest.approx(314159.26, rel=1e-3)
"""Equipment-specific configuration prevents misleading fuel calculations."""

import pytest
from pydantic import ValidationError

from app.api.analytics_config import GeneratorAnalyticsConfig
from app.api.schemas import PanelCreate, PanelUpdate


def test_unknown_nominal_values_are_not_assumed():
    settings = GeneratorAnalyticsConfig()
    assert settings.nominal_frequency_hz is None
    assert settings.nominal_battery_voltage is None
    assert settings.fuel_lhv_kwh_per_litre is None


@pytest.mark.parametrize("config", [
    {"fuel_lhv_kwh_per_litre": 0},
    {"fuel_lhv_kwh_per_litre": float("inf")},
    {"nominal_battery_voltage": 28},
    {"fuel_source": "tank"},
    {"tank_curve": [{"percent": 0, "litres": 100}, {"percent": 100, "litres": 50}]},
    {"tank_curve": [{"percent": 0, "litres": 0}, {"percent": 50, "litres": 50}]},
    {"fuel_curve": [{"load_percent": 50, "litres_per_hour": 10}, {"load_percent": 50, "litres_per_hour": 12}]},
])
def test_invalid_equipment_calibration_is_rejected(config):
    with pytest.raises(ValidationError):
        PanelUpdate(analytics_config=config)


def test_generator_configuration_round_trip():
    panel = PanelCreate(name="G1", address="127.0.0.1:502", rated_kw=100, analytics_config={
        "nominal_battery_voltage": 24, "nominal_frequency_hz": 60,
        "fuel_source": "tank", "tank_capacity_litres": 400,
        "tank_curve": [{"percent": 100, "litres": 400}, {"percent": 0, "litres": 0}],
    })
    assert panel.analytics_config["nominal_battery_voltage"] == 24
    assert panel.analytics_config["tank_curve"][0] == {"percent": 0, "litres": 0}
    assert "fuel_lhv_kwh_per_litre" not in panel.analytics_config

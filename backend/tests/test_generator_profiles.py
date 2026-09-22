"""The curated equipment catalogue remains safe for commissioning forms."""

from app.api.analytics_config import GeneratorAnalyticsConfig
from app.generator_profiles import GENERATOR_PROFILES, list_generator_profiles


def test_catalogue_has_fifty_manufacturer_profiles_and_custom():
    profiles = list_generator_profiles()
    assert len(GENERATOR_PROFILES) == 50
    assert len(profiles) == 51
    assert profiles[0]["id"] == "custom"
    assert {row["manufacturer"] for row in GENERATOR_PROFILES} == {
        "Caterpillar", "Cummins", "FG Wilson", "Rehlko (Kohler)",
    }
    assert len({row["id"] for row in profiles}) == len(profiles)


def test_manufacturer_profiles_have_ratings_sources_and_valid_curves():
    for profile in GENERATOR_PROFILES:
        assert profile["rated_kw"] > 0
        assert profile["rated_kvar"] >= 0
        assert profile["frequency_hz"] in {50, 60}
        assert profile["source_url"].startswith("https://")
        GeneratorAnalyticsConfig(
            generator_profile_id=profile["id"],
            generator_manufacturer=profile["manufacturer"],
            generator_model=profile["model"],
            engine_model=profile["engine_model"],
            nominal_frequency_hz=profile["frequency_hz"],
            nominal_battery_voltage=profile["nominal_battery_voltage"],
            standby_kw=profile["standby_kw"], prime_kw=profile["prime_kw"],
            standby_kva=profile["standby_kva"], prime_kva=profile["prime_kva"],
            power_factor=profile["power_factor"], speed_rpm=profile["speed_rpm"],
            datasheet_url=profile["source_url"], fuel_curve=profile["fuel_curve"],
        )


def test_catalogue_contains_published_fuel_curves_for_economy_dispatch():
    curves = {row["id"]: row["fuel_curve"] for row in GENERATOR_PROFILES if row["fuel_curve"]}
    assert {"cummins-c100d5-b59", "fg-p50-3", "fg-p88-3", "rehlko-200reozjf"} <= curves.keys()
    assert curves["rehlko-200reozjf"][-1] == {"load_percent": 100, "litres_per_hour": 58.0}


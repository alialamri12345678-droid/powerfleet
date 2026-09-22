"""Validated equipment settings shared by commissioning and report calculations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TankCalibrationPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    percent: float = Field(ge=0, le=100)
    litres: float = Field(ge=0)


class FuelCurvePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    load_percent: float = Field(ge=0, le=110)
    litres_per_hour: float = Field(ge=0)


class GeneratorAnalyticsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    engine_model: str = Field("", max_length=200)
    generator_profile_id: str = Field("custom", max_length=100)
    generator_manufacturer: str = Field("", max_length=120)
    generator_model: str = Field("", max_length=200)
    standby_kw: float | None = Field(None, gt=0, le=10000000)
    prime_kw: float | None = Field(None, gt=0, le=10000000)
    standby_kva: float | None = Field(None, gt=0, le=10000000)
    prime_kva: float | None = Field(None, gt=0, le=10000000)
    power_factor: float | None = Field(None, gt=0, le=1)
    speed_rpm: int | None = Field(None, ge=300, le=5000)
    datasheet_url: str = Field("", max_length=1000)
    fuel_curve_basis: Literal["standby", "prime"] | None = None
    nominal_frequency_hz: Literal[50, 60] | None = None
    nominal_battery_voltage: Literal[12, 24] | None = None
    fuel_type: str = Field("diesel", max_length=80)
    fuel_source: Literal["counter", "flow", "tank"] = "counter"
    fuel_lhv_kwh_per_litre: float | None = Field(None, gt=0, le=100)
    tank_capacity_litres: float | None = Field(None, gt=0, le=10000000)
    tank_curve: list[TankCalibrationPoint] = Field(default_factory=list, max_length=100)
    fuel_curve: list[FuelCurvePoint] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_curves(self):
        if self.tank_curve:
            points = sorted(self.tank_curve, key=lambda item: item.percent)
            if len(points) < 2 or points[0].percent != 0 or points[-1].percent != 100:
                raise ValueError("Tank calibration needs at least two points covering 0–100 percent")
            if any(a.percent >= b.percent or a.litres > b.litres for a, b in zip(points, points[1:])):
                raise ValueError("Tank calibration must have unique percentages and increasing volume")
            if self.tank_capacity_litres and points[-1].litres > self.tank_capacity_litres:
                raise ValueError("Tank calibration exceeds tank capacity")
            self.tank_curve = points
        if self.fuel_curve:
            points = sorted(self.fuel_curve, key=lambda item: item.load_percent)
            if len(points) < 2 or any(a.load_percent >= b.load_percent for a, b in zip(points, points[1:])):
                raise ValueError("Fuel curve needs at least two distinct load percentages")
            self.fuel_curve = points
        if self.fuel_source == "tank" and not self.tank_curve:
            raise ValueError("Tank fuel estimation requires a calibrated level-to-volume curve")
        return self

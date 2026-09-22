"""Validation for optional adaptive site dispatch and source measurements."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DispatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["legacy", "advisory", "automatic"] = "legacy"
    policy: Literal["priority", "capacity", "economy"] = "priority"
    grid_present: bool = False
    solar_present: bool = False
    solar_grid_forming: bool = False
    solar_curtailable: bool = False
    grid_import_limit_kw: float | None = Field(None, ge=0, le=10000000)
    max_load_percent: float = Field(80, ge=20, le=100)
    min_load_percent: float = Field(0, ge=0, le=70)
    reserve_kw: float = Field(0, ge=0, le=10000000)
    solar_loss_fraction: float = Field(1, ge=0, le=1)
    measurement_max_age_seconds: int = Field(15, ge=2, le=120)
    transition_dwell_seconds: int = Field(120, ge=30, le=3600)
    topology_verified: bool = False

    @model_validator(mode="after")
    def check(self):
        if self.min_load_percent >= self.max_load_percent:
            raise ValueError("Minimum generator load must be below the maximum")
        if self.grid_import_limit_kw is not None and not self.grid_present:
            raise ValueError("Grid import limit requires a grid source")
        if (self.solar_grid_forming or self.solar_curtailable) and not self.solar_present:
            raise ValueError("Solar capabilities require a solar source")
        if self.mode == "automatic" and not self.topology_verified:
            raise ValueError("Automatic dispatch requires a verified electrical topology")
        if self.mode == "automatic" and self.grid_present and self.grid_import_limit_kw is None:
            raise ValueError("Automatic grid dispatch requires a verified import capacity")
        return self


class SitePowerReading(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    measured_at: datetime
    load_kw: float = Field(ge=0, le=10000000)
    solar_kw: float = Field(0, ge=0, le=10000000)
    # Positive values mean power imported from the utility; negative values
    # mean the facility is exporting power to it.
    grid_kw: float | None = Field(None, ge=-10000000, le=10000000)
    grid_connected: bool = False
    bus_energized: bool = False

    @model_validator(mode="after")
    def check(self):
        if self.measured_at.tzinfo is None:
            raise ValueError("Measurement timestamp must include a timezone")
        return self

"""Typed, data-driven equipment and controller profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FieldValue:
    value: Any = None
    classification: str = "unknown"

    def __post_init__(self) -> None:
        if self.classification not in {"manufacturer_spec", "simulation_parameter", "unknown"}:
            raise ValueError(f"invalid data classification: {self.classification}")


@dataclass(frozen=True)
class ProfileMetadata:
    source: str | None = None
    source_document: str | None = None
    source_url: str | None = None
    datasheet_revision: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class GeneratorProfile:
    profile_id: str
    manufacturer: FieldValue
    model: FieldValue
    engine_manufacturer: FieldValue
    engine_model: FieldValue
    alternator_manufacturer: FieldValue
    alternator_model: FieldValue
    prime_power_kw: FieldValue
    standby_power_kw: FieldValue
    rated_kva: FieldValue
    rated_voltage_v: FieldValue
    rated_frequency_hz: FieldValue
    rated_current_a: FieldValue
    rated_power_factor: FieldValue
    rated_rpm: FieldValue
    phases: FieldValue
    fuel_type: FieldValue
    parameters: dict[str, FieldValue] = field(default_factory=dict)
    metadata: ProfileMetadata = field(default_factory=ProfileMetadata)


@dataclass(frozen=True)
class ControllerProfile:
    profile_id: str
    model: str
    family: str
    gencomm_version: int
    role: str
    supported_features: tuple[str, ...]
    supported_pages: tuple[int, ...]
    read_only_registers: tuple[int, ...]
    writable_registers: tuple[int, ...]
    communications: dict[str, Any]
    metadata: ProfileMetadata = field(default_factory=ProfileMetadata)


def _field(raw: Any) -> FieldValue:
    if isinstance(raw, dict) and "classification" in raw:
        return FieldValue(raw.get("value"), raw["classification"])
    return FieldValue(raw, "unknown")


def _metadata(raw: dict[str, Any]) -> ProfileMetadata:
    return ProfileMetadata(**{key: raw.get(key) for key in ProfileMetadata.__dataclass_fields__})


def load_generator_profile(path: str | Path) -> GeneratorProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return generator_profile_from_dict(raw)


def generator_profile_from_dict(raw: dict[str, Any]) -> GeneratorProfile:
    keys = (
        "manufacturer", "model", "engine_manufacturer", "engine_model",
        "alternator_manufacturer", "alternator_model", "prime_power_kw",
        "standby_power_kw", "rated_kva", "rated_voltage_v",
        "rated_frequency_hz", "rated_current_a", "rated_power_factor",
        "rated_rpm", "phases", "fuel_type",
    )
    values = {key: _field(raw.get(key)) for key in keys}
    params = {key: _field(value) for key, value in raw.get("parameters", {}).items()}
    return GeneratorProfile(raw["profile_id"], **values, parameters=params, metadata=_metadata(raw.get("metadata", {})))


def load_controller_profile(path: str | Path) -> ControllerProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return controller_profile_from_dict(raw)


def controller_profile_from_dict(raw: dict[str, Any]) -> ControllerProfile:
    return ControllerProfile(
        profile_id=raw["profile_id"], model=raw["model"], family=raw["family"],
        gencomm_version=int(raw["gencomm_version"]), role=raw["role"],
        supported_features=tuple(raw.get("supported_features", [])),
        supported_pages=tuple(int(x) for x in raw.get("supported_pages", [])),
        read_only_registers=tuple(int(x) for x in raw.get("read_only_registers", [])),
        writable_registers=tuple(int(x) for x in raw.get("writable_registers", [])),
        communications=dict(raw.get("communications", {})),
        metadata=_metadata(raw.get("metadata", {})),
    )


def _merge_profile(defaults: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in item.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load_catalog_entry(config_root: str | Path, kind: str, profile_id: str) -> dict[str, Any]:
    filename = "generator_manufacturers.json" if kind == "generator" else "dse_controllers.json"
    raw = json.loads((Path(config_root) / "catalogs" / filename).read_text(encoding="utf-8"))
    for item in raw.get("profiles", []):
        if item.get("profile_id") == profile_id:
            return _merge_profile(raw.get("defaults", {}), item)
    raise KeyError(f"unknown {kind} catalog profile: {profile_id}")


def load_generator_profile_reference(config_root: str | Path, reference: str) -> GeneratorProfile:
    if reference.startswith("catalog:generator:"):
        return generator_profile_from_dict(load_catalog_entry(config_root, "generator", reference.rsplit(":", 1)[-1]))
    return load_generator_profile(Path(config_root) / reference)


def load_controller_profile_reference(config_root: str | Path, reference: str) -> ControllerProfile:
    if reference.startswith("catalog:controller:"):
        return controller_profile_from_dict(load_catalog_entry(config_root, "controller", reference.rsplit(":", 1)[-1]))
    return load_controller_profile(Path(config_root) / reference)

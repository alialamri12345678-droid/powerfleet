"""Persistent, validated site and generator configuration management."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any

from simulator_core.profiles import (
    load_catalog_entry, load_controller_profile, load_controller_profile_reference,
    load_generator_profile, load_generator_profile_reference,
)


class ConfigurationError(ValueError):
    pass


class SiteRepository:
    def __init__(self, config_root: str | Path):
        self.root = Path(config_root).resolve()
        self.sites_dir = self.root / "sites"
        self.sites_dir.mkdir(parents=True, exist_ok=True)

    def list_sites(self) -> list[Path]:
        files = list(self.sites_dir.glob("*.json"))
        demo = self.root / "plant.demo.json"
        if demo.exists():
            files.append(demo)
        return sorted(set(path.resolve() for path in files), key=lambda path: self.site_name(path).lower())

    def site_name(self, path: str | Path) -> str:
        try:
            return str(self.load(path).get("name") or Path(path).stem)
        except Exception:
            return Path(path).stem

    def load(self, path: str | Path) -> dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path, data: dict[str, Any]) -> Path:
        self.validate(data, Path(path).parent)
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return destination

    def create_site(self, name: str, voltage_v: float = 400, frequency_hz: float = 50) -> Path:
        clean_name = name.strip()
        if not clean_name:
            raise ConfigurationError("site name is required")
        slug = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_") or "site"
        destination = self.sites_dir / f"{slug}.json"
        suffix = 2
        while destination.exists():
            destination = self.sites_dir / f"{slug}_{suffix}.json"
            suffix += 1
        data = {
            "name": clean_name, "voltage_v": float(voltage_v), "frequency_hz": float(frequency_hz),
            "modbus_rtu": {"enabled": False, "serial_port": "COM9", "baudrate": 19200, "data_bits": 8, "parity": "N", "stop_bits": 1},
            "generators": [], "grid": {"enabled": True, "closed_on_start": True, "voltage_v": float(voltage_v), "frequency_hz": float(frequency_hz)},
            "solar": {"enabled": False, "closed_on_start": False, "name": "SOLAR", "rated_kw": 500, "irradiance_pct": 100, "inverter_efficiency": .98, "ramp_kw_per_s": 100},
            "power_management": {"enabled": True, "automatic_start_stop": True, "automatic_breaker_control": False, "spinning_reserve_kw": 0, "minimum_generator_loading_enabled": True, "grid_import_target_kw": None, "grid_export_limit_kw": 0, "load_share_mode": "proportional"},
            "loads": [],
            "synchronization": {"max_frequency_difference_hz": .2, "max_voltage_difference_pct": 5, "max_phase_angle_difference_deg": 10, "minimum_stable_s": .5, "timeout_s": 30},
        }
        return self.save(destination, data)

    def clone_site(self, source: str | Path, new_name: str) -> Path:
        data = deepcopy(self.load(source))
        data["name"] = new_name.strip()
        destination = self.create_site(new_name, data.get("voltage_v", 400), data.get("frequency_hz", 50))
        return self.save(destination, data)

    def delete_site(self, path: str | Path) -> None:
        target = Path(path).resolve()
        if target.parent != self.sites_dir:
            raise ConfigurationError("the built-in demo site cannot be deleted")
        trash = self.root / "trash" / datetime.now().strftime("%Y%m%d_%H%M%S")
        trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(trash / target.name))
        site_data = self.root / "site_data" / target.stem
        if site_data.exists():
            shutil.move(str(site_data), str(trash / f"{target.stem}_site_data"))

    def equipment_profiles(self) -> list[Path]:
        return sorted((self.root / "equipment" / "generators").glob("*.json"))

    def controller_profiles(self) -> list[Path]:
        return sorted((self.root / "controllers").glob("*.json"))

    def generator_profile_options(self) -> dict[str, str]:
        options: dict[str, str] = {}
        for path in self.equipment_profiles():
            profile = load_generator_profile(path)
            options[f"{profile.manufacturer.value or 'Unknown'} — {profile.model.value or profile.profile_id}"] = self.relative_profile(path)
        catalog = json.loads((self.root / "catalogs" / "generator_manufacturers.json").read_text(encoding="utf-8"))
        for item in catalog.get("profiles", []):
            options[f"{item['manufacturer']['value']} — adjustable template"] = f"catalog:generator:{item['profile_id']}"
        return dict(sorted(options.items()))

    def controller_profile_options(self, target: str = "all") -> dict[str, str]:
        options: dict[str, str] = {}
        for path in self.controller_profiles():
            profile = load_controller_profile(path)
            if target == "generator" and profile.role in {"mains_controller", "bus_tie_controller", "ats_controller"}:
                continue
            if target == "mains" and profile.role not in {"mains_controller", "mains_parallel_genset_controller", "ats_controller"}:
                continue
            options[f"{profile.model} ({profile.role})"] = self.relative_profile(path)
        catalog = json.loads((self.root / "catalogs" / "dse_controllers.json").read_text(encoding="utf-8"))
        for item in catalog.get("profiles", []):
            role = item.get("role", catalog.get("defaults", {}).get("role", "controller"))
            if target == "generator" and role in {"mains_controller", "bus_tie_controller", "ats_controller"}:
                continue
            if target == "mains" and role not in {"mains_controller", "mains_parallel_genset_controller", "ats_controller"}:
                continue
            options[f"{item['model']} ({role})"] = f"catalog:controller:{item['profile_id']}"
        return dict(sorted(options.items()))

    def relative_profile(self, path: str | Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    def add_generator(
        self, data: dict[str, Any], name: str, equipment_profile: str,
        controller_profile: str, host: str, port: int, unit_id: int,
        rated_kw_override: float | None = None,
    ) -> dict[str, Any]:
        names = {str(item.get("name", "")).lower() for item in data.setdefault("generators", [])}
        if name.strip().lower() in names:
            raise ConfigurationError(f"generator name already exists: {name}")
        generator = {
            "name": name.strip(), "equipment_profile": equipment_profile,
            "controller_profile": controller_profile,
            "priority": len(data["generators"]) + 1,
            "modbus": {"host": host.strip() or "0.0.0.0", "port": int(port), "unit_id": int(unit_id)},
        }
        if rated_kw_override is not None:
            generator["rated_kw_override"] = float(rated_kw_override)
        data["generators"].append(generator)
        return generator

    def validate(self, data: dict[str, Any], base: Path | None = None) -> None:
        if not str(data.get("name", "")).strip():
            raise ConfigurationError("site name is required")
        if float(data.get("voltage_v", 0)) <= 0:
            raise ConfigurationError("site voltage must be greater than zero")
        if float(data.get("frequency_hz", 0)) <= 0:
            raise ConfigurationError("site frequency must be greater than zero")
        names: set[str] = set()
        endpoints: set[tuple[str, int, int]] = set()
        for index, generator in enumerate(data.get("generators", []), 1):
            name = str(generator.get("name", "")).strip()
            if not name or name.lower() in names:
                raise ConfigurationError(f"generator {index} has a missing or duplicate name")
            names.add(name.lower())
            mb = generator.get("modbus", {})
            port, unit_id = int(mb.get("port", 0)), int(mb.get("unit_id", 0))
            if not 1 <= port <= 65535:
                raise ConfigurationError(f"{name}: TCP port must be 1..65535")
            if not 1 <= unit_id <= 247:
                raise ConfigurationError(f"{name}: Modbus unit ID must be 1..247")
            endpoint = (str(mb.get("host", "0.0.0.0")), port, unit_id)
            if endpoint in endpoints:
                raise ConfigurationError(f"duplicate Modbus endpoint/unit combination: {endpoint}")
            endpoints.add(endpoint)
            for key, loader in (("equipment_profile", load_generator_profile), ("controller_profile", load_controller_profile)):
                reference = generator.get(key, "")
                loaded_profile = None
                if str(reference).startswith("catalog:"):
                    try:
                        loaded_profile = (load_generator_profile_reference if key == "equipment_profile" else load_controller_profile_reference)(self.root, reference)
                    except (KeyError, ValueError, OSError) as exc:
                        raise ConfigurationError(f"{name}: invalid {key}: {exc}") from exc
                else:
                    profile = Path(reference)
                    if not profile.is_absolute():
                        profile = ((base or self.root) / profile).resolve()
                        if not profile.exists():
                            profile = (self.root / generator.get(key, "")).resolve()
                    if not profile.exists():
                        raise ConfigurationError(f"{name}: missing {key}: {generator.get(key)}")
                    loaded_profile = loader(profile)
                if key == "controller_profile" and loaded_profile.role in {"mains_controller", "bus_tie_controller", "ats_controller"}:
                    raise ConfigurationError(f"{name}: {loaded_profile.model} is not a genset controller profile")
        if len(data.get("generators", [])) > 20:
            raise ConfigurationError("a site may contain at most 20 generators")
        mains = data.get("mains_controller")
        if mains:
            reference = mains.get("controller_profile", "")
            try:
                profile = load_controller_profile_reference(self.root, reference)
            except (KeyError, ValueError, OSError) as exc:
                raise ConfigurationError(f"invalid mains controller profile: {exc}") from exc
            if profile.role not in {"mains_controller", "mains_parallel_genset_controller", "ats_controller"}:
                raise ConfigurationError(f"{profile.model} is not a mains/ATS controller profile")
            mb = mains.get("modbus", {})
            port, unit_id = int(mb.get("port", 0)), int(mb.get("unit_id", 0))
            if not 1 <= port <= 65535 or not 1 <= unit_id <= 247:
                raise ConfigurationError("mains controller TCP port or unit ID is outside the valid range")
            endpoint = (str(mb.get("host", "0.0.0.0")), port, unit_id)
            if endpoint in endpoints:
                raise ConfigurationError(f"duplicate Modbus endpoint/unit combination: {endpoint}")

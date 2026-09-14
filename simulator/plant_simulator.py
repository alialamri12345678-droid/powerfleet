"""Modular plant simulator entry point. The legacy dse_simulator.py remains available."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from runtime import SimulatorRuntime
from ui.plant_ui import PlantSimulatorUI


def main() -> None:
    parser = argparse.ArgumentParser(description="Modular DSE GenComm plant simulator")
    parser.add_argument("--config", default=None, help="Site JSON; otherwise uses the UI-selected active site")
    parser.add_argument("--no-modbus", action="store_true", help="Run UI without binding TCP ports")
    args = parser.parse_args()
    config_root = Path(__file__).parent / "config"
    active_file = config_root / "active_site.txt"
    selected = Path(args.config).resolve() if args.config else None
    if selected is None and active_file.exists():
        candidate = Path(active_file.read_text(encoding="utf-8").strip())
        if candidate.exists(): selected = candidate.resolve()
    selected = selected or (config_root / "plant.demo.json")
    runtime = SimulatorRuntime(selected, enable_modbus=not args.no_modbus)
    if not args.no_modbus:
        runtime.start_servers()
    restart_with = PlantSimulatorUI(runtime).run()
    if restart_with:
        command = [sys.executable, str(Path(__file__).resolve()), "--config", str(restart_with)]
        if args.no_modbus:
            command.append("--no-modbus")
        os.execv(sys.executable, command)


if __name__ == "__main__":
    main()

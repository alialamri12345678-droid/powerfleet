"""Command rate-limiter / cooldown enforcement.

This is the last line of defense against rapid-cycling an engine.
It operates independently of the rules engine — even if a bug or
bad user input tries to rapid-cycle, this layer blocks it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CooldownResult:
    """Result of a cooldown check."""
    allowed: bool
    reason: str = ""
    retry_after_seconds: float = 0.0


@dataclass
class PanelCooldown:
    """Tracks the last start/stop command time for one panel."""
    last_start_time: float | None = None  # monotonic
    last_stop_time: float | None = None   # monotonic


class CooldownManager:
    """Per-panel command rate-limiter.

    Enforces:
    - Minimum run time: after a Start, no Stop is allowed for N seconds.
    - Minimum rest time: after a Stop, no Start is allowed for N seconds.
    """

    def __init__(
        self,
        min_run_seconds: int | None = None,
        min_rest_seconds: int | None = None,
    ):
        self._min_run = min_run_seconds or settings.command_min_run_seconds
        self._min_rest = min_rest_seconds or settings.command_min_rest_seconds
        self._panels: dict[str, PanelCooldown] = {}

    def _get(self, panel_id: str) -> PanelCooldown:
        if panel_id not in self._panels:
            self._panels[panel_id] = PanelCooldown()
        return self._panels[panel_id]

    def check_start(self, panel_id: str) -> CooldownResult:
        """Check if a Remote Start command is allowed right now."""
        cd = self._get(panel_id)
        now = time.monotonic()

        if cd.last_stop_time is not None:
            elapsed = now - cd.last_stop_time
            if elapsed < self._min_rest:
                remaining = self._min_rest - elapsed
                return CooldownResult(
                    allowed=False,
                    reason=(
                        f"Rest cooldown active: {remaining:.0f}s remaining "
                        f"(minimum {self._min_rest}s rest after stop)"
                    ),
                    retry_after_seconds=remaining,
                )

        return CooldownResult(allowed=True)

    def check_stop(self, panel_id: str) -> CooldownResult:
        """Check if a Remote Stop command is allowed right now."""
        cd = self._get(panel_id)
        now = time.monotonic()

        if cd.last_start_time is not None:
            elapsed = now - cd.last_start_time
            if elapsed < self._min_run:
                remaining = self._min_run - elapsed
                return CooldownResult(
                    allowed=False,
                    reason=(
                        f"Run cooldown active: {remaining:.0f}s remaining "
                        f"(minimum {self._min_run}s run after start)"
                    ),
                    retry_after_seconds=remaining,
                )

        return CooldownResult(allowed=True)

    def record_start(self, panel_id: str) -> None:
        """Record that a Start command was just sent."""
        cd = self._get(panel_id)
        cd.last_start_time = time.monotonic()
        logger.debug("Recorded START for panel %s", panel_id)

    def record_stop(self, panel_id: str) -> None:
        """Record that a Stop command was just sent."""
        cd = self._get(panel_id)
        cd.last_stop_time = time.monotonic()
        logger.debug("Recorded STOP for panel %s", panel_id)

    def reset(self, panel_id: str) -> None:
        """Clear cooldown state for a panel (e.g. after gateway restart reconciliation)."""
        self._panels.pop(panel_id, None)

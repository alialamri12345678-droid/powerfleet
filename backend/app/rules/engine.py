"""Rules engine — orchestrates scheduled and threshold-based panel control.

Uses APScheduler to fire time-based schedule rules and piggybacks on
the gateway's poll loop for threshold-based load monitoring. Every
automated action is logged with a human-readable reason.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.modbus.gateway import ModbusGateway
from app.modbus.panel_state import PanelState
from app.rules.fleet_dispatcher import FleetDispatcher, DesiredState

logger = logging.getLogger(__name__)


class RulesEngine:
    """Coordinates schedule rules and threshold rules.

    This is advisory/orchestration only — it calls gateway.send_remote_start()
    and gateway.send_remote_stop(), never touches electrical control directly.
    """

    def __init__(self, gateway: ModbusGateway):
        self._gateway = gateway
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._dispatcher = FleetDispatcher(gateway)

        # State intent tracking for the Fleet Dispatcher
        self._schedule_wants: dict[str, DesiredState] = {}
        self._threshold_started: dict[str, datetime] = {}
        self._threshold_wants: dict[str, DesiredState] = {}
        
        # Track replacement units started due to faults
        self._fault_started: dict[str, datetime] = {}
        self._fault_wants: dict[str, DesiredState] = {}

        # Track scheduled jobs by ID for dynamic updates
        self._schedule_jobs: dict[str, str] = {}  # schedule_id → apscheduler_job_id

        # Evaluation lock and debounce
        self._eval_lock = asyncio.Lock()
        self._last_eval_time = 0.0

        # DB accessor functions (set by main.py during startup)
        self._get_schedules = None
        self._get_thresholds = None
        self._get_overrides = None
        self._get_site = None
        self._get_threshold_state = None
        self._get_panel = None
        self._get_schedule_exceptions = None

    def set_data_accessors(
        self,
        get_schedules=None,
        get_schedule_exceptions=None,
        get_thresholds=None,
        get_overrides=None,
        get_site=None,
        get_threshold_state=None,
        get_panel=None,
    ):
        """Set the async functions used to read schedules/thresholds from DB."""
        self._get_schedules = get_schedules
        self._get_schedule_exceptions = get_schedule_exceptions
        self._get_thresholds = get_thresholds
        self._get_overrides = get_overrides
        self._get_site = get_site
        self._get_threshold_state = get_threshold_state
        self._get_panel = get_panel

    async def start(self) -> None:
        """Start the scheduler and register the threshold check listener."""
        # Reconstruct threshold state from database
        if self._get_threshold_state:
            threshold_started = await self._get_threshold_state()
            # Only keep panels that are actually running right now
            for pid, started_at in threshold_started.items():
                state = self._gateway.states.get(pid)
                if state and state.is_running:
                    self._threshold_started[pid] = started_at
                    self._threshold_wants[pid] = "RUNNING"
            
        self._scheduler.start()
        # Register threshold checker on every gateway poll
        self._gateway.on_state_update(self._on_panel_state_update)
        logger.info("Rules engine started, reconstructed %d threshold-started panels", len(self._threshold_started))

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        logger.info("Rules engine stopped")

    # ── Dispatch Orchestration ────────────────────────────────────────

    async def _reconcile_fleet(self) -> None:
        """Gather all intents and dispatch through the FleetDispatcher."""
        overrides_wants: dict[str, DesiredState] = {}
        
        if self._get_overrides:
            for pid in self._gateway.states.keys():
                overrides = await self._get_overrides(pid)
                now = datetime.now(timezone.utc)
                for override in overrides:
                    if override.get("is_active") and override.get("expires_at"):
                        expires = override["expires_at"]
                        if isinstance(expires, str):
                            expires = datetime.fromisoformat(expires)
                        if expires > now:
                            # We have an active override
                            otype = override.get("override_type")
                            if otype == "force_start":
                                overrides_wants[pid] = "RUNNING"
                            elif otype == "force_stop":
                                overrides_wants[pid] = "STOPPED"
                            break

        desired_state = self._dispatcher.compute_desired_state(
            schedule_wants=self._schedule_wants,
            threshold_wants=self._threshold_wants,
            overrides=overrides_wants,
            fault_wants=self._fault_wants,
        )
        
        await self._dispatcher.reconcile(desired_state)

    # ── Schedule Management ───────────────────────────────────────────

    async def load_schedules(self, schedules: list[dict[str, Any]]) -> None:
        """Load schedule entries from the database and create APScheduler jobs."""
        # Remove all existing schedule jobs
        for job_id in list(self._schedule_jobs.values()):
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        self._schedule_jobs.clear()

        for sched in schedules:
            if not sched.get("is_active", True):
                continue
            await self._add_schedule_jobs(sched)

        logger.info("Loaded %d schedule entries", len(schedules))
        
        if self._get_schedule_exceptions:
            exceptions = await self._get_schedule_exceptions()
            for exc in exceptions:
                if exc.get("is_active"):
                    await self._add_schedule_exception_jobs(exc)
            logger.info("Loaded %d schedule exceptions", len(exceptions))

    async def _add_schedule_exception_jobs(self, exc: dict[str, Any]) -> None:
        """Create start/stop APScheduler jobs for a one-off exception."""
        exc_id = exc["id"]
        panel_id = exc["panel_id"]
        exc_date = exc["exception_date"]
        start_time = exc["start_time"]
        end_time = exc["end_time"]
        
        if not start_time or not end_time:
            return

        from apscheduler.triggers.date import DateTrigger
        
        # Convert date and time to datetime
        start_h, start_m = map(int, start_time.split(":"))
        end_h, end_m = map(int, end_time.split(":"))
        
        start_dt = datetime.combine(exc_date, datetime.min.time()).replace(hour=start_h, minute=start_m)
        end_dt = datetime.combine(exc_date, datetime.min.time()).replace(hour=end_h, minute=end_m)
        
        now = datetime.now()
        if start_dt > now:
            start_job_id = f"exc_start_{exc_id}"
            self._scheduler.add_job(
                self._execute_scheduled_start,
                DateTrigger(run_date=start_dt),
                id=start_job_id,
                kwargs={"panel_id": panel_id, "schedule_id": exc_id, "is_exception": True},
                replace_existing=True,
            )
            self._schedule_jobs[f"{exc_id}_start"] = start_job_id
            
        if end_dt > now:
            stop_job_id = f"exc_stop_{exc_id}"
            self._scheduler.add_job(
                self._execute_scheduled_stop,
                DateTrigger(run_date=end_dt),
                id=stop_job_id,
                kwargs={"panel_id": panel_id, "schedule_id": exc_id, "is_exception": True},
                replace_existing=True,
            )
            self._schedule_jobs[f"{exc_id}_stop"] = stop_job_id

    async def _add_schedule_jobs(self, sched: dict[str, Any]) -> None:
        """Create start/stop APScheduler jobs for a single schedule entry."""
        schedule_id = sched["id"]
        panel_id = sched["panel_id"]
        day_of_week = sched["day_of_week"]
        start_time = sched["start_time"]  # "HH:MM"
        end_time = sched["end_time"]
        site_tz = sched.get("timezone", "UTC")

        # APScheduler day_of_week: mon=0, sun=6 (same as our ISO format)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        day_name = day_names[day_of_week]

        start_h, start_m = map(int, start_time.split(":"))
        end_h, end_m = map(int, end_time.split(":"))

        # Start job
        start_job_id = f"sched_start_{schedule_id}"
        self._scheduler.add_job(
            self._execute_scheduled_start,
            CronTrigger(
                day_of_week=day_name,
                hour=start_h,
                minute=start_m,
                timezone=site_tz,
            ),
            id=start_job_id,
            kwargs={
                "panel_id": panel_id,
                "schedule_id": schedule_id,
            },
            replace_existing=True,
        )

        # Stop job
        stop_job_id = f"sched_stop_{schedule_id}"
        self._scheduler.add_job(
            self._execute_scheduled_stop,
            CronTrigger(
                day_of_week=day_name,
                hour=end_h,
                minute=end_m,
                timezone=site_tz,
            ),
            id=stop_job_id,
            kwargs={
                "panel_id": panel_id,
                "schedule_id": schedule_id,
            },
            replace_existing=True,
        )

        self._schedule_jobs[f"{schedule_id}_start"] = start_job_id
        self._schedule_jobs[f"{schedule_id}_stop"] = stop_job_id

    async def _execute_scheduled_start(
        self, panel_id: str, schedule_id: str, is_exception: bool = False
    ) -> None:
        """Execute a scheduled Remote Start by updating intent."""
        # Skip if there's a holiday exception for today and this isn't the exception job itself
        if not is_exception and self._get_schedule_exceptions:
            exceptions = await self._get_schedule_exceptions()
            today = datetime.now().date()
            if any(e["panel_id"] == panel_id and e["exception_date"] == today and not e["is_active"] for e in exceptions):
                logger.info("Schedule %s skipped due to holiday exception for panel %s", schedule_id, panel_id)
                return

        logger.info("Schedule trigger: START panel %s (schedule %s)", panel_id, schedule_id)
        self._schedule_wants[panel_id] = "RUNNING"
        # Immediate reconciliation will be handled by the next poll cycle, 
        # but we can trigger one now for responsiveness
        await self._reconcile_fleet()

    async def _execute_scheduled_stop(
        self, panel_id: str, schedule_id: str, is_exception: bool = False
    ) -> None:
        """Execute a scheduled Remote Stop by updating intent."""
        if not is_exception and self._get_schedule_exceptions:
            exceptions = await self._get_schedule_exceptions()
            today = datetime.now().date()
            if any(e["panel_id"] == panel_id and e["exception_date"] == today and not e["is_active"] for e in exceptions):
                logger.info("Schedule %s skipped due to holiday exception for panel %s", schedule_id, panel_id)
                return
                
        logger.info("Schedule trigger: STOP panel %s (schedule %s)", panel_id, schedule_id)
        self._schedule_wants[panel_id] = "STOPPED"
        await self._reconcile_fleet()

    # ── Threshold Rules ───────────────────────────────────────────────

    async def _on_panel_state_update(
        self, panel_id: str, state: PanelState
    ) -> None:
        """Called on every poll cycle — evaluate threshold rules."""
        if not self._get_thresholds:
            return

        import time
        now = time.monotonic()
        if now - self._last_eval_time < 5.0:  # Evaluate at most every 5 seconds
            return

        if self._eval_lock.locked():
            return  # Skip if previous evaluation still running

        async with self._eval_lock:
            self._last_eval_time = now
            try:
                await self._evaluate_faults()
                await self._evaluate_thresholds()
            except Exception as exc:
                logger.error("Evaluation error: %s", exc)

    async def _evaluate_thresholds(self) -> None:
        """Check site load against thresholds and start/stop backup panels."""
        if not self._get_thresholds:
            return

        thresholds = await self._get_thresholds()
        if not thresholds:
            return

        for threshold in thresholds:
            await self._evaluate_single_threshold(threshold)
            
        await self._reconcile_fleet()

    async def _evaluate_faults(self) -> None:
        """Monitor for failed starts or overloads and start replacement/relief units."""
        idle_panels: list[str] = []
        critical_faults = 0
        overloads = 0
        
        for pid, state in self._gateway.states.items():
            if not state.is_reachable or not state.is_data_fresh:
                continue
                
            if state.engine_status == "stopped" and not state.active_alarms:
                idle_panels.append(pid)
                
            # If a panel wants to run (via schedule or threshold) but is faulted
            wants_to_run = self._schedule_wants.get(pid) == "RUNNING" or self._threshold_wants.get(pid) == "RUNNING"
            is_faulted = "fail_to_start" in state.active_alarms or "emergency_stop" in state.active_alarms
            
            if wants_to_run and is_faulted:
                critical_faults += 1
                
            if state.is_running and "overload_alarm" in state.active_alarms:
                overloads += 1
                
        required_replacements = critical_faults + overloads
        current_replacements = len(self._fault_started)
        
        # Start new replacements if needed
        while current_replacements < required_replacements and idle_panels:
            best_backup = await self._pick_backup(idle_panels)
            if not best_backup:
                break
                
            idle_panels.remove(best_backup)
            self._fault_started[best_backup] = datetime.now(timezone.utc)
            self._fault_wants[best_backup] = "RUNNING"
            current_replacements += 1
            logger.warning("Fault response: starting replacement unit %s", best_backup)
            
        # Stop replacements if faults are cleared
        if current_replacements > required_replacements:
            # We have more replacements running than active faults. Stop the oldest.
            for pid in list(self._fault_started.keys()):
                if current_replacements <= required_replacements:
                    break
                self._fault_wants[pid] = "STOPPED"
                del self._fault_started[pid]
                current_replacements -= 1
                logger.info("Fault response: stopping unneeded replacement unit %s", pid)

    async def _evaluate_single_threshold(self, threshold: dict[str, Any]) -> None:
        """Evaluate a single threshold rule."""
        site_id = threshold["site_id"]
        start_pct = float(threshold["start_pct"])
        stop_pct = float(threshold["stop_pct"])
        dwell_seconds = threshold["dwell_seconds"]

        # Calculate total site load across all running panels
        total_load_pct = 0.0
        running_panels: list[str] = []
        idle_panels: list[str] = []

        for pid, state in self._gateway.states.items():
            if not state.is_reachable or not state.is_data_fresh:
                continue
            if state.is_running:
                total_load_pct += state.load_kw_percent
                running_panels.append(pid)
            elif state.engine_status == "stopped":
                idle_panels.append(pid)

        if not running_panels:
            return  # No panels running — nothing to evaluate

        # Average load across running panels
        avg_load = total_load_pct / len(running_panels) if running_panels else 0

        # LOAD TOO HIGH — start a backup
        if avg_load >= start_pct and idle_panels:
            # Check for max parallel units
            site_info = await self._get_site(site_id) if self._get_site else None
            max_parallel = site_info.get("max_parallel_units") if site_info else None

            if max_parallel and len(running_panels) >= max_parallel:
                logger.debug(
                    "Load at %.1f%% but max parallel (%d) reached",
                    avg_load, max_parallel,
                )
                return
                
            # Calculate how much kW capacity we need to add to get the average load below the stop_pct
            total_current_kw = sum(
                self._gateway.states[pid].load_kw for pid in running_panels 
                if pid in self._gateway.states
            )
            total_rated_kw = 0.0
            for pid in running_panels:
                panel_info = await self._get_panel(pid) if getattr(self, "_get_panel", None) else None
                if panel_info:
                    total_rated_kw += panel_info.get("rated_kw", 0.0)
            
            needed_kw = 0.0
            if stop_pct > 0 and total_rated_kw > 0:
                target_total_capacity = total_current_kw / (stop_pct / 100.0)
                needed_kw = target_total_capacity - total_rated_kw

            # Pick backup with fewest run hours, trying to meet needed_kw
            best_backup = await self._pick_backup(idle_panels, needed_kw)
            if not best_backup:
                return

            # Don't start if already started by threshold
            if best_backup in self._threshold_started:
                return

            self._threshold_started[best_backup] = datetime.now(timezone.utc)
            self._threshold_wants[best_backup] = "RUNNING"
            logger.info(
                "Threshold rule: wants backup %s RUNNING (load %.1f%% > %.1f%%)",
                best_backup, avg_load, start_pct,
            )

        # LOAD DROPPED — stop backup (with dwell time)
        elif avg_load <= stop_pct:
            for panel_id, started_at in list(self._threshold_started.items()):
                elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                if elapsed < dwell_seconds:
                    logger.debug(
                        "Dwell time not met for %s: %.0f/%ds",
                        panel_id, elapsed, dwell_seconds,
                    )
                    continue

                self._threshold_wants[panel_id] = "STOPPED"
                del self._threshold_started[panel_id]
                logger.info(
                    "Threshold rule: wants backup %s STOPPED (load %.1f%% < %.1f%%)",
                    panel_id, avg_load, stop_pct,
                )

    async def _pick_backup(self, idle_panels: list[str], needed_kw: float = 0.0) -> str | None:
        """Select the best backup panel: maintenance skip, lowest lead_rotation_order, lowest priority, fewest run hours."""
        if not idle_panels:
            return None

        candidates = []
        for pid in idle_panels:
            state = self._gateway.states.get(pid)
            if not state or not getattr(state, "is_data_fresh", True):
                continue
                
            priority = 100
            lead_rotation_order = 100
            rated_kw = 0.0
            maintenance_mode = False

            if getattr(self, "_get_panel", None):
                panel_info = await self._get_panel(pid)
                if panel_info:
                    maintenance_mode = panel_info.get("maintenance_mode", False)
                    priority = panel_info.get("priority", 100)
                    lead_rotation_order = panel_info.get("lead_rotation_order", 100)
                    rated_kw = panel_info.get("rated_kw", 0.0)

            if maintenance_mode:
                continue

            candidates.append((pid, lead_rotation_order, priority, state.run_hours, rated_kw))

        if not candidates:
            return None

        # Sort by: lead_rotation_order, priority, then run hours
        candidates.sort(key=lambda c: (c[1], c[2], c[3]))
        
        if needed_kw > 0:
            # Try to find one that satisfies the capacity need
            capable = [c for c in candidates if c[4] >= needed_kw]
            if capable:
                return capable[0][0]

        # Fallback to the best one available even if it doesn't meet the full kW need
        return candidates[0][0]

    # ── Override Checks ───────────────────────────────────────────────

    async def _is_overridden(self, panel_id: str) -> bool:
        """Check if a panel has an active, non-expired override."""
        if not self._get_overrides:
            return False

        overrides = await self._get_overrides(panel_id)
        now = datetime.now(timezone.utc)

        for override in overrides:
            if override.get("is_active") and override.get("expires_at"):
                expires = override["expires_at"]
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires)
                if expires > now:
                    return True
        return False

    # ── Dynamic Schedule Updates ──────────────────────────────────────

    async def update_schedule(self, schedule: dict[str, Any]) -> None:
        """Add or update a single schedule entry."""
        schedule_id = schedule["id"]

        # Remove existing jobs for this schedule
        for suffix in ("_start", "_stop"):
            job_id = self._schedule_jobs.pop(f"{schedule_id}{suffix}", None)
            if job_id:
                try:
                    self._scheduler.remove_job(job_id)
                except Exception:
                    pass

        if schedule.get("is_active", True):
            await self._add_schedule_jobs(schedule)

    async def remove_schedule(self, schedule_id: str) -> None:
        """Remove jobs for a deleted schedule."""
        for suffix in ("_start", "_stop"):
            job_id = self._schedule_jobs.pop(f"{schedule_id}{suffix}", None)
            if job_id:
                try:
                    self._scheduler.remove_job(job_id)
                except Exception:
                    pass

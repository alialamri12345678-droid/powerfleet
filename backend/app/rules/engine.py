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
        self._get_daily_priorities = None
        self._get_release_thresholds = None
        self._get_start_thresholds = None

    def set_data_accessors(
        self,
        get_schedules=None,
        get_schedule_exceptions=None,
        get_thresholds=None,
        get_overrides=None,
        get_site=None,
        get_threshold_state=None,
        get_panel=None,
        get_release_thresholds=None,
        get_start_thresholds=None,
    ):
        """Set the async functions used to read schedules/thresholds from DB."""
        self._get_schedules = get_schedules
        self._get_schedule_exceptions = get_schedule_exceptions
        self._get_thresholds = get_thresholds
        self._get_overrides = get_overrides
        self._get_site = get_site
        self._get_threshold_state = get_threshold_state
        self._get_panel = get_panel
        self._get_release_thresholds = get_release_thresholds
        self._get_start_thresholds = get_start_thresholds

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

        self._adopt_unmanaged_running_panels()
            
        self._scheduler.start()
        # Register threshold checker on every gateway poll
        self._gateway.on_state_update(self._on_panel_state_update)
        logger.info("Rules engine started, reconstructed %d threshold-started panels", len(self._threshold_started))

    def _adopt_unmanaged_running_panels(self) -> None:
        """Bring running, unscheduled units under threshold release control.

        This covers restarts and generator records recreated while the physical
        controller remains on. The dwell period begins now, so startup never
        causes an immediate stop. A persistent manual run should use an override.
        """
        now = datetime.now(timezone.utc)
        for panel_id, state in self._gateway.states.items():
            if not state.is_running or panel_id in self._threshold_started:
                continue
            if self._schedule_wants.get(panel_id) == "RUNNING":
                continue
            if self._fault_wants.get(panel_id) == "RUNNING":
                continue
            self._threshold_started[panel_id] = now
            self._threshold_wants[panel_id] = "RUNNING"
            logger.info(
                "Adopted running unscheduled panel %s for threshold release after dwell",
                panel_id,
            )

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        self._scheduler.shutdown(wait=False)
        logger.info("Rules engine stopped")

    def remove_panel(self, panel_id: str) -> None:
        """Forget all cached control intents for a decommissioned generator."""
        for state in (
            self._schedule_wants, self._threshold_started, self._threshold_wants,
            self._fault_started, self._fault_wants,
        ):
            state.pop(panel_id, None)

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
        
        # Remember which panels were previously wanted by schedule
        previously_wanted = set(self._schedule_wants.keys())
        
        # Clear schedule wants so we can re-evaluate from scratch
        self._schedule_wants.clear()

        # Get current time in UTC
        now_utc = datetime.now(timezone.utc)

        # Collect all panel IDs that appear in the new schedules
        new_scheduled_panels = set()

        for sched in schedules:
            if not sched.get("is_active", True):
                continue
            
            panel_id = sched["panel_id"]
            new_scheduled_panels.add(panel_id)
            
            await self._add_schedule_jobs(sched)
            
            # Immediately evaluate if we are currently inside the schedule window
            try:
                from zoneinfo import ZoneInfo
                site_tz = ZoneInfo(sched.get("timezone", "UTC"))
            except Exception:
                site_tz = timezone.utc
                
            now_local = now_utc.astimezone(site_tz)
            if now_local.weekday() == sched.get("day_of_week"):
                start_time = sched.get("start_time")
                end_time = sched.get("end_time")
                if start_time and end_time:
                    current_time_str = now_local.strftime("%H:%M")
                    if start_time <= current_time_str < end_time:
                        self._schedule_wants[panel_id] = "RUNNING"
        
        # Any panel that was previously wanted but is no longer scheduled at all
        # OR is scheduled but not in its active window → mark STOPPED
        for panel_id in new_scheduled_panels:
            if panel_id not in self._schedule_wants:
                self._schedule_wants[panel_id] = "STOPPED"
        
        # Panels that were previously scheduled but are completely removed
        for panel_id in previously_wanted:
            if panel_id not in new_scheduled_panels:
                self._schedule_wants[panel_id] = "STOPPED"
                        
        # Trigger reconciliation to apply immediate schedule intent
        await self._reconcile_fleet()

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
        sites_data = {}
        
        for pid, state in self._gateway.states.items():
            if not state.is_reachable:
                continue
                
            site_id = state.site_id
            if not site_id:
                continue
                
            if site_id not in sites_data:
                sites_data[site_id] = {
                    "idle_panels": [],
                    "critical_faults": 0,
                    "overloads": 0
                }
                
            if state.engine_status == "stopped" and not state.active_alarms:
                sites_data[site_id]["idle_panels"].append(pid)
                
            # If a panel wants to run (via schedule or threshold) but is faulted
            wants_to_run = self._schedule_wants.get(pid) == "RUNNING" or self._threshold_wants.get(pid) == "RUNNING"
            is_faulted = "fail_to_start" in state.active_alarms or "emergency_stop" in state.active_alarms
            
            if wants_to_run and is_faulted:
                sites_data[site_id]["critical_faults"] += 1
                
            if state.is_running and "overload_alarm" in state.active_alarms:
                sites_data[site_id]["overloads"] += 1
                
        for site_id, data in sites_data.items():
            required_replacements = data["critical_faults"] + data["overloads"]
            
            # Find currently running replacements for this site
            site_replacements = [
                pid for pid in self._fault_started.keys() 
                if self._gateway.states.get(pid) and self._gateway.states[pid].site_id == site_id
            ]
            current_replacements = len(site_replacements)
            idle_panels = data["idle_panels"]
            
            # Start new replacements if needed
            while current_replacements < required_replacements and idle_panels:
                best_backup = await self._pick_backup(idle_panels)
                if not best_backup:
                    break
                    
                idle_panels.remove(best_backup)
                self._fault_started[best_backup] = datetime.now(timezone.utc)
                self._fault_wants[best_backup] = "RUNNING"
                current_replacements += 1
                site_replacements.append(best_backup)
                logger.warning("Fault response [site %s]: starting replacement unit %s", site_id[:8], best_backup)
                
            # Stop replacements if faults are cleared
            if current_replacements > required_replacements:
                for pid in list(site_replacements):
                    if current_replacements <= required_replacements:
                        break
                    self._fault_wants[pid] = "STOPPED"
                    del self._fault_started[pid]
                    current_replacements -= 1
                    logger.info("Fault response [site %s]: stopping unneeded replacement unit %s", site_id[:8], pid)

    async def _evaluate_single_threshold(self, threshold: dict[str, Any]) -> None:
        """Evaluate a single threshold rule.
        
        START: Triggers when ANY individual running unit's load >= start_pct.
        STOP/RELEASE: Triggers when total facility load % drops below the per-backup release threshold.
        Release order: highest priority number (lowest priority) released first.
        """
        site_id = threshold["site_id"]
        start_pct = float(threshold["start_pct"])
        dwell_seconds = threshold["dwell_seconds"]

        # Collect running and idle panels for this site
        running_panels: list[str] = []
        idle_panels: list[str] = []
        max_unit_load = 0.0
        total_load_kw = 0.0
        total_rated_kw = 0.0
        running_capacity_kw = 0.0
        panel_capacities = {}

        for pid, state in self._gateway.states.items():
            if state.site_id != site_id:
                continue
            if not state.is_reachable:
                continue
                
            # Always add to total site capacity regardless of running state
            panel_kw = 0.0
            if getattr(self, "_get_panel", None):
                panel_info = await self._get_panel(pid)
                if panel_info:
                    panel_kw = float(panel_info.get("rated_kw", 0.0) or 0.0)
            
            panel_capacities[pid] = panel_kw
            total_rated_kw += panel_kw

            if state.is_running:
                running_panels.append(pid)
                total_load_kw += state.load_kw
                running_capacity_kw += panel_kw
                unit_load_pct = state.load_kw_percent
                if unit_load_pct > max_unit_load:
                    max_unit_load = unit_load_pct
            elif state.engine_status == "stopped":
                idle_panels.append(pid)

        # Remove any panels from _threshold_started that are no longer running
        for pid in list(self._threshold_started.keys()):
            p_state = self._gateway.states.get(pid)
            if not p_state or not p_state.is_running:
                del self._threshold_started[pid]

        if not running_panels:
            return

        # Calculate total facility load percentage
        total_facility_load_pct = (total_load_kw / total_rated_kw * 100.0) if total_rated_kw > 0 else 0.0
        avg_load = sum(self._gateway.states[p].load_kw_percent for p in running_panels) / len(running_panels)

        logger.info(
            "Threshold eval [site %s]: %d running, %d idle, max_unit=%.1f%%, total_facility=%.1f%%, start_pct=%.1f%%",
            site_id[:8], len(running_panels), len(idle_panels), max_unit_load, total_facility_load_pct, start_pct,
        )

        # ── START LOGIC: total facility load vs per-backup start thresholds ──
        if idle_panels:
            best_backup = await self._pick_backup(idle_panels)
            if best_backup:
                start_pct_for_backup = float(threshold.get("start_pct", 70))
                if getattr(self, "_get_start_thresholds", None):
                    sts = await self._get_start_thresholds(site_id)
                    for st in sts:
                        if st["panel_id"] == best_backup:
                            start_pct_for_backup = float(st["start_pct"])
                            break

                if total_facility_load_pct >= start_pct_for_backup:
                    site_info = await self._get_site(site_id) if self._get_site else None
                    max_parallel = site_info.get("max_parallel_units") if site_info else None

                    if max_parallel and len(running_panels) >= max_parallel:
                        logger.info(
                            "Threshold eval [site %s]: Total load %.1f%% >= %.1f%% but max parallel units (%d) reached",
                            site_id[:8], total_facility_load_pct, start_pct_for_backup, max_parallel,
                        )
                    else:
                        # Prevent cascade starting: Cooldown before starting another backup for this site
                        recent_start = False
                        now_utc = datetime.now(timezone.utc)
                        for started_pid, started_at in self._threshold_started.items():
                            p_state = self._gateway.states.get(started_pid)
                            if p_state and p_state.site_id == site_id:
                                if started_at.tzinfo is None:
                                    started_at = started_at.replace(tzinfo=timezone.utc)
                                if (now_utc - started_at).total_seconds() < 30.0:
                                    recent_start = True
                                    break
                        
                        if recent_start:
                            logger.debug("Threshold eval [site %s]: Delaying start due to recent backup start (prevent cascade)", site_id[:8])
                        else:
                            if best_backup in self._threshold_started:
                                best_state = self._gateway.states.get(best_backup)
                                if best_state and best_state.is_running:
                                    pass
                                else:
                                    del self._threshold_started[best_backup]
                            
                            self._threshold_started[best_backup] = datetime.now(timezone.utc)
                            self._threshold_wants[best_backup] = "RUNNING"
                            logger.info(
                                "Threshold rule [site %s]: starting backup %s (total facility load %.1f%% >= start %.1f%%)",
                                site_id[:8], best_backup, total_facility_load_pct, start_pct_for_backup,
                            )
                            return # Block release logic since we just started a unit

        # ── RELEASE LOGIC: total facility load vs per-backup release thresholds ──
        if self._threshold_started:
            # Get per-backup release thresholds
            release_thresholds = {}
            if getattr(self, "_get_release_thresholds", None):
                rts = await self._get_release_thresholds(site_id)
                for rt in rts:
                    release_thresholds[rt["panel_id"]] = {
                        "release_pct": float(rt["release_pct"]),
                        "priority_order": rt["priority_order"],
                    }

            # Check each threshold-started backup for release eligibility
            # Release in reverse priority order (highest priority_order first = lowest priority backup)
            started_backups = list(self._threshold_started.items())
            # Sort by priority_order descending (release lowest priority backups first)
            started_backups.sort(
                key=lambda x: release_thresholds.get(x[0], {}).get("priority_order", 999),
                reverse=True,
            )

            for panel_id, started_at in started_backups:
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                if elapsed < dwell_seconds:
                    logger.debug(
                        "Dwell time not met for %s: %.0f/%ds",
                        panel_id, elapsed, dwell_seconds,
                    )
                    continue

                rt_info = release_thresholds.get(panel_id)
                release_pct = rt_info["release_pct"] if rt_info else float(threshold.get("stop_pct", 50))

                if total_facility_load_pct <= release_pct:
                    self._threshold_wants[panel_id] = "STOPPED"
                    logger.info(
                        "Threshold rule [site %s]: requesting release of backup %s (total facility load %.1f%% <= release %.1f%%)",
                        site_id[:8], panel_id, total_facility_load_pct, release_pct
                    )

    async def _pick_backup(self, idle_panels: list[str], needed_kw: float = 0.0) -> str | None:
        """Select the best backup panel: maintenance skip, no alarms, highest priority (lowest number), fewest run hours."""
        if not idle_panels:
            return None

        candidates = []
        for pid in idle_panels:
            state = self._gateway.states.get(pid)
            if not state:
                continue
            # Skip candidates with active alarms
            if state.active_alarms:
                continue
                
            priority = 100
            lead_rotation_order = 100
            rated_kw = 0.0
            maintenance_mode = False

            if getattr(self, "_get_panel", None):
                panel_info = await self._get_panel(pid)
                if panel_info:
                    maintenance_mode = panel_info.get("maintenance_mode", False)
                    lead_rotation_order = panel_info.get("lead_rotation_order", 100)
                    priority = panel_info.get("priority", 100)
                    rated_kw = float(panel_info.get("rated_kw", 0.0) or 0.0)
                    
            if maintenance_mode:
                continue
                
            candidates.append([pid, lead_rotation_order, priority, state.run_hours, rated_kw])
            
        # Overwrite priority with daily priorities if available
        if getattr(self, "_get_daily_priorities", None):
            current_day = datetime.now(timezone.utc).weekday()
            daily_priorities = await self._get_daily_priorities()
            priority_map = {
                dp.get("panel_id"): dp.get("priority")
                for dp in daily_priorities
                if dp.get("day_of_week") == current_day and dp.get("priority") is not None
            }
            for candidate in candidates:
                pid = candidate[0]
                if pid in priority_map:
                    candidate[2] = priority_map[pid]

        if not candidates:
            return None

        # Sort strictly by priority (1 is first, then 2, etc.), then run hours
        candidates.sort(key=lambda c: (c[2], c[3]))
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

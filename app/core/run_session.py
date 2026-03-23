"""RunSession: manages one active traffic generation run."""
from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from app.core.config_manager import ConfigManager
from app.core.state_machine import StateMachine
from app.engine.action_executor import ActionExecutor
from app.engine.behavior_engine import BehaviorEngine
from app.engine.browser_manager import BrowserManager
from app.logging.loggers import EventLogger, ScreenshotManager, SummaryLogger
from app.models.models import (
    ActionResult, AppState, BehaviorIntensity, FeatureFlags,
    Persona, PrivateApp, ResultType, RunMode, RuntimeStatus,
)


class RunSession:
    def __init__(
        self,
        persona: Persona,
        run_mode: RunMode,
        intensity: BehaviorIntensity,
        flags: FeatureFlags,
        private_apps: list[PrivateApp],
        config: ConfigManager,
        status_callback: Optional[Callable[[RuntimeStatus], None]] = None,
    ):
        self.persona = persona
        self.run_mode = run_mode
        self.intensity = intensity
        self.flags = flags
        self.private_apps = private_apps
        self.config = config
        self._status_callback = status_callback

        self.sm = StateMachine()
        self.status = RuntimeStatus(persona_name=persona.display_name)
        self._stop_event = asyncio.Event()
        self._domains: set[str] = set()

        root = config.root
        self.event_logger = EventLogger(root / "logs")
        self.summary_logger = SummaryLogger(root / "logs")
        self.screenshot_mgr = ScreenshotManager(root / "screenshots")

    # ── Public API (called from thread) ───────────────────────────────

    def request_stop(self) -> None:
        self._stop_event.set()

    # ── Main loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        if not self.sm.transition(AppState.STARTING):
            return
        self._update_status(state=AppState.STARTING, action="Launching browser...")

        browser = BrowserManager(timeout_ms=self.config.get("page_timeout_ms", 30000))
        max_actions_before_restart = self.config.get("max_actions_before_browser_restart", 100)
        relaunch_retries = self.config.get("browser_relaunch_retry_count", 3)

        try:
            await browser.launch()
        except Exception as exc:
            self.event_logger.log_error(f"Browser launch failed: {exc}", exc)
            self.sm.force(AppState.ERROR)
            self._update_status(state=AppState.ERROR, action=f"Launch failed: {exc}")
            return

        if not self.sm.transition(AppState.RUNNING):
            await browser.close()
            return

        self._update_status(state=AppState.RUNNING, action="Running")
        start_time = time.monotonic()

        behavior = BehaviorEngine(
            persona=self.persona,
            run_mode=self.run_mode,
            intensity=self.intensity,
            flags=self.flags,
            private_apps=self.private_apps,
            safe_prompts=self.config.safe_prompts,
            malware_tests=self.config.malware_tests,
        )
        executor = ActionExecutor(browser, self.persona.behavior, self.screenshot_mgr)

        action_count_since_restart = 0

        while not self._stop_event.is_set():
            try:
                plan = behavior.build_action_plan()
                self._update_status(
                    action=f"{plan.action_label} → {plan.target_url[:60]}",
                    current_url=plan.target_url,
                )

                result = await executor.execute(plan)

                # Track
                self.status.actions_completed += 1
                action_count_since_restart += 1
                if result.result_type == ResultType.BLOCKED:
                    self.status.blocked_count += 1
                elif result.result_type == ResultType.WARNING:
                    self.status.warning_count += 1
                elif result.result_type in (ResultType.FAILED, ResultType.LOAD_FAILURE,
                                             ResultType.TIMEOUT, ResultType.DNS_FAILURE):
                    self.status.failure_count += 1

                # Domain tracking
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(result.final_url).hostname
                    if domain:
                        self._domains.add(domain)
                except Exception:
                    pass

                self.event_logger.log_event(self.persona.name, result)

                self._update_status(
                    current_url=result.final_url,
                    last_result=result.result_type.value,
                    elapsed=time.monotonic() - start_time,
                )

                # Browser restart
                if action_count_since_restart >= max_actions_before_restart:
                    self._update_status(action="Restarting browser...")
                    await browser.close_extra_tabs()
                    await browser.restart()
                    self.status.browser_restart_count += 1
                    action_count_since_restart = 0

            except Exception as exc:
                self.event_logger.log_error(f"Action loop error: {exc}", exc)
                # Try to recover
                if self.sm.transition(AppState.RECOVERING):
                    self._update_status(state=AppState.RECOVERING, action="Recovering browser...")
                    recovered = False
                    for attempt in range(relaunch_retries):
                        try:
                            await browser.restart()
                            recovered = True
                            break
                        except Exception:
                            await asyncio.sleep(2)
                    if recovered:
                        self.sm.transition(AppState.RUNNING)
                        self._update_status(state=AppState.RUNNING, action="Recovered")
                        action_count_since_restart = 0
                    else:
                        self.sm.force(AppState.ERROR)
                        self._update_status(state=AppState.ERROR, action="Unrecoverable browser failure")
                        break

        # ── Cleanup ───────────────────────────────────────────────────
        self.sm.transition(AppState.STOPPING)
        self._update_status(state=AppState.STOPPING, action="Stopping...")

        self.summary_logger.write_summary(self.status, self._domains)
        await browser.close()

        self.sm.transition(AppState.STOPPED)
        self._update_status(state=AppState.STOPPED, action="Stopped")

    # ── Status helper ─────────────────────────────────────────────────

    def _update_status(
        self,
        state: Optional[AppState] = None,
        action: str = "",
        current_url: str = "",
        last_result: str = "",
        elapsed: float = 0.0,
    ) -> None:
        if state:
            self.status.state = state
        if action:
            self.status.current_action = action
        if current_url:
            self.status.current_url = current_url
        if last_result:
            self.status.last_result = last_result
        if elapsed:
            self.status.elapsed_seconds = elapsed

        if self._status_callback:
            try:
                self._status_callback(self.status)
            except Exception:
                pass

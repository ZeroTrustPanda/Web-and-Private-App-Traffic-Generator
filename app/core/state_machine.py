"""Simple state machine for the run lifecycle."""
from __future__ import annotations

import threading
from app.models.models import AppState

_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.IDLE:       {AppState.STARTING},
    AppState.STARTING:   {AppState.RUNNING, AppState.ERROR},
    AppState.RUNNING:    {AppState.STOPPING, AppState.RECOVERING, AppState.ERROR},
    AppState.STOPPING:   {AppState.STOPPED, AppState.ERROR},
    AppState.STOPPED:    {AppState.IDLE},
    AppState.ERROR:      {AppState.IDLE},
    AppState.RECOVERING: {AppState.RUNNING, AppState.ERROR},
}


class StateMachine:
    def __init__(self) -> None:
        self._state = AppState.IDLE
        self._lock = threading.Lock()

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    def transition(self, target: AppState) -> bool:
        with self._lock:
            allowed = _TRANSITIONS.get(self._state, set())
            if target in allowed:
                self._state = target
                return True
            return False

    def force(self, target: AppState) -> None:
        with self._lock:
            self._state = target

    def is_running(self) -> bool:
        return self.state == AppState.RUNNING

    def reset(self) -> None:
        self.force(AppState.IDLE)

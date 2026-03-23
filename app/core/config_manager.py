"""Loads and manages all local configuration files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.models import Persona, PrivateApp
from app.utils.helpers import load_json, save_json, base_dir, ensure_dir


_DEFAULT_GLOBAL = {
    "page_timeout_ms": 30000,
    "navigation_retry_count": 1,
    "browser_relaunch_retry_count": 3,
    "max_actions_before_browser_restart": 100,
    "gui_refresh_interval_ms": 1000,
    "status_update_interval_seconds": 5,
    "default_run_mode": "mixed_realistic",
    "default_behavior_intensity": "medium",
}


class ConfigManager:
    def __init__(self, root: Path | None = None):
        self.root = root or base_dir()
        self.config_dir = self.root / "config"
        self.personas_dir = self.config_dir / "personas"
        self.global_settings: dict[str, Any] = {}
        self.personas: dict[str, Persona] = {}
        self.private_apps: list[PrivateApp] = []
        self.safe_prompts: list[dict] = []
        self.malware_tests: list[dict] = []

    # ── Bootstrap ─────────────────────────────────────────────────────

    def load_all(self) -> None:
        ensure_dir(self.config_dir)
        ensure_dir(self.personas_dir)
        ensure_dir(self.root / "logs")
        ensure_dir(self.root / "screenshots")
        self._load_global()
        self._load_personas()
        self._load_private_apps()
        self._load_safe_prompts()
        self._load_malware_tests()

    # ── Global settings ───────────────────────────────────────────────

    def _load_global(self) -> None:
        path = self.config_dir / "global_settings.json"
        if path.exists():
            self.global_settings = load_json(path)
        else:
            self.global_settings = dict(_DEFAULT_GLOBAL)
            save_json(path, self.global_settings)

    def get(self, key: str, default: Any = None) -> Any:
        return self.global_settings.get(key, default)

    # ── Personas ──────────────────────────────────────────────────────

    def _load_personas(self) -> None:
        self.personas.clear()
        for p in sorted(self.personas_dir.glob("*.json")):
            try:
                data = load_json(p)
                persona = Persona.from_dict(data)
                self.personas[persona.name] = persona
            except Exception as exc:
                print(f"[ConfigManager] Failed to load persona {p.name}: {exc}")

    def persona_names(self) -> list[str]:
        return list(self.personas.keys())

    def get_persona(self, name: str) -> Persona | None:
        return self.personas.get(name)

    # ── Private apps ──────────────────────────────────────────────────

    def _load_private_apps(self) -> None:
        path = self.config_dir / "private_apps.json"
        if path.exists():
            raw = load_json(path)
            self.private_apps = [PrivateApp(**item) for item in raw]
        else:
            self.private_apps = []
            save_json(path, [])

    def save_private_apps(self) -> None:
        path = self.config_dir / "private_apps.json"
        from dataclasses import asdict
        save_json(path, [asdict(a) for a in self.private_apps])

    # ── Safe prompts ──────────────────────────────────────────────────

    def _load_safe_prompts(self) -> None:
        path = self.config_dir / "safe_prompts.json"
        if path.exists():
            self.safe_prompts = load_json(path)
        else:
            self.safe_prompts = []
            save_json(path, [])

    def prompts_for_persona(self, persona_name: str) -> list[dict]:
        return [p for p in self.safe_prompts if p.get("persona") == persona_name]

    # ── Malware tests ─────────────────────────────────────────────────

    def _load_malware_tests(self) -> None:
        path = self.config_dir / "malware_tests.json"
        if path.exists():
            self.malware_tests = load_json(path)
        else:
            self.malware_tests = []
            save_json(path, [])

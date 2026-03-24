"""Loads and manages all local configuration files."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
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

# Valid site categories that map to persona JSON keys
SITE_CATEGORIES = [
    "normal_sites",
    "restricted_geo_sites",
    "tls_test_sites",
    "phish_test_sites",
    "ai_sites",
    "search_queries",
]


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

    def save_persona(self, persona: Persona) -> None:
        """Save a persona back to its JSON file."""
        path = self.personas_dir / f"{persona.name}.json"
        data = {
            "name": persona.name,
            "display_name": persona.display_name,
            "description": persona.description,
            "weights": persona.weights,
            "nested_violation_weights": persona.nested_violation_weights,
            "behavior": {
                "tab_open_chance": persona.behavior.tab_open_chance,
                "external_link_chance": persona.behavior.external_link_chance,
                "search_engine_chance": persona.behavior.search_engine_chance,
                "revisit_chance": persona.behavior.revisit_chance,
                "max_click_depth": persona.behavior.max_click_depth,
                "dwell_short_seconds": persona.behavior.dwell_short_seconds,
                "dwell_medium_seconds": persona.behavior.dwell_medium_seconds,
                "dwell_long_seconds": persona.behavior.dwell_long_seconds,
            },
            "normal_sites": persona.normal_sites,
            "restricted_geo_sites": persona.restricted_geo_sites,
            "tls_test_sites": persona.tls_test_sites,
            "phish_test_sites": persona.phish_test_sites,
            "ai_sites": persona.ai_sites,
            "search_queries": persona.search_queries,
            "private_app_preferences": persona.private_app_preferences,
            "private_app_denied_tests": persona.private_app_denied_tests,
        }
        save_json(path, data)
        self.personas[persona.name] = persona

    # ── Private apps ──────────────────────────────────────────────────

    def _load_private_apps(self) -> None:
        path = self.config_dir / "private_apps.json"
        if path.exists():
            raw = load_json(path)
            self.private_apps = []
            for item in raw:
                # Handle v1 configs that lack 'port'
                if "port" not in item:
                    item["port"] = 443
                self.private_apps.append(PrivateApp(**item))
        else:
            self.private_apps = []
            save_json(path, [])

    def save_private_apps(self) -> None:
        path = self.config_dir / "private_apps.json"
        save_json(path, [asdict(a) for a in self.private_apps])

    # ── CSV Import ────────────────────────────────────────────────────

    def import_sites_csv(
        self,
        csv_path: str | Path,
        persona_name: str,
        category: str,
    ) -> tuple[int, int, list[str]]:
        """Import sites from a CSV into a persona's site list.

        The CSV should have a column named 'url' (or 'site' or 'URL').
        For restricted_geo_sites it should also have 'country_code' and 'label'.
        For search_queries the column should be 'query' (or 'url' works too).

        Returns (added_count, skipped_duplicates, errors).
        """
        persona = self.personas.get(persona_name)
        if not persona:
            return 0, 0, [f"Persona '{persona_name}' not found"]
        if category not in SITE_CATEGORIES:
            return 0, 0, [f"Invalid category '{category}'"]

        current_list = getattr(persona, category)
        errors: list[str] = []
        added = 0
        skipped = 0

        # Build a set of existing values for dedup
        if category == "restricted_geo_sites":
            existing = {item.get("url", "") if isinstance(item, dict) else item for item in current_list}
        else:
            existing = set(current_list)

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                # Normalise column names to lowercase
                if reader.fieldnames:
                    reader.fieldnames = [n.strip().lower() for n in reader.fieldnames]

                for row_num, row in enumerate(reader, start=2):
                    row = {k.strip().lower(): v.strip() for k, v in row.items() if k}

                    if category == "search_queries":
                        value = row.get("query") or row.get("url") or row.get("site") or ""
                        if not value:
                            errors.append(f"Row {row_num}: empty query")
                            continue
                        if value in existing:
                            skipped += 1
                            continue
                        current_list.append(value)
                        existing.add(value)
                        added += 1

                    elif category == "restricted_geo_sites":
                        url = row.get("url") or row.get("site") or ""
                        cc = row.get("country_code") or row.get("cc") or ""
                        label = row.get("label") or row.get("description") or ""
                        if not url:
                            errors.append(f"Row {row_num}: empty url")
                            continue
                        if url in existing:
                            skipped += 1
                            continue
                        current_list.append({"url": url, "country_code": cc, "label": label})
                        existing.add(url)
                        added += 1

                    else:
                        # normal_sites, tls_test_sites, phish_test_sites, ai_sites
                        url = row.get("url") or row.get("site") or ""
                        if not url:
                            errors.append(f"Row {row_num}: empty url")
                            continue
                        if url in existing:
                            skipped += 1
                            continue
                        current_list.append(url)
                        existing.add(url)
                        added += 1

        except Exception as exc:
            errors.append(f"CSV read error: {exc}")

        # Persist
        if added > 0:
            self.save_persona(persona)

        return added, skipped, errors

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

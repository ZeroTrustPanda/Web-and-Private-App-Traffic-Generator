"""Logging: event JSONL, summary, errors, screenshots."""
from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import asdict
from pathlib import Path

from app.models.models import ActionResult, RuntimeStatus
from app.utils.helpers import utc_now_iso, utc_now_file_stamp, append_jsonl, ensure_dir


class EventLogger:
    def __init__(self, log_dir: Path):
        self.log_dir = ensure_dir(log_dir)
        stamp = utc_now_file_stamp()
        self.event_path = self.log_dir / f"events_{stamp}.jsonl"
        self.error_path = self.log_dir / "errors.log"

    def log_event(self, persona: str, result: ActionResult) -> None:
        plan = result.action_plan
        record = {
            "timestamp": utc_now_iso(),
            "persona": persona,
            "behavior_type": plan.behavior_type.value if plan else "",
            "category": plan.category if plan else "",
            "action": plan.action_label if plan else "",
            "url": result.final_url,
            "result": result.result_type.value,
            "page_title": result.page_title,
            "latency_ms": result.latency_ms,
            "click_depth": result.click_depth,
            "screenshot_path": result.screenshot_path,
            "notes": result.notes,
        }
        append_jsonl(self.event_path, record)

    def log_error(self, msg: str, exc: Exception | None = None) -> None:
        ts = utc_now_iso()
        with open(self.error_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            if exc:
                f.write(traceback.format_exc() + "\n")


class SummaryLogger:
    def __init__(self, log_dir: Path):
        self.log_dir = ensure_dir(log_dir)
        stamp = utc_now_file_stamp()
        self.summary_path = self.log_dir / f"summary_{stamp}.json"

    def write_summary(self, status: RuntimeStatus, domains: set[str]) -> None:
        from dataclasses import asdict
        data = asdict(status)
        data["state"] = status.state.value
        data["unique_domains"] = len(domains)
        data["timestamp"] = utc_now_iso()
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


class ScreenshotManager:
    def __init__(self, screenshot_dir: Path):
        self.screenshot_dir = ensure_dir(screenshot_dir)

    def capture_path(self, label: str) -> str:
        stamp = utc_now_file_stamp()
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label[:40])
        return str(self.screenshot_dir / f"{stamp}_{safe}.png")

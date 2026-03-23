"""Utility helpers for time, randomness, files, and validation."""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Time utils ────────────────────────────────────────────────────────────

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


# ── Random utils ──────────────────────────────────────────────────────────

def weighted_choice(options: list[str], weights: list[int | float]) -> str:
    """Pick one option from a weighted list."""
    total = sum(weights)
    if total == 0:
        return random.choice(options)
    r = random.uniform(0, total)
    cumulative = 0.0
    for opt, w in zip(options, weights):
        cumulative += w
        if r <= cumulative:
            return opt
    return options[-1]


def rand_range(low: int, high: int) -> int:
    return random.randint(low, high)


def rand_float_range(low: float, high: float) -> float:
    return random.uniform(low, high)


def chance(probability: float) -> bool:
    return random.random() < probability


# ── File utils ────────────────────────────────────────────────────────────

def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Any, indent: int = 2) -> None:
    ensure_dir(Path(path).parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def append_jsonl(path: str | Path, record: dict) -> None:
    ensure_dir(Path(path).parent)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ── Validation ────────────────────────────────────────────────────────────

def is_valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def is_valid_fqdn(fqdn: str) -> bool:
    if not fqdn or " " in fqdn:
        return False
    parts = fqdn.split(".")
    return len(parts) >= 2 and all(p for p in parts)


def base_dir() -> Path:
    """Return the traffic_generator root directory."""
    return Path(__file__).resolve().parent.parent.parent

"""Data models used throughout the application."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Enums ─────────────────────────────────────────────────────────────────

class AppState(Enum):
    IDLE = "Idle"
    STARTING = "Starting"
    RUNNING = "Running"
    STOPPING = "Stopping"
    STOPPED = "Stopped"
    ERROR = "Error"
    RECOVERING = "Recovering"


class RunMode(Enum):
    MIXED_REALISTIC = "Mixed Realistic"
    PUBLIC_ONLY = "Public Only"
    PRIVATE_APP_FOCUS = "Private App Focus"
    POLICY_CHALLENGE = "Policy Challenge Focus"


class BehaviorIntensity(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    AGGRESSIVE = "Aggressive"


class BehaviorType(Enum):
    NORMAL = "normal"
    GRAY_AREA = "gray_area"
    VIOLATION = "violation"


class ViolationCategory(Enum):
    AI = "ai"
    RESTRICTED_GEO = "restricted_geo"
    TLS = "tls"
    PHISH = "phish"
    MALWARE = "malware"
    DENIED_PRIVATE_APP = "denied_private_app"


class ResultType(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    WARNING = "warning"
    REDIRECTED = "redirected"
    FAILED = "failed"
    TIMEOUT = "timeout"
    DNS_FAILURE = "dns_failure"
    LOAD_FAILURE = "load_failure"
    DOWNLOAD_ALLOWED = "download_allowed"
    DOWNLOAD_BLOCKED = "download_blocked"


# ── Feature Flags ─────────────────────────────────────────────────────────

@dataclass
class FeatureFlags:
    enable_ai_tests: bool = True
    enable_restricted_geo_tests: bool = True
    enable_tls_tests: bool = True
    enable_phish_tests: bool = True
    enable_malware_tests: bool = True
    enable_private_app_tests: bool = True


# ── Private App ───────────────────────────────────────────────────────────

@dataclass
class PrivateApp:
    enabled: bool = True
    name: str = ""
    fqdn: str = ""
    port: int = 443
    landing_path: str = "/"
    expected_title_substring: str = ""
    expected_selector: str = "body"
    allowed_personas: list[str] = field(default_factory=list)
    weight: int = 10

    def url(self) -> str:
        path = self.landing_path if self.landing_path.startswith("/") else f"/{self.landing_path}"
        scheme = "http" if self.port == 80 else "https"
        if (scheme == "https" and self.port == 443) or (scheme == "http" and self.port == 80):
            return f"{scheme}://{self.fqdn}{path}"
        return f"{scheme}://{self.fqdn}:{self.port}{path}"


# ── Persona ───────────────────────────────────────────────────────────────

@dataclass
class PersonaBehavior:
    tab_open_chance: float = 0.15
    external_link_chance: float = 0.30
    search_engine_chance: float = 0.20
    revisit_chance: float = 0.12
    max_click_depth: int = 3
    dwell_short_seconds: list[int] = field(default_factory=lambda: [4, 12])
    dwell_medium_seconds: list[int] = field(default_factory=lambda: [15, 45])
    dwell_long_seconds: list[int] = field(default_factory=lambda: [45, 120])


@dataclass
class Persona:
    name: str = ""
    display_name: str = ""
    description: str = ""
    weights: dict[str, int] = field(default_factory=lambda: {"normal": 75, "gray_area": 15, "violation": 10})
    nested_violation_weights: dict[str, int] = field(default_factory=lambda: {
        "ai": 35, "restricted_geo": 25, "phish": 15, "tls": 15, "malware": 10
    })
    behavior: PersonaBehavior = field(default_factory=PersonaBehavior)
    normal_sites: list[str] = field(default_factory=list)
    restricted_geo_sites: list[dict] = field(default_factory=list)
    tls_test_sites: list[str] = field(default_factory=list)
    phish_test_sites: list[str] = field(default_factory=list)
    ai_sites: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    private_app_preferences: list[str] = field(default_factory=list)
    private_app_denied_tests: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Persona":
        beh = d.get("behavior", {})
        return cls(
            name=d.get("name", ""),
            display_name=d.get("display_name", ""),
            description=d.get("description", ""),
            weights=d.get("weights", cls.__dataclass_fields__["weights"].default_factory()),
            nested_violation_weights=d.get("nested_violation_weights",
                                           cls.__dataclass_fields__["nested_violation_weights"].default_factory()),
            behavior=PersonaBehavior(**beh) if beh else PersonaBehavior(),
            normal_sites=d.get("normal_sites", []),
            restricted_geo_sites=d.get("restricted_geo_sites", []),
            tls_test_sites=d.get("tls_test_sites", []),
            phish_test_sites=d.get("phish_test_sites", []),
            ai_sites=d.get("ai_sites", []),
            search_queries=d.get("search_queries", []),
            private_app_preferences=d.get("private_app_preferences", []),
            private_app_denied_tests=d.get("private_app_denied_tests", []),
        )


# ── Action / Result ───────────────────────────────────────────────────────

@dataclass
class ActionPlan:
    behavior_type: BehaviorType = BehaviorType.NORMAL
    category: str = "normal"
    target_url: str = ""
    max_depth: int = 2
    action_label: str = ""
    is_private_app: bool = False
    private_app: Optional[PrivateApp] = None
    search_query: Optional[str] = None
    prompt_text: Optional[str] = None


@dataclass
class ActionResult:
    action_plan: Optional[ActionPlan] = None
    result_type: ResultType = ResultType.ALLOWED
    final_url: str = ""
    page_title: str = ""
    latency_ms: int = 0
    click_depth: int = 0
    notes: str = ""
    requires_screenshot: bool = False
    screenshot_path: Optional[str] = None


# ── Runtime Status ────────────────────────────────────────────────────────

@dataclass
class RuntimeStatus:
    state: AppState = AppState.IDLE
    persona_name: str = ""
    current_url: str = ""
    current_action: str = ""
    last_result: str = ""
    actions_completed: int = 0
    blocked_count: int = 0
    warning_count: int = 0
    failure_count: int = 0
    elapsed_seconds: float = 0.0
    browser_restart_count: int = 0

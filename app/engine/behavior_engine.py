"""Behavior engine: selects next action category, target, and builds action plans."""
from __future__ import annotations

import random
from typing import Optional

from app.models.models import (
    ActionPlan, BehaviorIntensity, BehaviorType, FeatureFlags,
    Persona, PrivateApp, RunMode, ViolationCategory,
)
from app.utils.helpers import weighted_choice, chance


# Intensity → how often challenges appear (1-in-N actions)
_CHALLENGE_FREQ = {
    BehaviorIntensity.LOW: (20, 30),
    BehaviorIntensity.MEDIUM: (8, 12),
    BehaviorIntensity.AGGRESSIVE: (4, 6),
}


class BehaviorEngine:
    def __init__(
        self,
        persona: Persona,
        run_mode: RunMode,
        intensity: BehaviorIntensity,
        flags: FeatureFlags,
        private_apps: list[PrivateApp],
        safe_prompts: list[dict],
        malware_tests: list[dict],
    ):
        self.persona = persona
        self.run_mode = run_mode
        self.intensity = intensity
        self.flags = flags
        self.private_apps = private_apps
        self.safe_prompts = safe_prompts
        self.malware_tests = malware_tests
        self._action_counter = 0
        self._visited_urls: list[str] = []

    # ── Top-level selection ───────────────────────────────────────────

    def select_behavior_type(self) -> BehaviorType:
        self._action_counter += 1

        if self.run_mode == RunMode.PUBLIC_ONLY:
            return BehaviorType.NORMAL

        if self.run_mode == RunMode.POLICY_CHALLENGE:
            # mostly violations
            return random.choices(
                [BehaviorType.VIOLATION, BehaviorType.NORMAL],
                weights=[80, 20],
            )[0]

        # Mixed / Private App Focus
        w = self.persona.weights
        lo, hi = _CHALLENGE_FREQ[self.intensity]
        challenge_every = random.randint(lo, hi)

        if self._action_counter % challenge_every == 0:
            return random.choices(
                [BehaviorType.GRAY_AREA, BehaviorType.VIOLATION],
                weights=[w.get("gray_area", 15), w.get("violation", 10)],
            )[0]

        if self.run_mode == RunMode.PRIVATE_APP_FOCUS and self.flags.enable_private_app_tests:
            if chance(0.4):
                return BehaviorType.NORMAL  # private app is handled as normal for allowed
            return BehaviorType.NORMAL

        return BehaviorType.NORMAL

    # ── Category within violation ─────────────────────────────────────

    def select_violation_category(self) -> Optional[ViolationCategory]:
        nw = self.persona.nested_violation_weights
        options = []
        weights = []

        if self.flags.enable_ai_tests and nw.get("ai", 0) > 0:
            options.append(ViolationCategory.AI); weights.append(nw["ai"])
        if self.flags.enable_restricted_geo_tests and nw.get("restricted_geo", 0) > 0:
            options.append(ViolationCategory.RESTRICTED_GEO); weights.append(nw["restricted_geo"])
        if self.flags.enable_tls_tests and nw.get("tls", 0) > 0:
            options.append(ViolationCategory.TLS); weights.append(nw["tls"])
        if self.flags.enable_phish_tests and nw.get("phish", 0) > 0:
            options.append(ViolationCategory.PHISH); weights.append(nw["phish"])
        if self.flags.enable_malware_tests and nw.get("malware", 0) > 0:
            options.append(ViolationCategory.MALWARE); weights.append(nw["malware"])
        if self.flags.enable_private_app_tests:
            options.append(ViolationCategory.DENIED_PRIVATE_APP); weights.append(15)

        if not options:
            return None
        chosen = random.choices(options, weights=weights, k=1)[0]
        return chosen

    # ── Build action plan ─────────────────────────────────────────────

    def build_action_plan(self) -> ActionPlan:
        btype = self.select_behavior_type()

        if btype == BehaviorType.NORMAL:
            return self._plan_normal()
        elif btype == BehaviorType.GRAY_AREA:
            return self._plan_gray_area()
        else:
            return self._plan_violation()

    def _plan_normal(self) -> ActionPlan:
        # Decide: search, revisit, private app, or new site
        p = self.persona

        if (self.run_mode == RunMode.PRIVATE_APP_FOCUS
                and self.flags.enable_private_app_tests
                and chance(0.5)):
            app = self._pick_allowed_private_app()
            if app:
                return ActionPlan(
                    behavior_type=BehaviorType.NORMAL,
                    category="private_app",
                    target_url=app.url(),
                    max_depth=1,
                    action_label="private_app_check",
                    is_private_app=True,
                    private_app=app,
                )

        if self._visited_urls and chance(p.behavior.revisit_chance):
            url = random.choice(self._visited_urls[-20:])
            return ActionPlan(
                behavior_type=BehaviorType.NORMAL,
                category="revisit",
                target_url=url,
                max_depth=p.behavior.max_click_depth,
                action_label="revisit",
            )

        if p.search_queries and chance(p.behavior.search_engine_chance):
            query = random.choice(p.search_queries)
            return ActionPlan(
                behavior_type=BehaviorType.NORMAL,
                category="search",
                target_url="",
                max_depth=2,
                action_label="search",
                search_query=query,
            )

        url = random.choice(p.normal_sites) if p.normal_sites else "https://en.wikipedia.org"
        self._visited_urls.append(url)
        return ActionPlan(
            behavior_type=BehaviorType.NORMAL,
            category="browse",
            target_url=url,
            max_depth=p.behavior.max_click_depth,
            action_label="browse",
        )

    def _plan_gray_area(self) -> ActionPlan:
        # Gray area: use AI sites for "summarize" type actions
        p = self.persona
        if p.ai_sites and self.flags.enable_ai_tests:
            url = random.choice(p.ai_sites)
            prompt = None
            if self.safe_prompts:
                matching = [sp for sp in self.safe_prompts if sp.get("persona") == p.name]
                if matching:
                    prompt = random.choice(matching).get("text", "")
            return ActionPlan(
                behavior_type=BehaviorType.GRAY_AREA,
                category="ai",
                target_url=url,
                max_depth=1,
                action_label="ai_gray_area",
                prompt_text=prompt,
            )
        # Fallback to normal browse
        return self._plan_normal()

    def _plan_violation(self) -> ActionPlan:
        cat = self.select_violation_category()
        if cat is None:
            return self._plan_normal()

        p = self.persona

        if cat == ViolationCategory.AI:
            url = random.choice(p.ai_sites) if p.ai_sites else "https://chat.openai.com"
            prompt = None
            if self.safe_prompts:
                matching = [sp for sp in self.safe_prompts if sp.get("persona") == p.name]
                if matching:
                    prompt = random.choice(matching).get("text", "")
            return ActionPlan(
                behavior_type=BehaviorType.VIOLATION, category="ai",
                target_url=url, max_depth=1, action_label="ai_violation",
                prompt_text=prompt,
            )

        if cat == ViolationCategory.RESTRICTED_GEO:
            if p.restricted_geo_sites:
                site = random.choice(p.restricted_geo_sites)
                url = site if isinstance(site, str) else site.get("url", "")
            else:
                url = "https://rt.com"
            return ActionPlan(
                behavior_type=BehaviorType.VIOLATION, category="restricted_geo",
                target_url=url, max_depth=1, action_label="restricted_geo",
            )

        if cat == ViolationCategory.TLS:
            url = random.choice(p.tls_test_sites) if p.tls_test_sites else "https://expired.badssl.com/"
            return ActionPlan(
                behavior_type=BehaviorType.VIOLATION, category="tls",
                target_url=url, max_depth=1, action_label="tls_test",
            )

        if cat == ViolationCategory.PHISH:
            url = random.choice(p.phish_test_sites) if p.phish_test_sites else "https://phish.lab.local"
            return ActionPlan(
                behavior_type=BehaviorType.VIOLATION, category="phish",
                target_url=url, max_depth=1, action_label="phish_simulation",
            )

        if cat == ViolationCategory.MALWARE:
            if self.malware_tests:
                test = random.choice(self.malware_tests)
                url = test.get("url", "https://secure.eicar.org/eicar.com.txt")
            else:
                url = "https://secure.eicar.org/eicar.com.txt"
            return ActionPlan(
                behavior_type=BehaviorType.VIOLATION, category="malware",
                target_url=url, max_depth=0, action_label="malware_download_test",
            )

        if cat == ViolationCategory.DENIED_PRIVATE_APP:
            app = self._pick_denied_private_app()
            if app:
                return ActionPlan(
                    behavior_type=BehaviorType.VIOLATION, category="denied_private_app",
                    target_url=app.url(), max_depth=1, action_label="denied_private_app",
                    is_private_app=True, private_app=app,
                )

        return self._plan_normal()

    # ── Private app helpers ───────────────────────────────────────────

    def _pick_allowed_private_app(self) -> Optional[PrivateApp]:
        allowed = [
            a for a in self.private_apps
            if a.enabled and self.persona.name in a.allowed_personas
        ]
        if not allowed:
            return None
        return random.choices(allowed, weights=[a.weight for a in allowed], k=1)[0]

    def _pick_denied_private_app(self) -> Optional[PrivateApp]:
        denied = [
            a for a in self.private_apps
            if a.enabled and self.persona.name not in a.allowed_personas
        ]
        if not denied:
            return None
        return random.choice(denied)

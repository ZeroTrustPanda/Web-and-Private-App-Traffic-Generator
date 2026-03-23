"""Executes action plans against the browser and returns results."""
from __future__ import annotations

import asyncio
import random
import time

from app.engine.browser_manager import BrowserManager
from app.engine.result_classifier import classify_result, classify_private_app, should_screenshot
from app.logging.loggers import ScreenshotManager
from app.models.models import ActionPlan, ActionResult, BehaviorType, PersonaBehavior, ResultType


class ActionExecutor:
    def __init__(
        self,
        browser: BrowserManager,
        persona_behavior: PersonaBehavior,
        screenshot_mgr: ScreenshotManager,
    ):
        self.browser = browser
        self.pb = persona_behavior
        self.screenshot_mgr = screenshot_mgr

    async def execute(self, plan: ActionPlan) -> ActionResult:
        try:
            if plan.action_label == "search":
                return await self._execute_search(plan)
            elif plan.is_private_app:
                return await self._execute_private_app(plan)
            else:
                return await self._execute_browse(plan)
        except Exception as exc:
            return ActionResult(
                action_plan=plan,
                result_type=ResultType.LOAD_FAILURE,
                final_url=plan.target_url,
                notes=f"Exception: {exc}",
            )

    # ── Browse ────────────────────────────────────────────────────────

    async def _execute_browse(self, plan: ActionPlan) -> ActionResult:
        nav = await self.browser.goto(plan.target_url)
        page_text = await self.browser.page_text_sample()
        rt = classify_result(nav, page_text)

        await self._dwell()
        await self.browser.scroll_random()

        depth = 0
        if rt == ResultType.ALLOWED and plan.max_depth > 0:
            depth = await self._click_traverse(plan.max_depth)

        result = ActionResult(
            action_plan=plan,
            result_type=rt,
            final_url=nav.get("url", plan.target_url),
            page_title=nav.get("title", ""),
            latency_ms=nav.get("latency_ms", 0),
            click_depth=depth,
            requires_screenshot=should_screenshot(rt),
        )

        if result.requires_screenshot:
            path = self.screenshot_mgr.capture_path(plan.action_label)
            await self.browser.screenshot(path)
            result.screenshot_path = path

        return result

    # ── Search ────────────────────────────────────────────────────────

    async def _execute_search(self, plan: ActionPlan) -> ActionResult:
        query = plan.search_query or "test"
        if random.random() < 0.5:
            nav = await self.browser.search_google(query)
        else:
            nav = await self.browser.search_bing(query)

        page_text = await self.browser.page_text_sample()
        rt = classify_result(nav, page_text)

        await self._dwell()

        # Try to click a search result
        depth = 0
        if rt == ResultType.ALLOWED:
            links = await self.browser.get_links()
            content_links = [
                l for l in links
                if l.get("href", "").startswith("http")
                and "google" not in l["href"]
                and "bing" not in l["href"]
                and "microsoft" not in l["href"]
                and len(l.get("text", "")) > 5
            ]
            if content_links:
                chosen = random.choice(content_links[:8])
                nav2 = await self.browser.click_link(chosen["href"])
                page_text2 = await self.browser.page_text_sample()
                rt = classify_result(nav2, page_text2)
                nav = nav2
                depth = 1
                await self._dwell()

        result = ActionResult(
            action_plan=plan,
            result_type=rt,
            final_url=nav.get("url", ""),
            page_title=nav.get("title", ""),
            latency_ms=nav.get("latency_ms", 0),
            click_depth=depth,
            notes=f"Query: {query}",
            requires_screenshot=should_screenshot(rt),
        )
        if result.requires_screenshot:
            path = self.screenshot_mgr.capture_path(f"search_{query[:20]}")
            await self.browser.screenshot(path)
            result.screenshot_path = path
        return result

    # ── Private App ───────────────────────────────────────────────────

    async def _execute_private_app(self, plan: ActionPlan) -> ActionResult:
        app = plan.private_app
        nav = await self.browser.goto(plan.target_url)
        page_text = await self.browser.page_text_sample()

        sel_present = True
        if app and app.expected_selector:
            sel_present = await self.browser.has_selector(app.expected_selector)

        rt = classify_private_app(
            nav, page_text,
            expected_title=app.expected_title_substring if app else "",
            expected_selector_present=sel_present,
        )

        result = ActionResult(
            action_plan=plan,
            result_type=rt,
            final_url=nav.get("url", plan.target_url),
            page_title=nav.get("title", ""),
            latency_ms=nav.get("latency_ms", 0),
            notes=f"Private app: {app.name if app else 'unknown'}",
            requires_screenshot=should_screenshot(rt),
        )
        if result.requires_screenshot:
            path = self.screenshot_mgr.capture_path(f"priv_{app.name if app else 'app'}")
            await self.browser.screenshot(path)
            result.screenshot_path = path
        return result

    # ── Helpers ────────────────────────────────────────────────────────

    async def _dwell(self) -> None:
        bucket = random.choices(["short", "medium", "long"], weights=[50, 35, 15])[0]
        if bucket == "short":
            lo, hi = self.pb.dwell_short_seconds
        elif bucket == "medium":
            lo, hi = self.pb.dwell_medium_seconds
        else:
            lo, hi = self.pb.dwell_long_seconds
        await asyncio.sleep(random.uniform(lo, hi))

    async def _click_traverse(self, max_depth: int) -> int:
        depth = 0
        for _ in range(max_depth):
            links = await self.browser.get_links()
            # Filter out non-content links
            good = [
                l for l in links
                if l.get("href", "").startswith("http")
                and "login" not in l["href"].lower()
                and "logout" not in l["href"].lower()
                and "signin" not in l["href"].lower()
                and "signup" not in l["href"].lower()
                and "javascript:" not in l["href"].lower()
                and "mailto:" not in l["href"].lower()
                and len(l.get("text", "")) > 2
            ]
            if not good:
                break
            chosen = random.choice(good[:15])
            nav = await self.browser.click_link(chosen["href"])
            if nav.get("error"):
                break
            depth += 1
            await self.browser.scroll_random()
            await self._dwell()
        return depth

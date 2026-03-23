"""Browser manager: launch, navigate, click, scroll, screenshot via Playwright."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """Manages a single Chromium browser instance with one default page."""

    def __init__(self, timeout_ms: int = 30000):
        self.timeout_ms = timeout_ms
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def launch(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        self._page = await self._context.new_page()

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._context = self._page = None

    async def restart(self) -> None:
        await self.close()
        await self.launch()

    @property
    def page(self) -> Page:
        assert self._page is not None, "Browser not launched"
        return self._page

    # ── Navigation ────────────────────────────────────────────────────

    async def goto(self, url: str) -> dict:
        """Navigate and return {url, title, error}."""
        start = time.monotonic()
        try:
            resp = await self.page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            title = await self.page.title()
            return {
                "url": self.page.url,
                "title": title,
                "status": resp.status if resp else 0,
                "error": None,
                "latency_ms": int((time.monotonic() - start) * 1000),
            }
        except Exception as exc:
            return {
                "url": url,
                "title": "",
                "status": 0,
                "error": str(exc),
                "latency_ms": int((time.monotonic() - start) * 1000),
            }

    async def current_url(self) -> str:
        return self.page.url

    async def current_title(self) -> str:
        try:
            return await self.page.title()
        except Exception:
            return ""

    # ── Interaction ───────────────────────────────────────────────────

    async def scroll_random(self) -> None:
        distance = random.randint(200, 800)
        try:
            await self.page.evaluate(f"window.scrollBy(0, {distance})")
            await asyncio.sleep(random.uniform(0.3, 1.0))
        except Exception:
            pass

    async def get_links(self) -> list[dict]:
        """Return list of {href, text} from visible anchors."""
        try:
            links = await self.page.evaluate("""() => {
                const anchors = document.querySelectorAll('a[href]');
                const result = [];
                for (const a of anchors) {
                    const href = a.href;
                    const text = (a.innerText || '').trim().substring(0, 120);
                    if (href && href.startsWith('http') && text.length > 0) {
                        result.push({href, text});
                    }
                }
                return result;
            }""")
            return links or []
        except Exception:
            return []

    async def click_link(self, href: str) -> dict:
        """Navigate to href via page.goto (more reliable than element click)."""
        return await self.goto(href)

    async def go_back(self) -> None:
        try:
            await self.page.go_back(timeout=self.timeout_ms)
        except Exception:
            pass

    # ── Tabs ──────────────────────────────────────────────────────────

    async def open_new_tab(self, url: str) -> dict:
        try:
            new_page = await self._context.new_page()
            self._page = new_page
            return await self.goto(url)
        except Exception as exc:
            return {"url": url, "title": "", "status": 0, "error": str(exc), "latency_ms": 0}

    async def close_extra_tabs(self) -> None:
        if not self._context:
            return
        pages = self._context.pages
        while len(pages) > 1:
            try:
                await pages[-1].close()
            except Exception:
                pass
            pages = self._context.pages
        if pages:
            self._page = pages[0]

    # ── Search ────────────────────────────────────────────────────────

    async def search_google(self, query: str) -> dict:
        """Perform a Google search and return nav result."""
        encoded = query.replace(" ", "+")
        url = f"https://www.google.com/search?q={encoded}"
        return await self.goto(url)

    async def search_bing(self, query: str) -> dict:
        encoded = query.replace(" ", "+")
        url = f"https://www.bing.com/search?q={encoded}"
        return await self.goto(url)

    # ── Screenshot ────────────────────────────────────────────────────

    async def screenshot(self, path: str) -> None:
        try:
            await self.page.screenshot(path=path, full_page=False)
        except Exception:
            pass

    # ── Page inspection ───────────────────────────────────────────────

    async def page_text_sample(self, max_chars: int = 2000) -> str:
        try:
            text = await self.page.evaluate("() => document.body?.innerText?.substring(0, 3000) || ''")
            return text[:max_chars]
        except Exception:
            return ""

    async def has_selector(self, selector: str) -> bool:
        try:
            el = await self.page.query_selector(selector)
            return el is not None
        except Exception:
            return False

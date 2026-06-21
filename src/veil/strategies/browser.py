"""Heaviest strategy: a real headless browser with stealth patches.

Use this only when fingerprinting or JS challenges defeat the lighter tiers.
It actually executes the page's JavaScript, so it clears interstitials that
require running a challenge script (e.g. Cloudflare "Just a moment...").
"""
from __future__ import annotations

import asyncio
from typing import Optional

from veil.models import FetchRequest, FetchResponse
from veil.strategies.base import Strategy

try:
    from playwright.async_api import async_playwright  # type: ignore

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_PLAYWRIGHT = False

try:
    from playwright_stealth import stealth_async  # type: ignore

    _HAS_STEALTH = True
except ImportError:  # pragma: no cover
    _HAS_STEALTH = False


class BrowserStrategy(Strategy):
    name = "browser"
    cost = 100

    def __init__(self, headless: bool = True, wait_until: str = "networkidle") -> None:
        self.headless = headless
        self.wait_until = wait_until
        self.available = _HAS_PLAYWRIGHT
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self):
        # Lazily launch one browser process and reuse it across fetches.
        async with self._lock:
            if self._browser is None:
                if not _HAS_PLAYWRIGHT:
                    raise RuntimeError(
                        "playwright is not installed. Install with: "
                        "pip install 'veil-scraper[browser]' && playwright install chromium"
                    )
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(headless=self.headless)
        return self._browser

    async def fetch(
        self, request: FetchRequest, *, proxy: Optional[str] = None
    ) -> FetchResponse:
        browser = await self._ensure_browser()
        context_kwargs = {}
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}
        if request.headers:
            context_kwargs["extra_http_headers"] = request.headers

        context = await browser.new_context(**context_kwargs)
        try:
            page = await context.new_page()
            if _HAS_STEALTH:
                await stealth_async(page)
            resp = await page.goto(
                request.url, wait_until=self.wait_until, timeout=request.timeout * 1000
            )
            status = resp.status if resp else 0
            text = await page.content()
            headers = dict(resp.headers) if resp else {}
            return FetchResponse(
                url=page.url,
                status=status,
                text=text,
                headers=headers,
                strategy=self.name,
                from_proxy=proxy,
            )
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

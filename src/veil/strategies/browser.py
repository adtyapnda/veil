"""Heaviest strategy: a real headless browser with stealth patches.

Use this only when fingerprinting or JS challenges defeat the lighter tiers.
It actually executes the page's JavaScript, so it clears interstitials that
require running a challenge script (e.g. Cloudflare "Just a moment...").

Three cost/realism optimizations layer on top of the bare browser:
  * resource blocking   -- abort images/fonts/media (faster, cheaper, still real)
  * behavioral mimicry  -- jittered mouse/scroll before reading (beats behavior checks)
  * context concurrency -- N parallel browser contexts on one browser process
"""
from __future__ import annotations

import asyncio
import random
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

# Resource types safe to drop without breaking most pages or challenge scripts.
# (Stylesheets/scripts are kept -- challenges often need them.)
_DEFAULT_BLOCKED = frozenset({"image", "font", "media"})

# A real Chrome UA, kept in sync with the http_basic tier so tiers don't conflict.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Launch flags that strip the most obvious "I am automated" tells.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-first-run",
    "--no-default-browser-check",
]

# Injected before any page script runs: patches the classic detection surface
# (navigator.webdriver, plugins, languages, window.chrome, permissions).
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
const _origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (_origQuery) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _origQuery(p);
}
"""


class BrowserStrategy(Strategy):
    name = "browser"
    cost = 100

    def __init__(
        self,
        headless: bool = True,
        wait_until: str = "networkidle",
        *,
        block_resources: bool = True,
        blocked_types: frozenset[str] = _DEFAULT_BLOCKED,
        humanize: bool = True,
        max_contexts: int = 4,
        viewport: tuple[int, int] = (1280, 800),
    ) -> None:
        self.headless = headless
        self.wait_until = wait_until
        self.block_resources = block_resources
        self.blocked_types = blocked_types
        self.humanize = humanize
        self.max_contexts = max_contexts
        self.viewport = viewport
        self.available = _HAS_PLAYWRIGHT

        self._pw = None
        self._browser = None
        self._launch_lock = asyncio.Lock()
        # Bound how many browser contexts run at once (set up lazily so it binds
        # to the loop the engine actually runs on).
        self._sem: Optional[asyncio.Semaphore] = None

    async def _ensure_browser(self):
        # Lazily launch one browser process and reuse it across fetches.
        async with self._launch_lock:
            if self._browser is None:
                if not _HAS_PLAYWRIGHT:
                    raise RuntimeError(
                        "playwright is not installed. Install with: "
                        "pip install 'veil-scraper[browser]' && playwright install chromium"
                    )
                self._pw = await async_playwright().start()
                self._browser = await self._launch(self._pw)
            if self._sem is None:
                self._sem = asyncio.Semaphore(self.max_contexts)
        return self._browser

    async def _launch(self, pw):
        # Real Chrome (channel="chrome") looks far less automated than bundled
        # Chromium, but isn't always installed -- fall back gracefully.
        opts = {"headless": self.headless, "args": _LAUNCH_ARGS}
        try:
            return await pw.chromium.launch(channel="chrome", **opts)
        except Exception:  # noqa: BLE001 - chrome channel not available
            return await pw.chromium.launch(**opts)

    async def _install_blocking(self, context) -> None:
        async def _route(route):
            if route.request.resource_type in self.blocked_types:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", _route)

    async def _act_human(self, page) -> None:
        # A few small, jittered movements so we don't look like an instant,
        # mouse-less bot. Best-effort: never fail a fetch over a nicety.
        try:
            w, h = self.viewport
            for _ in range(random.randint(2, 4)):
                await page.mouse.move(
                    random.randint(0, w), random.randint(0, h),
                    steps=random.randint(5, 15),
                )
                await page.wait_for_timeout(random.randint(80, 250))
            await page.mouse.wheel(0, random.randint(200, 900))
            await page.wait_for_timeout(random.randint(150, 500))
        except Exception:  # noqa: BLE001
            pass

    async def fetch(
        self, request: FetchRequest, *, proxy: Optional[str] = None
    ) -> FetchResponse:
        browser = await self._ensure_browser()
        # Realistic context: real UA + locale/timezone so headers and JS environment
        # agree (mismatches between these are a common bot tell).
        context_kwargs = {
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
            "user_agent": _CHROME_UA,
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}
        if request.headers:
            context_kwargs["extra_http_headers"] = request.headers

        assert self._sem is not None
        async with self._sem:  # bound concurrent contexts
            context = await browser.new_context(**context_kwargs)
            try:
                # Patch the detection surface before any page script runs.
                await context.add_init_script(_STEALTH_JS)
                if self.block_resources:
                    await self._install_blocking(context)
                page = await context.new_page()
                if _HAS_STEALTH:
                    await stealth_async(page)
                resp = await page.goto(
                    request.url,
                    wait_until=self.wait_until,
                    timeout=request.timeout * 1000,
                )
                if self.humanize:
                    await self._act_human(page)
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

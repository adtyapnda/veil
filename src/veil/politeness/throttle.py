"""Politeness layer: robots.txt compliance + per-host rate limiting.

This is the part that keeps the tool ethical and keeps you off blocklists.
It is ON by default. Respecting robots.txt is a deliberate default, not an
oversight -- disable it only for domains you own or are authorized to crawl.
"""
from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx


@dataclass
class HostThrottle:
    """Tracks the last request time per host to enforce a minimum delay."""

    delay: float = 1.0
    _last: dict[str, float] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _lock_for(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        async with self._lock_for(host):
            now = time.monotonic()
            elapsed = now - self._last.get(host, 0.0)
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self._last[host] = time.monotonic()


@dataclass
class RobotsCache:
    """Fetches and caches robots.txt rules per host."""

    user_agent: str = "veil"
    _parsers: dict[str, urllib.robotparser.RobotFileParser] = field(default_factory=dict)

    async def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._parsers:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{host}/robots.txt"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(robots_url)
                    rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                # On any error, fail open (allow) -- robots is advisory, and a
                # transient fetch failure shouldn't halt the whole crawl.
                rp.parse([])
            self._parsers[host] = rp
        return self._parsers[host]

    async def allowed(self, url: str) -> bool:
        rp = await self._parser_for(url)
        return rp.can_fetch(self.user_agent, url)


@dataclass
class Politeness:
    """Combined gate: robots check + throttle, applied before every fetch."""

    respect_robots: bool = True
    delay: float = 1.0
    user_agent: str = "veil"

    def __post_init__(self) -> None:
        self.throttle = HostThrottle(delay=self.delay)
        self.robots = RobotsCache(user_agent=self.user_agent)

    async def gate(self, url: str) -> None:
        """Raise PermissionError if robots disallows; otherwise throttle."""
        if self.respect_robots and not await self.robots.allowed(url):
            raise PermissionError(f"robots.txt disallows fetching {url}")
        await self.throttle.wait(url)

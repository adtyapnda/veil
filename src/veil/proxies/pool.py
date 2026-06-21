"""Proxy rotation with lightweight health tracking.

Hands out proxies round-robin, skips ones that have failed recently, and lets
the engine report success/failure so bad proxies cool down automatically.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _ProxyState:
    url: str
    failures: int = 0
    # Unix timestamp before which this proxy should be skipped.
    cooldown_until: float = 0.0


@dataclass
class ProxyPool:
    """A rotating pool of proxy URLs (e.g. 'http://user:pass@host:port')."""

    proxies: list[str] = field(default_factory=list)
    # After this many consecutive failures a proxy is benched.
    max_failures: int = 3
    cooldown_seconds: float = 60.0

    def __post_init__(self) -> None:
        self._states = {p: _ProxyState(p) for p in self.proxies}
        self._cycle = itertools.cycle(self.proxies) if self.proxies else None

    @property
    def enabled(self) -> bool:
        return bool(self.proxies)

    def acquire(self) -> Optional[str]:
        """Return the next healthy proxy, or None if the pool is empty."""
        if not self._cycle:
            return None
        now = time.time()
        # Try at most one full lap to find a healthy proxy.
        for _ in range(len(self.proxies)):
            proxy = next(self._cycle)
            state = self._states[proxy]
            if state.cooldown_until <= now:
                return proxy
        # Everything is cooling down; return the soonest-available anyway.
        return min(self._states.values(), key=lambda s: s.cooldown_until).url

    def report_success(self, proxy: Optional[str]) -> None:
        if proxy and proxy in self._states:
            self._states[proxy].failures = 0
            self._states[proxy].cooldown_until = 0.0

    def report_failure(self, proxy: Optional[str]) -> None:
        if not proxy or proxy not in self._states:
            return
        state = self._states[proxy]
        state.failures += 1
        if state.failures >= self.max_failures:
            state.cooldown_until = time.time() + self.cooldown_seconds
            state.failures = 0

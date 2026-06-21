"""Strategy contract. Every fetch backend implements this interface."""
from __future__ import annotations

import abc
from typing import Optional

from veil.models import FetchRequest, FetchResponse


class Strategy(abc.ABC):
    """A pluggable way to fetch a URL.

    Strategies are ordered by *cost*: the engine tries the cheapest first and
    escalates only when a cheaper one is blocked or returns junk. ``cost`` is an
    arbitrary integer used purely for ordering (lower = tried earlier).
    """

    name: str = "base"
    cost: int = 0

    # Set False for strategies whose optional deps are not installed, so the
    # engine can skip them gracefully instead of crashing.
    available: bool = True

    @abc.abstractmethod
    async def fetch(
        self, request: FetchRequest, *, proxy: Optional[str] = None
    ) -> FetchResponse:
        """Fetch ``request`` or raise BlockedError / an exception on failure."""

    def looks_blocked(self, resp: FetchResponse, request: FetchRequest) -> bool:
        """Heuristic shared by all strategies to detect soft blocks.

        Returns True when the HTTP status or body smells like an anti-bot wall
        even though the request technically "succeeded".
        """
        if resp.status in (403, 429, 503):
            return True
        body = resp.text.lower()
        signals = (
            "just a moment",          # Cloudflare interstitial
            "verifying you are human",
            "cf-chl",                 # Cloudflare challenge token
            "captcha",
            "access denied",
            "enable javascript and cookies",
        )
        if any(s in body for s in signals):
            return True
        if request.success_marker and request.success_marker.lower() not in body:
            return True
        return False

    async def aclose(self) -> None:
        """Release resources (browser, client). Override if needed."""

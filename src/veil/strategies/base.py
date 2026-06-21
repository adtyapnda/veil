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

    # Challenge/interstitial pages are small; above this size, textual block
    # signals are treated as noise rather than evidence of a wall.
    CHALLENGE_PAGE_MAX_BYTES: int = 15000

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
        # An explicit success marker is authoritative: if you told us what real
        # content looks like and it's there, trust it over fuzzy signals.
        if request.success_marker:
            return request.success_marker.lower() not in body
        # Textual challenge signals only mean "blocked" on a small interstitial.
        # A full content page can legitimately embed these tokens (e.g. a page
        # that *passed* a Cloudflare challenge still ships cf-chl scripts).
        if len(resp.text) < self.CHALLENGE_PAGE_MAX_BYTES:
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
        return False

    async def aclose(self) -> None:
        """Release resources (browser, client). Override if needed."""

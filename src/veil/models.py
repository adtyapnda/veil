"""Core data types passed between the engine and strategies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FetchRequest:
    """A single fetch the engine should satisfy by any working strategy."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    # Optional CSS/text marker that must be present for the response to count
    # as "real content" rather than a challenge/block page.
    success_marker: Optional[str] = None
    # Per-request override; otherwise the engine's default order is used.
    strategies: Optional[list[str]] = None
    timeout: float = 30.0


@dataclass
class FetchResponse:
    """Normalized result regardless of which strategy produced it."""

    url: str
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)
    strategy: str = ""
    # How many strategies were attempted before this one succeeded.
    attempts: int = 1
    from_proxy: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class BlockedError(Exception):
    """Raised by a strategy when it is confident the response is a block/challenge."""


class AllStrategiesFailed(Exception):
    """Raised by the engine when no configured strategy could fetch the URL."""

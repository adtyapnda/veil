"""Engine tests using fake strategies -- no network required."""
from __future__ import annotations

import pytest

from veil.engine import Engine
from veil.models import AllStrategiesFailed, FetchRequest, FetchResponse
from veil.politeness import Politeness
from veil.strategies.base import Strategy


class FakeStrategy(Strategy):
    def __init__(self, name, cost, *, status=200, body="ok content"):
        self.name = name
        self.cost = cost
        self._status = status
        self._body = body
        self.calls = 0

    async def fetch(self, request, *, proxy=None):
        self.calls += 1
        return FetchResponse(
            url=request.url, status=self._status, text=self._body, strategy=self.name
        )


@pytest.fixture
def no_politeness():
    # Disable robots + throttle so tests don't hit the network or sleep.
    p = Politeness(respect_robots=False, delay=0.0)
    return p


async def test_cheapest_strategy_wins(no_politeness):
    cheap = FakeStrategy("cheap", cost=0)
    pricey = FakeStrategy("pricey", cost=100)
    engine = Engine(strategies=[pricey, cheap], politeness=no_politeness)

    resp = await engine.fetch("http://example.com")

    assert resp.strategy == "cheap"
    assert resp.attempts == 1
    assert pricey.calls == 0  # never escalated


async def test_escalates_past_blocked(no_politeness):
    blocked = FakeStrategy("blocked", cost=0, status=403, body="Access Denied")
    good = FakeStrategy("good", cost=10, body="real page body")
    engine = Engine(strategies=[blocked, good], politeness=no_politeness)

    resp = await engine.fetch("http://example.com")

    assert resp.strategy == "good"
    assert resp.attempts == 2
    assert blocked.calls == 1


async def test_success_marker_forces_escalation(no_politeness):
    wrong = FakeStrategy("wrong", cost=0, body="some other page")
    right = FakeStrategy("right", cost=10, body="contains the MAGIC token")
    engine = Engine(strategies=[wrong, right], politeness=no_politeness)

    resp = await engine.fetch(FetchRequest(url="http://x.com", success_marker="MAGIC"))

    assert resp.strategy == "right"


async def test_all_fail_raises(no_politeness):
    a = FakeStrategy("a", cost=0, status=403, body="captcha")
    b = FakeStrategy("b", cost=10, status=429, body="too many requests")
    engine = Engine(strategies=[a, b], politeness=no_politeness)

    with pytest.raises(AllStrategiesFailed):
        await engine.fetch("http://example.com")

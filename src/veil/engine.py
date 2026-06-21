"""The cascade engine: orchestrates strategies, proxies, politeness, retries."""
from __future__ import annotations

import logging
from typing import Optional

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from veil.models import AllStrategiesFailed, BlockedError, FetchRequest, FetchResponse
from veil.politeness import Politeness
from veil.proxies import ProxyPool
from veil.strategies import (
    BrowserStrategy,
    HttpBasicStrategy,
    Strategy,
    TlsImpersonateStrategy,
)

log = logging.getLogger("veil")


class Engine:
    """Fetch a URL by escalating through strategies until one works.

    Order is by ``Strategy.cost`` ascending: try the cheapest viable strategy,
    and only escalate to a heavier one when the response looks blocked.
    """

    def __init__(
        self,
        strategies: Optional[list[Strategy]] = None,
        proxy_pool: Optional[ProxyPool] = None,
        politeness: Optional[Politeness] = None,
        retries_per_strategy: int = 2,
    ) -> None:
        if strategies is None:
            strategies = [
                HttpBasicStrategy(),
                TlsImpersonateStrategy(),
                BrowserStrategy(),
            ]
        # Keep only available strategies, ordered cheapest-first.
        self.strategies = sorted(
            (s for s in strategies if s.available), key=lambda s: s.cost
        )
        self.proxy_pool = proxy_pool or ProxyPool()
        self.politeness = politeness or Politeness()
        self.retries_per_strategy = retries_per_strategy

    async def fetch(self, request: FetchRequest | str) -> FetchResponse:
        if isinstance(request, str):
            request = FetchRequest(url=request)

        await self.politeness.gate(request.url)

        selected = self._select(request)
        attempts = 0
        last_exc: Optional[Exception] = None

        for strategy in selected:
            attempts += 1
            try:
                resp = await self._run_with_retry(strategy, request)
                resp.attempts = attempts
                if strategy.looks_blocked(resp, request):
                    log.info("strategy=%s blocked, escalating", strategy.name)
                    self.proxy_pool.report_failure(resp.from_proxy)
                    last_exc = BlockedError(f"{strategy.name} returned a block page")
                    continue
                self.proxy_pool.report_success(resp.from_proxy)
                log.info("strategy=%s succeeded (status=%s)", strategy.name, resp.status)
                return resp
            except Exception as exc:  # noqa: BLE001 - escalate on any failure
                log.warning("strategy=%s failed: %s", strategy.name, exc)
                last_exc = exc
                continue

        raise AllStrategiesFailed(
            f"All {attempts} strategies failed for {request.url}"
        ) from last_exc

    def _select(self, request: FetchRequest) -> list[Strategy]:
        if request.strategies:
            wanted = set(request.strategies)
            return [s for s in self.strategies if s.name in wanted]
        return self.strategies

    async def _run_with_retry(
        self, strategy: Strategy, request: FetchRequest
    ) -> FetchResponse:
        # Transient network errors get a couple of backed-off retries before we
        # give up on this strategy and escalate to the next.
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.retries_per_strategy),
            wait=wait_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        ):
            with attempt:
                proxy = self.proxy_pool.acquire() if self.proxy_pool.enabled else None
                return await strategy.fetch(request, proxy=proxy)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        for s in self.strategies:
            await s.aclose()

"""Cheapest strategy: a plain httpx request with a believable header set."""
from __future__ import annotations

from typing import Optional

import httpx

from veil.models import FetchRequest, FetchResponse
from veil.strategies.base import Strategy

# A current, real Chrome header order. httpx can't fake the TLS fingerprint,
# but well-formed headers alone clear a surprising number of basic filters.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


class HttpBasicStrategy(Strategy):
    name = "http_basic"
    cost = 0

    async def fetch(
        self, request: FetchRequest, *, proxy: Optional[str] = None
    ) -> FetchResponse:
        headers = {**_DEFAULT_HEADERS, **request.headers}
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=request.timeout,
            proxy=proxy,
            http2=True,
        ) as client:
            r = await client.request(request.method, request.url, headers=headers)
            return FetchResponse(
                url=str(r.url),
                status=r.status_code,
                text=r.text,
                headers=dict(r.headers),
                strategy=self.name,
                from_proxy=proxy,
            )

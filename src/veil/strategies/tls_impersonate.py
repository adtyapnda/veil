"""Mid-tier strategy: curl_cffi impersonates a real browser's TLS/JA3 + HTTP2.

This defeats fingerprint-based filters (the kind that reject you for *how* you
connect, not what you send) without the cost of launching a browser.
"""
from __future__ import annotations

from typing import Optional

from veil.models import FetchRequest, FetchResponse
from veil.strategies.base import Strategy

try:
    from curl_cffi import requests as cffi_requests  # type: ignore

    _HAS_CURL_CFFI = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_CURL_CFFI = False


class TlsImpersonateStrategy(Strategy):
    name = "tls_impersonate"
    cost = 10

    def __init__(self, impersonate: str = "chrome") -> None:
        # "chrome" tracks a recent stable Chrome fingerprint in curl_cffi.
        self.impersonate = impersonate
        self.available = _HAS_CURL_CFFI

    async def fetch(
        self, request: FetchRequest, *, proxy: Optional[str] = None
    ) -> FetchResponse:
        if not _HAS_CURL_CFFI:
            raise RuntimeError(
                "curl_cffi is not installed. Install with: pip install 'veil-scraper[tls]'"
            )
        proxies = {"http": proxy, "https": proxy} if proxy else None
        # curl_cffi's async API mirrors requests but is awaitable.
        async with cffi_requests.AsyncSession() as session:
            r = await session.request(
                request.method,
                request.url,
                headers=request.headers or None,
                impersonate=self.impersonate,
                proxies=proxies,
                timeout=request.timeout,
                allow_redirects=True,
            )
            return FetchResponse(
                url=r.url,
                status=r.status_code,
                text=r.text,
                headers=dict(r.headers),
                strategy=self.name,
                from_proxy=proxy,
            )

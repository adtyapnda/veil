"""Probe each strategy independently against real anti-bot test targets.

Prints a matrix: for every (target, tier) it reports HTTP status, whether the
block heuristic fired, and response size -- so you can see exactly which tier
beats which defense. Targets below are public pages intended for testing
scrapers (or harmless control pages).

Run:  python examples/battletest.py   (needs the [all] extra + chromium)
"""
import asyncio

from veil.models import FetchRequest
from veil.strategies import BrowserStrategy, HttpBasicStrategy, TlsImpersonateStrategy

TARGETS = [
    ("control: example.com", "https://example.com", "Example Domain"),
    ("cloudflare js-challenge", "https://nowsecure.nl", None),
    ("scrapingcourse antibot", "https://www.scrapingcourse.com/antibot-challenge", None),
    ("bot fingerprint test", "https://bot.sannysoft.com", None),
]


async def probe(strategy, url, marker):
    req = FetchRequest(url=url, success_marker=marker, timeout=30.0)
    try:
        resp = await strategy.fetch(req)
        blocked = strategy.looks_blocked(resp, req)
        verdict = "BLOCKED" if blocked else "OK"
        return f"{verdict:8} status={resp.status:<3} bytes={len(resp.text):>7}"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).splitlines()[0][:48]
        return f"ERROR    {msg}"


async def main():
    strategies = [
        HttpBasicStrategy(),
        TlsImpersonateStrategy(),
        BrowserStrategy(),  # block_resources + humanize on by default
    ]
    try:
        for label, url, marker in TARGETS:
            print(f"\n# {label}\n  {url}")
            for s in strategies:
                if not s.available:
                    print(f"  {s.name:18} (unavailable - extra not installed)")
                    continue
                result = await probe(s, url, marker)
                print(f"  {s.name:18} {result}")
    finally:
        for s in strategies:
            await s.aclose()


if __name__ == "__main__":
    asyncio.run(main())

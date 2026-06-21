"""Crawl ANY site at scale -- programmatic equivalent of the `veil crawl` CLI.

This is site-agnostic: swap the seeds + extractor and it works anywhere. The
crawler handles concurrency, polite pacing, proxy rotation, dedupe, streaming
JSONL output, and checkpoint/resume.

Run:  python examples/crawl_any_site.py
"""
import asyncio

from veil import Engine, Politeness, ProxyPool
from veil.crawl import CrawlConfig, Crawler
from veil.extract import css_listings, parse_listings


async def main() -> None:
    engine = Engine(
        proxy_pool=ProxyPool([]),  # add "http://user:pass@host:port" entries to scale
        # Crawler owns pacing, so disable the engine throttle (delay=0).
        # Flip respect_robots=False only for sites you're authorized to crawl.
        politeness=Politeness(respect_robots=True, delay=0.0),
    )

    crawler = Crawler(
        engine,
        CrawlConfig(
            output_path="out.jsonl",
            concurrency=8,
            per_request_delay=0.5,   # + random jitter below
            jitter=0.5,
            checkpoint_path="crawl.checkpoint.json",  # rerun to resume
            max_pages=50,
        ),
        # Skip the cheap HTTP tier on sites you know fingerprint connections:
        # start_strategy="tls_impersonate",
    )

    # --- Option A: paginated search pages, JSON-LD extraction (robust default) ---
    seeds = [f"https://example.com/search?page={n}" for n in range(1, 6)]
    extract = lambda html, url: parse_listings(html)

    # --- Option B: your own CSS selectors (capture from DevTools) ---
    # extract = lambda html, url: css_listings(
    #     html,
    #     card="div.listing-card",
    #     fields={"title": "h2.title", "price": "span.price"},
    # )

    # --- Optional: follow detail links discovered on each page ---
    # import re
    # from urllib.parse import urljoin
    # from veil.extract import soup
    # pat = re.compile(r"/property/\d+")
    # def discover(html, base):
    #     for a in soup(html).find_all("a", href=True):
    #         link = urljoin(base, a["href"])
    #         if pat.search(link):
    #             yield link

    try:
        stats = await crawler.crawl(seeds, extract)  # add `discover` as 3rd arg
        print(stats.line(), "-> out.jsonl")
    finally:
        await engine.aclose()


if __name__ == "__main__":
    asyncio.run(main())

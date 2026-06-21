"""Command-line interface: `veil fetch <url>` and `veil crawl ...`."""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from urllib.parse import urljoin

from veil.engine import Engine
from veil.models import FetchRequest
from veil.politeness import Politeness
from veil.proxies import ProxyPool


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="veil", description="Modular polite web scraper.")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="Fetch a single URL via the cascade engine.")
    f.add_argument("url")
    f.add_argument("--marker", help="Text that must appear for the page to count as real.")
    f.add_argument(
        "--strategies",
        help="Comma-separated subset to use, e.g. 'http_basic,tls_impersonate'.",
    )
    f.add_argument("--proxy", action="append", default=[], help="Proxy URL (repeatable).")
    f.add_argument("--delay", type=float, default=1.0, help="Min seconds between hits/host.")
    f.add_argument(
        "--no-robots",
        action="store_true",
        help="Ignore robots.txt (only for domains you own/are authorized to crawl).",
    )
    f.add_argument("-v", "--verbose", action="store_true")

    _build_crawl_parser(sub)
    return p


def _build_crawl_parser(sub) -> None:
    c = sub.add_parser(
        "crawl",
        help="Crawl many pages of ANY site -> JSONL, with resume + concurrency.",
    )
    # --- where to start ---
    seeds = c.add_argument_group("seeds (use --url-template OR --url)")
    seeds.add_argument(
        "--url-template",
        help="URL with a {page} placeholder, e.g. 'https://site/search?p={page}'.",
    )
    seeds.add_argument("--start", type=int, default=1, help="First page number.")
    seeds.add_argument("--pages", type=int, default=1, help="How many pages from --start.")
    seeds.add_argument("--url", action="append", default=[], help="Explicit seed URL (repeatable).")
    # --- how to extract ---
    ex = c.add_argument_group("extraction")
    ex.add_argument(
        "--extract",
        choices=["jsonld", "css"],
        default="jsonld",
        help="jsonld = schema.org blocks (default, robust); css = your selectors.",
    )
    ex.add_argument("--card", help="[css] selector repeating once per record.")
    ex.add_argument(
        "--field",
        action="append",
        default=[],
        metavar="NAME=SELECTOR",
        help="[css] field to extract within each card (repeatable).",
    )
    # --- link following ---
    c.add_argument(
        "--follow",
        metavar="REGEX",
        help="Enqueue discovered links whose absolute URL matches this regex.",
    )
    # --- engine / pacing / output ---
    c.add_argument("--proxy", action="append", default=[], help="Proxy URL (repeatable).")
    c.add_argument("--proxy-file", help="File with one proxy URL per line.")
    c.add_argument("--start-strategy", help="Begin every fetch at this tier, e.g. tls_impersonate.")
    c.add_argument("--concurrency", type=int, default=8)
    c.add_argument("--delay", type=float, default=0.5, help="Per-worker delay between fetches (s).")
    c.add_argument("--jitter", type=float, default=0.5, help="Random extra delay 0..jitter (s).")
    c.add_argument("--max-pages", type=int, help="Hard cap on total pages fetched.")
    c.add_argument(
        "--no-robots",
        action="store_true",
        help="Ignore robots.txt (only for sites you own/are authorized to crawl).",
    )
    c.add_argument("--out", default="out.jsonl", help="JSONL output path.")
    c.add_argument("--checkpoint", help="Resume file (records progress; rerun to continue).")
    c.add_argument("-v", "--verbose", action="store_true")


async def _fetch(args: argparse.Namespace) -> int:
    engine = Engine(
        proxy_pool=ProxyPool(proxies=args.proxy),
        politeness=Politeness(respect_robots=not args.no_robots, delay=args.delay),
    )
    request = FetchRequest(
        url=args.url,
        success_marker=args.marker,
        strategies=args.strategies.split(",") if args.strategies else None,
    )
    try:
        resp = await engine.fetch(request)
    finally:
        await engine.aclose()

    sys.stderr.write(
        f"[{resp.strategy}] status={resp.status} attempts={resp.attempts} "
        f"bytes={len(resp.text)}\n"
    )
    sys.stdout.write(resp.text)
    return 0 if resp.ok else 1


def _build_seeds(args: argparse.Namespace) -> list[str]:
    seeds = list(args.url)
    if args.url_template:
        seeds += [
            args.url_template.format(page=n)
            for n in range(args.start, args.start + args.pages)
        ]
    if not seeds:
        raise SystemExit("crawl: provide --url-template (+--pages) or --url")
    return seeds


def _build_extract(args: argparse.Namespace):
    if args.extract == "jsonld":
        from veil.extract import parse_listings

        return lambda html, url: parse_listings(html)

    if not args.card:
        raise SystemExit("crawl: --extract css requires --card SELECTOR")
    fields = {}
    for pair in args.field:
        if "=" not in pair:
            raise SystemExit(f"crawl: --field must be NAME=SELECTOR, got '{pair}'")
        name, sel = pair.split("=", 1)
        fields[name.strip()] = sel.strip()
    from veil.extract import css_listings

    return lambda html, url: css_listings(html, card=args.card, fields=fields)


def _build_discover(args: argparse.Namespace):
    if not args.follow:
        return None
    pattern = re.compile(args.follow)
    from veil.extract import soup

    def discover(html: str, base_url: str):
        for a in soup(html).find_all("a", href=True):
            link = urljoin(base_url, a["href"])
            if pattern.search(link):
                yield link

    return discover


def _load_proxies(args: argparse.Namespace) -> list[str]:
    proxies = list(args.proxy)
    if args.proxy_file:
        with open(args.proxy_file, encoding="utf-8") as fh:
            proxies += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    return proxies


async def _crawl(args: argparse.Namespace) -> int:
    from veil.crawl import CrawlConfig, Crawler

    engine = Engine(
        proxy_pool=ProxyPool(proxies=_load_proxies(args)),
        # The crawler owns pacing (per-worker delay), so disable the engine's
        # per-host throttle to let concurrency actually work. Robots still applies.
        politeness=Politeness(respect_robots=not args.no_robots, delay=0.0),
    )
    crawler = Crawler(
        engine,
        CrawlConfig(
            output_path=args.out,
            concurrency=args.concurrency,
            per_request_delay=args.delay,
            jitter=args.jitter,
            checkpoint_path=args.checkpoint,
            max_pages=args.max_pages,
        ),
        start_strategy=args.start_strategy,
    )
    try:
        stats = await crawler.crawl(
            _build_seeds(args), _build_extract(args), _build_discover(args)
        )
    finally:
        await engine.aclose()
    sys.stderr.write(f"done: {stats.line()} -> {args.out}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command == "fetch":
        return asyncio.run(_fetch(args))
    if args.command == "crawl":
        return asyncio.run(_crawl(args))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

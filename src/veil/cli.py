"""Command-line interface: `veil fetch <url>`."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

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
    return p


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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command == "fetch":
        return asyncio.run(_fetch(args))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

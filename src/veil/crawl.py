"""A generic, resumable, concurrent crawler that drives the cascade Engine.

Site-agnostic: you give it seed URLs, an ``extract`` function (html, url -> rows)
and optionally a ``discover`` function (html, url -> more URLs to follow). It
handles concurrency, polite pacing, proxy rotation (via the engine), dedupe,
streaming JSONL output, and checkpoint/resume so a crash or ban never loses
progress.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from veil.engine import Engine
from veil.models import FetchRequest

log = logging.getLogger("veil.crawl")

# (html, url) -> list of record dicts
ExtractFn = Callable[[str, str], list[dict]]
# (html, url) -> iterable of new URLs to enqueue
DiscoverFn = Callable[[str, str], Iterable[str]]
# record -> stable dedupe key
KeyFn = Callable[[dict], str]


@dataclass
class CrawlStats:
    fetched: int = 0
    records: int = 0
    blocked: int = 0
    errors: int = 0
    skipped: int = 0

    def line(self) -> str:
        return (
            f"fetched={self.fetched} records={self.records} "
            f"blocked={self.blocked} errors={self.errors} skipped={self.skipped}"
        )


@dataclass
class CrawlConfig:
    output_path: str
    concurrency: int = 8
    # Pacing per worker, after each fetch: delay + uniform(0, jitter).
    per_request_delay: float = 0.5
    jitter: float = 0.5
    checkpoint_path: Optional[str] = None
    save_every: int = 25
    # Hard cap on number of pages fetched (None = unlimited).
    max_pages: Optional[int] = None


class _Checkpoint:
    """Tracks completed URLs + seen record keys; survives restarts."""

    def __init__(self, path: Optional[str]) -> None:
        self.path = Path(path) if path else None
        self.done: set[str] = set()
        self.seen_keys: set[str] = set()
        self.enqueued: set[str] = set()
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.done = set(data.get("done", []))
            self.seen_keys = set(data.get("seen_keys", []))
            # Anything previously enqueued is at least known; reseed from done.
            self.enqueued = set(self.done)

    def save(self) -> None:
        if not self.path:
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"done": sorted(self.done), "seen_keys": sorted(self.seen_keys)}
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)  # atomic on the same filesystem


def _default_key(record: dict) -> str:
    # Dedupe on the full record content. Keying on a single field like "url" is
    # wrong when one page yields many records that share a link (e.g. quotes that
    # all link to the same author page) -- it silently drops real rows. Pass a
    # custom key_fn to Crawler if you want id/url-based dedupe instead.
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


class Crawler:
    def __init__(
        self,
        engine: Engine,
        config: CrawlConfig,
        *,
        key_fn: KeyFn = _default_key,
        start_strategy: Optional[str] = None,
    ) -> None:
        self.engine = engine
        self.cfg = config
        self.key_fn = key_fn
        # Optional: force every request to begin at a given tier (e.g. skip the
        # cheap http_basic on a site you know fingerprints connections).
        self.start_strategy = start_strategy

        self.stats = CrawlStats()
        self._cp = _Checkpoint(config.checkpoint_path)
        self._queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._out_lock = asyncio.Lock()
        self._out = None
        self._since_save = 0

    async def crawl(
        self,
        seeds: Iterable[str],
        extract: ExtractFn,
        discover: Optional[DiscoverFn] = None,
    ) -> CrawlStats:
        Path(self.cfg.output_path).parent.mkdir(parents=True, exist_ok=True)
        # Append mode so a resumed run keeps prior output.
        self._out = open(self.cfg.output_path, "a", encoding="utf-8")
        try:
            for url in seeds:
                self._enqueue(url)
            workers = [
                asyncio.create_task(self._worker(extract, discover))
                for _ in range(self.cfg.concurrency)
            ]
            await self._queue.join()
            for _ in workers:
                self._queue.put_nowait(None)  # poison pills
            await asyncio.gather(*workers, return_exceptions=True)
        finally:
            self._cp.save()
            self._out.flush()
            self._out.close()
        log.info("crawl finished: %s", self.stats.line())
        return self.stats

    def _enqueue(self, url: str) -> None:
        if not url or not url.startswith(("http://", "https://")):
            return
        if url in self._cp.enqueued or url in self._cp.done:
            return
        if self.cfg.max_pages and len(self._cp.enqueued) >= self.cfg.max_pages:
            return
        self._cp.enqueued.add(url)
        self._queue.put_nowait(url)

    async def _worker(self, extract: ExtractFn, discover: Optional[DiscoverFn]) -> None:
        while True:
            url = await self._queue.get()
            if url is None:
                self._queue.task_done()
                return
            try:
                await self._process(url, extract, discover)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors += 1
                log.warning("error on %s: %s", url, exc)
            finally:
                self._cp.done.add(url)
                self._maybe_save()
                self._queue.task_done()
                # Polite pacing per worker (combined across N workers = N/delay rate).
                await asyncio.sleep(
                    self.cfg.per_request_delay + random.uniform(0, self.cfg.jitter)
                )

    async def _process(
        self, url: str, extract: ExtractFn, discover: Optional[DiscoverFn]
    ) -> None:
        request = FetchRequest(
            url=url,
            strategies=[self.start_strategy] if self.start_strategy else None,
        )
        try:
            resp = await self.engine.fetch(request)
        except Exception:
            self.stats.blocked += 1
            raise
        self.stats.fetched += 1

        rows = extract(resp.text, resp.url)
        new = 0
        for row in rows:
            key = self.key_fn(row)
            if key in self._cp.seen_keys:
                self.stats.skipped += 1
                continue
            self._cp.seen_keys.add(key)
            await self._write(row)
            new += 1
        self.stats.records += new
        log.info("[%s] %s -> %d new rows", resp.strategy, url, new)

        if discover:
            for link in discover(resp.text, resp.url):
                self._enqueue(link)

    async def _write(self, row: dict) -> None:
        async with self._out_lock:
            self._out.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _maybe_save(self) -> None:
        self._since_save += 1
        if self._since_save >= self.cfg.save_every:
            self._cp.save()
            if self._out:
                self._out.flush()
            self._since_save = 0

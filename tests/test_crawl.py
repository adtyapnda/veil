"""Crawler tests using a fake engine -- no network, no sleeps that matter."""
from __future__ import annotations

import json

import pytest

from veil.crawl import CrawlConfig, Crawler
from veil.models import FetchRequest, FetchResponse


class FakeEngine:
    """Serves canned HTML keyed by URL and records what was fetched."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.fetched: list[str] = []

    async def fetch(self, request):
        url = request.url if isinstance(request, FetchRequest) else request
        self.fetched.append(url)
        if url not in self.pages:
            raise RuntimeError(f"404 {url}")
        return FetchResponse(url=url, status=200, text=self.pages[url], strategy="fake")

    async def aclose(self):
        pass


def _rows_extract(html, url):
    # Each "page" is a JSON list of record dicts for test simplicity.
    return json.loads(html)


def _read_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture
def fast_cfg(tmp_path):
    return CrawlConfig(
        output_path=str(tmp_path / "out.jsonl"),
        concurrency=4,
        per_request_delay=0.0,
        jitter=0.0,
    )


async def test_crawl_writes_all_records(tmp_path, fast_cfg):
    pages = {
        "https://s/1": json.dumps([{"url": "https://i/a"}, {"url": "https://i/b"}]),
        "https://s/2": json.dumps([{"url": "https://i/c"}]),
    }
    engine = FakeEngine(pages)
    crawler = Crawler(engine, fast_cfg)

    stats = await crawler.crawl(list(pages), _rows_extract)

    rows = _read_jsonl(tmp_path / "out.jsonl")
    assert stats.fetched == 2
    assert stats.records == 3
    assert {r["url"] for r in rows} == {"https://i/a", "https://i/b", "https://i/c"}


async def test_crawl_dedupes_records(tmp_path, fast_cfg):
    pages = {
        "https://s/1": json.dumps([{"url": "https://i/dup"}]),
        "https://s/2": json.dumps([{"url": "https://i/dup"}, {"url": "https://i/new"}]),
    }
    crawler = Crawler(FakeEngine(pages), fast_cfg)
    stats = await crawler.crawl(list(pages), _rows_extract)

    assert stats.records == 2  # dup counted once
    assert stats.skipped == 1


async def test_crawl_follows_discovered_links(tmp_path, fast_cfg):
    pages = {
        "https://s/index": json.dumps([{"url": "https://i/seed"}]),
        "https://s/next": json.dumps([{"url": "https://i/followed"}]),
    }
    engine = FakeEngine(pages)
    crawler = Crawler(engine, fast_cfg)

    def discover(html, url):
        if url == "https://s/index":
            return ["https://s/next"]
        return []

    stats = await crawler.crawl(["https://s/index"], _rows_extract, discover)
    assert "https://s/next" in engine.fetched
    assert stats.fetched == 2


async def test_checkpoint_resume_skips_done(tmp_path):
    cp = tmp_path / "cp.json"
    cfg = CrawlConfig(
        output_path=str(tmp_path / "out.jsonl"),
        concurrency=2,
        per_request_delay=0.0,
        jitter=0.0,
        checkpoint_path=str(cp),
    )
    pages = {"https://s/1": json.dumps([{"url": "https://i/a"}])}

    # First run completes the page.
    e1 = FakeEngine(pages)
    await Crawler(e1, cfg).crawl(["https://s/1"], _rows_extract)
    assert e1.fetched == ["https://s/1"]

    # Second run with same checkpoint should skip the already-done URL.
    e2 = FakeEngine(pages)
    await Crawler(e2, cfg).crawl(["https://s/1"], _rows_extract)
    assert e2.fetched == []  # nothing re-fetched

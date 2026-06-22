# veil

[![CI](https://github.com/adtyapnda/veil/actions/workflows/ci.yml/badge.svg)](https://github.com/adtyapnda/veil/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

A modular, **polite** web scraper that *cascades* through fetch strategies —
from a near-free HTTP request up to a full stealth browser — and stops at the
cheapest one that actually returns the page.

Most scrapers either send a naive `requests.get()` (and get blocked) or fire up
a heavy headless browser for *everything* (slow and expensive). `veil` picks the
lightest tool that works, per site, automatically.

```
                 ┌─────────────────────────────────────────────┐
 fetch(url) ───► │  politeness gate (robots.txt + rate limit)   │
                 └───────────────────────┬─────────────────────┘
                                         ▼
        cheapest ──► http_basic ──► tls_impersonate ──► browser ──► heaviest
        (httpx)        (curl_cffi JA3/HTTP2)        (Playwright + stealth)
                                         │
                            escalates only when a tier
                            returns a block/challenge page
```

## Quick start

Needs Python 3.9+. Install the full tool straight from GitHub:

```bash
pip install "veil-scraper[all] @ git+https://github.com/adtyapnda/veil"
playwright install chromium   # only needed for the browser tier
```

> Just want the light version (plain HTTP, no browser)?
> `pip install "git+https://github.com/adtyapnda/veil"`

Then use the `veil` command:

```bash
# fetch one page (auto-picks the cheapest tier that works)
veil fetch https://example.com

# crawl many pages to a file, resumable if it stops
veil crawl --url-template "https://example.com/search?page={page}" \
  --pages 50 --out results.jsonl --checkpoint run.ckpt
```

Or from Python:

```python
import asyncio
from veil import Engine

async def main():
    engine = Engine()
    resp = await engine.fetch("https://example.com")
    print(resp.strategy, resp.status, len(resp.text))
    await engine.aclose()

asyncio.run(main())
```

Prefer to read/modify the code? Clone instead: `git clone https://github.com/adtyapnda/veil`
then `pip install -e ".[all]"` (see [Install](#install) and [CONTRIBUTING.md](CONTRIBUTING.md)).

## Why it's structured this way

| Tier | Backend | Beats | Cost |
|------|---------|-------|------|
| `http_basic` | `httpx` + realistic headers | naive header filters | ~free |
| `tls_impersonate` | `curl_cffi` | TLS/JA3 + HTTP2 fingerprinting | low |
| `browser` | Playwright + stealth | JS challenges, behavioral checks | high |

Cross-cutting concerns wrap **every** tier:

- **Proxy pool** — round-robin rotation with per-proxy health/cooldown.
- **Politeness** — robots.txt compliance + per-host rate limiting + exponential
  backoff on transient errors.

Each tier is a `Strategy` subclass, so adding your own (e.g. a CAPTCHA-solver
hook, or an alternate impersonation library) is one small file.

## What it beats (and what it doesn't)

Measured by [`examples/battletest.py`](examples/battletest.py), which probes each
tier against real targets. Honest results, not marketing:

| Target | http_basic | tls_impersonate | browser |
|--------|:---------:|:--------------:|:-------:|
| Plain site (control) | ✅ | ✅ | ✅ |
| Cloudflare **JS challenge** (nowsecure.nl) | ✅ | ✅ | ✅ |
| Bot fingerprint test (bot.sannysoft.com) | ✅ | ✅ | ✅ |
| Reputation **hard-block 403** (scrapingcourse antibot) | ❌ | ❌ | ❌ |

**The key distinction:**

- **JS challenges** (`200`/`503` + a small page that runs script to test you) —
  `veil` handles these. The browser tier executes the challenge; lighter tiers
  often pass on header/TLS realism alone.
- **Reputation hard-blocks** (`403` served *before* any JavaScript runs) — `veil`
  **cannot** fix these with code. The block is decided at Cloudflare's edge from
  your **IP reputation** + connection signals, so in-page stealth never executes.
  The only lever is a better egress IP: plug **residential/mobile proxies** into
  the `ProxyPool` (`--proxy-file`). That's infrastructure, not evasion code.

In short: `veil` does everything the *software* side can do (TLS realism,
JS-challenge solving, anti-detection browser). Beating an IP-reputation `403`
is a question of proxy quality, not more scraper cleverness.

## Install

```bash
# Base (http_basic only) -- light, pure-Python deps
pip install -e .

# Add TLS fingerprint impersonation
pip install -e ".[tls]"

# Add the stealth browser tier
pip install -e ".[browser]"
playwright install chromium

# Everything + dev tools
pip install -e ".[all,dev]"
```

Optional tiers degrade gracefully: if `curl_cffi` or Playwright isn't installed,
the engine simply skips that tier instead of crashing.

## Usage

### CLI

```bash
# Cascade automatically, print the page to stdout
veil fetch https://example.com --marker "Example Domain"

# Force a subset of strategies
veil fetch https://example.com --strategies http_basic,tls_impersonate

# Rotate through proxies, 2s between hits per host
veil fetch https://example.com --proxy http://a:8080 --proxy http://b:8080 --delay 2
```

### Library

```python
import asyncio
from veil import Engine, FetchRequest, Politeness, ProxyPool

async def main():
    engine = Engine(
        proxy_pool=ProxyPool(["http://user:pass@host:port"]),
        politeness=Politeness(respect_robots=True, delay=1.0),
    )
    resp = await engine.fetch(
        FetchRequest(url="https://example.com", success_marker="Example Domain")
    )
    print(resp.strategy, resp.status, len(resp.text))
    await engine.aclose()

asyncio.run(main())
```

## Crawling at scale (any site)

`veil fetch` is one URL. `veil crawl` is **many pages of any site** — concurrent,
resumable, streaming to JSONL, with dedupe and proxy rotation. Extraction defaults
to JSON-LD / schema.org (stable across redesigns); drop to CSS selectors when a
site doesn't expose structured data.

```bash
# Paginated search, JSON-LD extraction, 8 workers, resumable
veil crawl \
  --url-template "https://example.com/search?page={page}" \
  --pages 50 \
  --concurrency 8 --delay 0.5 --jitter 0.5 \
  --out listings.jsonl --checkpoint crawl.ckpt

# Custom CSS selectors (capture the repeating card + fields from DevTools)
veil crawl \
  --url-template "https://example.com/list?p={page}" --pages 20 \
  --extract css --card "div.listing-card" \
  --field "title=h2.title" --field "price=span.price" \
  --out out.jsonl

# Follow detail links matching a regex, scale across many proxies
veil crawl --url "https://example.com/index" \
  --follow "/property/\d+" \
  --proxy-file proxies.txt --concurrency 16 \
  --out out.jsonl --checkpoint crawl.ckpt
```

**Resume:** if a run is interrupted (crash, ban, Ctrl-C), rerun the *same command*
with the same `--checkpoint` — completed URLs and already-seen records are skipped.

Pacing is owned by the crawler (`--delay` + `--jitter`, per worker), so effective
request rate ≈ `concurrency / delay`. Tune down for politeness, add proxies to scale
up. See [examples/crawl_any_site.py](examples/crawl_any_site.py) for the library API.

> Robots is respected by default here too. `--no-robots` exists for sites you own
> or are authorized to crawl; using it elsewhere is on you (see Responsible use).

## Extending: write your own strategy

```python
from veil.strategies.base import Strategy
from veil.models import FetchResponse

class MyStrategy(Strategy):
    name = "my_strategy"
    cost = 50  # where it sits in the cascade (lower = tried earlier)

    async def fetch(self, request, *, proxy=None):
        ...  # return a FetchResponse or raise

# engine = Engine(strategies=[HttpBasicStrategy(), MyStrategy(), ...])
```

## Tests

```bash
pytest          # engine logic is fully tested with fake strategies (no network)
```

## Contributing

This is a learning-friendly project and **contributions are welcome** — including
from people new to Python. See [CONTRIBUTING.md](CONTRIBUTING.md) to get set up,
and [GOOD_FIRST_ISSUES.md](GOOD_FIRST_ISSUES.md) for well-scoped starter tasks
(each names the files to touch and a hint). New strategies, parsers, docs, and
tests are all fair game.

## ⚖️ Responsible use

This tool is for collecting **publicly accessible** data you're allowed to
collect — price monitoring, academic research, archiving, accessibility, etc.

- `respect_robots=True` is the **default**. Turn it off only for domains you own
  or are explicitly authorized to crawl.
- Rate limiting is on by default. Don't remove it to hammer a site — that's
  abusive and may be illegal (e.g. degrading a service).
- Respect each site's Terms of Service and applicable law (CFAA, GDPR, copyright,
  database rights). Scraping personal data or copyrighted content can carry
  legal risk regardless of what this tool *can* do.
- Do **not** use `veil` to bypass authentication, paywalls, or access controls
  on content you aren't entitled to.

You are responsible for how you use it. See [LICENSE](LICENSE) (MIT, no warranty).

## Roadmap

- [ ] Per-domain strategy memory (remember which tier worked, skip the cheap ones)
- [ ] Pluggable CAPTCHA-solver hook
- [ ] Concurrent crawl queue with per-host concurrency caps
- [ ] Response caching layer
- [ ] Metrics/observability (success rate per strategy & proxy)
```

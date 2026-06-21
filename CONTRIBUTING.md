# Contributing to veil

Thanks for considering a contribution! This is a learning-friendly project —
beginners are genuinely welcome, and "I'm not sure if this is right" PRs are fine.
If anything here is unclear, open an issue and ask.

## Getting set up

```bash
# 1. Fork on GitHub, then clone your fork
git clone https://github.com/<your-username>/veil
cd veil

# 2. Create a virtual environment
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

# 3. Install everything (all strategies + dev tools)
pip install -e ".[all,dev]"
playwright install chromium   # only needed for the browser strategy
```

## Running the checks

Two things must pass before a PR is merged — the same two CI runs:

```bash
pytest -q          # tests (most don't need network)
ruff check src tests   # lint
```

If `ruff` flags something, `ruff check --fix src tests` fixes most of it.

## How the project is laid out

```
src/veil/
  engine.py            # the cascade: tries strategies cheapest-first, escalates
  models.py            # FetchRequest / FetchResponse data types
  cli.py               # `veil fetch` and `veil crawl`
  strategies/
    base.py            # the Strategy interface + shared block detection
    http_basic.py      # tier 1: httpx
    tls_impersonate.py # tier 2: curl_cffi (JA3/HTTP2)
    browser.py         # tier 3: Playwright + stealth
  proxies/pool.py      # rotating proxy pool with health/cooldown
  politeness/throttle.py  # robots.txt + per-host rate limiting
  crawl.py             # resumable concurrent crawler -> JSONL
  extract.py           # JSON-LD + CSS extraction helpers
tests/                 # pytest; use fakes, avoid real network where possible
examples/              # runnable demos
```

## Adding a new fetch strategy (the main extension point)

A strategy is one small file implementing `Strategy.fetch`. Example skeleton:

```python
from veil.strategies.base import Strategy
from veil.models import FetchResponse

class MyStrategy(Strategy):
    name = "my_strategy"
    cost = 50  # where it sits in the cascade (lower = tried earlier)

    async def fetch(self, request, *, proxy=None):
        # ... do the fetch ...
        return FetchResponse(url=..., status=..., text=..., strategy=self.name)
```

Then register it in `strategies/__init__.py` and (optionally) the default list in
`engine.py`. Add a test that uses a fake/mock rather than a live site.

## Submitting a PR

1. Branch off `main`: `git checkout -b my-change`
2. Make your change + add/adjust a test
3. Run `pytest -q` and `ruff check src tests`
4. Commit, push to your fork, open a PR describing **what** and **why**

Small, focused PRs are easier to review and much more likely to be merged. If
you're picking up a task from [GOOD_FIRST_ISSUES.md](GOOD_FIRST_ISSUES.md),
mention which one in the PR.

## Style

- Match the surrounding code; keep comments about *why*, not *what*.
- Prefer standard library + existing deps over adding new ones (ask first for new deps).
- Be kind in reviews. Everyone here is learning something.

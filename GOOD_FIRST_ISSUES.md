# Good first issues

Beginner-friendly, well-scoped tasks. Each names the file(s) to touch and a hint
to get you started. Pick one, comment on the matching GitHub issue (or open one),
and see [CONTRIBUTING.md](CONTRIBUTING.md) for setup. Difficulty: 🟢 easy ·
🟡 medium · 🔴 involved.

---

### 1. 🟢 Add CSV output to the crawler
**Files:** `src/veil/crawl.py`, `src/veil/cli.py`
Right now the crawler only writes JSONL. Add a `--format jsonl|csv` flag. For CSV,
collect field names from the first record (or a `--columns` list) and write rows
with `csv.DictWriter`.
*Hint:* the write path is `Crawler._write`; thread the format through `CrawlConfig`.

### 2. 🟢 Rotate User-Agents in the http_basic tier
**Files:** `src/veil/strategies/http_basic.py`
A single hard-coded UA is easy to fingerprint. Add a small pool of realistic
desktop UAs and pick one per request (`random.choice`). Bonus: let the caller
pass their own list.
*Hint:* `_DEFAULT_HEADERS["User-Agent"]` is the spot.

### 3. 🟢 Make block-detection signals configurable
**Files:** `src/veil/strategies/base.py`
The challenge-page signals in `looks_blocked` are hard-coded. Move them to a
class attribute (e.g. `BLOCK_SIGNALS`) so users can extend/override them for a
specific site without editing the method.
*Hint:* keep the size guard (`CHALLENGE_PAGE_MAX_BYTES`) behavior intact; add a test.

### 4. 🟡 Add a `--max-records` stop condition
**Files:** `src/veil/crawl.py`, `src/veil/cli.py`
Let a crawl stop cleanly once it has written N new records (useful for sampling).
Track a counter in the crawler and stop enqueuing / draining once hit.
*Hint:* `CrawlConfig` already has `max_pages`; mirror that for records.

### 5. 🟡 Parse `Retry-After` for smarter backoff
**Files:** `src/veil/engine.py`, maybe `src/veil/strategies/base.py`
When a server returns `429`/`503` with a `Retry-After` header, honor it instead
of the fixed exponential backoff.
*Hint:* the response headers are on `FetchResponse.headers`; read it where the
engine decides to escalate/retry.

### 6. 🟡 Build a sitemap reader
**Files:** new `src/veil/sitemap.py`, a test, an example
Many sites expose `/sitemap.xml` (sometimes a sitemap *index* pointing to more
XML files, sometimes gzipped). Add a helper that fetches a sitemap via the Engine
and yields all the URLs, so the crawler can seed from it.
*Hint:* `xml.etree.ElementTree` for parsing; handle the `<sitemapindex>` vs
`<urlset>` cases and `.xml.gz` via `gzip`.

### 7. 🔴 Per-domain strategy memory
**Files:** `src/veil/engine.py`
After the cascade finds a working tier for a host, remember it and try that tier
*first* next time (skipping the cheap ones you know get blocked). A simple
`dict[host -> strategy_name]` is enough to start.
*Hint:* key by `urlparse(url).netloc`; update it on success in `Engine.fetch`.

### 8. 🔴 Track success metrics per strategy & proxy
**Files:** `src/veil/engine.py`, maybe a new `src/veil/metrics.py`
Count attempts/successes/blocks per strategy and per proxy, and expose a summary
(e.g. `engine.stats()`). Helps users see which tier/proxy actually works for a site.
*Hint:* the engine already knows the outcome of each attempt — accumulate it.

---

Don't see your idea here? Open an issue and propose it — new strategies, parsers,
docs, and tests are all welcome.

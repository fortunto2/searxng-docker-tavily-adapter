# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

This is a **SearXNG Docker Tavily Adapter** - a free Tavily API replacement using SearXNG. The system consists of:

- **SearXNG** (port 8999) - Meta-search engine that aggregates results from Google, DuckDuckGo, Brave, etc.
- **Tavily Adapter** (port 8000) - FastAPI service that provides Tavily-compatible API interface
- **Solograph Search** (port 8002) - Semantic vector search over ProductHunt (26k+ products, FalkorDB)
- **Redis/Valkey** - Caching layer for SearXNG
- **Unified Configuration** - Single `config.yaml` file configures all services

### Key Components

- `simple_tavily_adapter/` - FastAPI adapter service (Python)
  - `main.py` - FastAPI application: `/search`, `/extract`, `/transcript`, `/health`
  - `engine_selector.py` - smart engine routing per query type (ours, not upstream)
  - `tavily_client.py` - Drop-in replacement for Tavily Python client
  - `config_loader.py` - YAML config parsing
- `searxng/engines/` - Custom SearXNG engines
  - `sources_local.py` - Generic engine for Solograph vector search (ProductHunt, YouTube, etc.)
  - `reddit.py` - PullPush backend (fixes Reddit 403)
  - `reddit_api.py` - Reddit OAuth API engine
- `docker-compose.yaml` - Multi-service orchestration
- `config.yaml` - Unified configuration for SearXNG + adapter
- `Caddyfile` - Reverse proxy configuration

## Essential Commands

### Setup & Configuration
```bash
# Initial setup (required)
cp config.example.yaml config.yaml
# Edit config.yaml and change server.secret_key (minimum 32 chars)

# Start all services
docker compose up -d

# View logs
docker compose logs tavily-adapter
docker compose logs searxng

# Stop services
docker compose down
```

### Development Commands
```bash
# Local development of adapter
cd simple_tavily_adapter
pip install -r requirements.txt
python main.py

# Run adapter tests
python test_client.py

# Health checks
curl -f http://localhost:8000/health
curl "http://localhost:8999/search?q=test&format=json"

# Test API endpoint
curl -X POST "http://localhost:8000/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "test query", "max_results": 3}'
```

### Generate Secret Key (Required)
```bash
# For config.yaml server.secret_key
python3 -c "import secrets; print(secrets.token_hex(32))"
# or
openssl rand -hex 32
```

## Configuration Notes

- **Critical**: Must change `server.secret_key` in `config.yaml` (32+ characters)
- SearXNG and Adapter share the same `config.yaml` file
- SearXNG config is at root level, Adapter config under `adapter:` section
- Adapter connects to SearXNG via internal Docker network: `http://searxng:8080`

## Endpoints

| Endpoint | What |
|---|---|
| `POST /search` | Tavily-compatible search. `include_raw_content` scrapes each result |
| `POST /extract` | One page as markdown. `size`: `s`=5k, `m`=10k, `l`=25k chars, `f`=full. Reports `source`: `negotiated` or `extracted` |
| `GET /extract/{id}/{page}` | Page N of a `size=f` extraction (cached 30 min) |
| `POST /transcript` | YouTube captions as text (ours, not upstream) |
| `GET /health` | Health check |

### Markdown content negotiation — tried before any conversion

`/extract` and the `/search` scraper ask for `text/markdown` ahead of html. A site
that implements negotiation then serves its own authored markdown, which beats any
extraction and is far smaller: visayes.app returns 8.3k chars against 51 KB of HTML,
and developers.cloudflare.com returns a more complete page than trafilatura recovers
from its HTML (5332 vs 2635 chars). Confirmed working on visayes.app, rustman.org and
developers.cloudflare.com.

`served_markdown()` decides. `text/markdown` is taken at face value. `text/plain` is
only trusted when `Vary` carries an `accept` token, because rustman.org negotiates but
labels its markdown `text/plain` — and **`Vary` must be parsed as a token list, not by
substring**: `Vary: Accept-Encoding` ships with nearly every gzip response and contains
"accept", which would mark every plain-text file as markdown.

The `/extract` response reports which path ran in `source`: `negotiated` or `extracted`.

### Markdown conversion — two converters, picked per document

`html_to_markdown()` tries trafilatura first and falls back to markdownify over an
nh3-sanitized soup. This is not belt-and-braces, both cases happen:

- trafilatura wins on articles. It drops nav, ads and footers by structure, which
  stripping tags by name cannot do, and it keeps tables.
- trafilatura's markdown writer degrades to flat text on small or atypical
  documents: no headings, no bold, no links, no list bullets. Verified against a
  10-line test page (`test_extract.py::test_small_document_keeps_markdown_formatting`).

So trafilatura's output is accepted only when it actually contains markdown markers.
Do not "simplify" this to a single converter.

**`Brotli` is a required dependency, not an optional one.** The scrape headers
advertise `Accept-Encoding: ... br`; without it aiohttp raises
`ClientResponseError: Can not decode content-encoding: brotli`, and because
`fetch_raw_content` swallows exceptions, raw content came back empty for every
brotli-serving site with no error anywhere.

## Reddit: every API path is closed, use a browser

Checked 2026-08-23, all four:

| Path | State |
|---|---|
| `reddit` engine (PullPush) | Works when PullPush lets you in. Free community API, rate-limits by IP and returns 429 under any real use. Also 403s a `Python-urllib` User-Agent while accepting curl, a browser, or none |
| `reddit.com/search.json` | 403, even from a residential IP. Reddit fingerprints, it is not just datacenter ranges |
| `old.reddit.com/search` | 302 to a login page |
| `reddit api` (OAuth) | 401 without credentials, and SearXNG runs an explicitly named engine even when the config disables it |

What works is `www.reddit.com/search/?q=...` in a real browser (Playwright MCP),
which returns results with no login. Pull the posts out of the DOM by matching
`a[href*="/comments/"]` and reading `/r/(sub)/comments/(id)`. Use PullPush when it
answers, since it gives score, comment count and selftext that the search page
does not, and fall back to the browser.

## MCP server

`searxng_mcp/` exposes `web_search`, `web_extract` and `youtube_transcript` over MCP.
It depends on `mcp` and `httpx` and nothing else.

Kept separate from the solograph MCP server on purpose, from two incidents: a broken
import in solograph took all 16 of its tools down at once, search included, and
solograph is registered per-project so sessions in other repos had no search at all.

```bash
uv run --project searxng_mcp searxng-mcp     # stdio
```

Register it as `searxng`, so tools resolve as `mcp__searxng__web_search`.

## Upstream

Fork of [vakovalskii/searcharvester](https://github.com/vakovalskii/searcharvester),
which rewrote itself from scratch as Searcharvester 2.0 in April 2026. There is no
shared git history with that rewrite, so no merge or cherry-pick path exists; changes
move by hand. `/extract` was ported that way.

Ours keeps what upstream dropped: `engine_selector.py`, the Reddit PullPush and OAuth
engines, `sources_local.py` for solograph vector search, `/transcript`, and the curated
30-engine config. Upstream's `/research` (Hermes multi-agent orchestrator) was
deliberately not taken: it needs an LLM API key and a Hermes runtime to do what a
coding agent already does.

## API Compatibility

The adapter provides 100% Tavily API compatibility:
- Same request/response format
- Drop-in replacement for `tavily-python` client
- Supports `include_raw_content` with web scraping
- No API keys required (ignored if provided)

## Web Scraping Feature

When `include_raw_content: true`:
1. SearXNG returns search results with URLs
2. Adapter scrapes each URL in parallel
3. HTML goes through `html_to_markdown()` (see above)
4. Content is truncated to `adapter.scraper.max_content_length` and returned in `raw_content`

Scraping timeout and limits configured in `config.yaml` under `adapter.scraper`.
For a single page read in full, use `POST /extract` instead: same conversion, but
sized and paginated rather than truncated.
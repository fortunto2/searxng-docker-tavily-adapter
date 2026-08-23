#!/usr/bin/env python3
"""SearXNG MCP server — web search and page extraction for coding agents.

Deliberately separate from the solograph MCP server. Two reasons, both from
incidents: solograph's import broke once and took every one of its 16 tools down
with it, search included; and solograph is registered per-project, so sessions in
other repos had no search at all. This server needs httpx and nothing else, so it
starts anywhere and stays up when the graph does not.

Talks to the Tavily-compatible adapter (this repo's `simple_tavily_adapter`).

Environment:
  TAVILY_API_URL — adapter base URL (default: http://localhost:8013)
  TAVILY_API_KEY — bearer token; ignored by the self-hosted adapter

Run:
  uv run --project /path/to/this/repo searxng-mcp
"""

import os

import httpx
from mcp.server import MCPServer

mcp = MCPServer("searxng")

API_URL = os.environ.get("TAVILY_API_URL", "http://localhost:8013").rstrip("/")
API_KEY = os.environ.get("TAVILY_API_KEY", "")

_DOWN = (
    f"No adapter at {API_URL}. Start it with `make search-up`, or point "
    f"TAVILY_API_URL somewhere else."
)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


async def _post(client: httpx.AsyncClient, path: str, payload: dict) -> dict:
    try:
        resp = await client.post(f"{API_URL}{path}", json=payload, headers=_headers())
    except httpx.ConnectError:
        return {"error": "Adapter unreachable", "detail": _DOWN}
    except httpx.TimeoutException:
        return {"error": "Adapter timed out", "detail": f"POST {path}"}
    if resp.status_code != 200:
        return {"error": f"{path} returned {resp.status_code}", "detail": resp.text[:500]}
    return resp.json()


@mcp.tool()
async def web_search(
    query: str,
    max_results: int = 10,
    engines: str | None = None,
    include_raw_content: bool = False,
) -> dict:
    """Search the web via SearXNG, with smart engine routing.

    Engines are auto-selected from the query. Groups:
      academic — arxiv, google scholar (research, paper, algorithm)
      tech     — github, stackoverflow (python, react, code, framework)
      product  — brave, reddit, app stores (app, competitor, pricing, vs)
      news     — google news, hacker news (news, latest, trend)
      general  — duckduckgo, google cse, brave, reddit (default)

    Google direct usually answers with a CAPTCHA and gets suspended; duckduckgo and
    google cse carry general queries. The specialist engines are reliable.

    The response carries "unresponsive_engines" as [name, reason] pairs whenever an
    engine was banned or timed out for this query. Read it before concluding that a
    zero-result answer means the subject does not exist.

    Args:
        query: Search query. For engines="reddit" keep it to 3 keywords or fewer,
            the Reddit backend returns nothing for longer ones.
        max_results: Number of results (default 10)
        engines: Override routing, e.g. "reddit", "github", "arxiv,google scholar"
        include_raw_content: Also scrape each result. For reading ONE page prefer
            web_extract: it is sized, paginated and cached rather than truncated.
    """
    payload: dict = {
        "query": query,
        "max_results": max_results,
        "include_raw_content": include_raw_content,
    }
    if engines:
        payload["engines"] = engines
    async with httpx.AsyncClient(timeout=60) as client:
        data = await _post(client, "/search", payload)

    # An empty result list plus suspended engines is a ban, not an absence. Say so,
    # otherwise the caller concludes the subject does not exist and moves on.
    down = data.get("unresponsive_engines") or []
    if down and not data.get("results"):
        names = ", ".join(f"{e[0]} ({e[1]})" for e in down if e)
        data["hint"] = (
            f"No results, and every engine asked for is unavailable: {names}. "
            "Suspensions here last 2-10 minutes, so retry shortly, or pass "
            "engines= with a different set (github, stackoverflow, hackernews, "
            "arxiv, youtube and google cse are rarely blocked)."
        )
    return data


@mcp.tool()
async def web_extract(url: str, size: str = "m", page: int = 1) -> dict:
    """Read one page as clean markdown, sized to a context budget.

    The adapter runs the page through trafilatura, which drops navigation, ads and
    footers by structure and keeps tables, headings and links. Prefer this over a
    plain fetch for articles and documentation.

    Many docs sites now serve their own markdown when asked for it (visayes.app,
    rustman.org, developers.cloudflare.com). The adapter negotiates that first, so
    the result is the site's authored prose at a fraction of the size instead of an
    extraction guess. The response's "source" field says which happened:
    "negotiated" or "extracted".

    Extractions are cached server-side for 30 minutes, so paging costs no refetch.

    Args:
        url: Page to read
        size: "s" 5000 chars, "m" 10000 (default), "l" 25000, "f" whole document
            paginated at 25000 per page
        page: Page number, only meaningful with size="f". Page 1 reports
            pages.total and pages.next when more remain.
    """
    if size not in ("s", "m", "l", "f"):
        return {"error": f"size must be s, m, l or f (got {size!r})"}
    if page < 1:
        return {"error": f"page must be >= 1 (got {page})"}

    async with httpx.AsyncClient(timeout=90) as client:
        data = await _post(client, "/extract", {"url": url, "size": size})
        if "error" in data or page == 1:
            return data

        # Paging is a second call against the cached extraction.
        try:
            resp = await client.get(
                f"{API_URL}/extract/{data['id']}/{page}", headers=_headers()
            )
        except httpx.ConnectError:
            return {"error": "Adapter unreachable", "detail": _DOWN}
        if resp.status_code != 200:
            return {
                "error": f"page {page} returned {resp.status_code}",
                "detail": resp.text[:500],
            }
        return resp.json()


@mcp.tool()
async def youtube_transcript(
    video_id: str,
    languages: list[str] | None = None,
    max_length: int = 5000,
) -> dict:
    """Fetch a YouTube video's captions as plain text.

    Args:
        video_id: Video id ("dQw4w9WgXcQ") or a full YouTube URL
        languages: Preferred caption languages in order (default ["en", "ru"])
        max_length: Truncate the transcript to this many chars (default 5000)
    """
    payload = {
        "video_id": video_id,
        "languages": languages or ["en", "ru"],
        "max_length": max_length,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        return await _post(client, "/transcript", payload)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

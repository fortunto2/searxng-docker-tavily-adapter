"""Tests for /extract and the two-converter markdown path.

Offline: every test drives an aiohttp mock server, so these run in CI without
network access. Run: uv run --with pytest --with pytest-asyncio python -m pytest test_extract.py
"""
import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi.testclient import TestClient
from tavily_client import TavilyResponse

import main
from main import (
    PAGE_SIZE,
    SIZE_LIMITS,
    _build_extract_response,
    _extract_id,
    _extract_url,
    app,
    fetch_raw_content,
    html_to_markdown,
    needs_html_conversion,
    negotiated_markdown,
)

# A small document. trafilatura's markdown writer flattens these to plain text,
# so it is the case that must fall through to markdownify.
SMALL_HTML = """<!DOCTYPE html><html><head><title>Test Page</title></head><body>
<h1>Main Title</h1>
<p>This is a <strong>test</strong> paragraph with <em>emphasis</em>.</p>
<h2>Subtitle</h2>
<ul><li>Item 1</li><li>Item 2 with <a href="https://example.com">link</a></li></ul>
<script>alert('x');</script></body></html>"""

# An article-shaped document wrapped in chrome. trafilatura should drop the
# chrome; markdownify would keep it.
ARTICLE_HTML = """<!DOCTYPE html><html><head><title>Long Read</title></head><body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<header>SITE BANNER NAVIGATION</header>
<article><h1>Deep Dive</h1>
""" + "".join(
    f"<p>Paragraph {i} explains the subject in enough words that the extractor "
    f"treats this block as the main content of the document rather than as "
    f"boilerplate noise around the edges of the page.</p>" for i in range(40)
) + """</article>
<footer>COPYRIGHT FOOTER PRIVACY POLICY</footer></body></html>"""


def test_small_document_keeps_markdown_formatting():
    """trafilatura flattens this one, so the markdownify fallback must take over."""
    out = html_to_markdown(SMALL_HTML)
    assert "# Main Title" in out
    assert "**test**" in out
    assert "*emphasis*" in out
    assert "[link](https://example.com)" in out
    assert "alert" not in out


def test_article_drops_boilerplate():
    """trafilatura should win here and strip nav, header and footer."""
    out = html_to_markdown(ARTICLE_HTML)
    assert "Paragraph 7 explains" in out
    for chrome in ("SITE BANNER", "COPYRIGHT FOOTER", "PRIVACY POLICY"):
        assert chrome not in out, f"boilerplate survived: {chrome}"


def test_extract_id_is_stable_and_16_chars():
    a = _extract_id("https://example.com/x")
    assert a == _extract_id("https://example.com/x")
    assert len(a) == 16
    assert a != _extract_id("https://example.com/y")


@pytest.mark.parametrize("size", ["s", "m", "l"])
def test_size_presets_truncate(size):
    body = "x" * 60000
    r = _build_extract_response("a" * 16, "http://u", "T", body, size)
    assert r["chars"] == SIZE_LIMITS[size]
    assert r["total_chars"] == 60000
    assert r["pages"] == {"current": 1, "total": 1, "page_size": SIZE_LIMITS[size]}


def test_full_size_paginates_and_chains_next():
    body = "x" * (PAGE_SIZE * 2 + 10)
    first = _build_extract_response("b" * 16, "http://u", "T", body, "f", page=1)
    assert first["pages"]["total"] == 3
    assert first["pages"]["next"] == f"/extract/{'b' * 16}/2"

    last = _build_extract_response("b" * 16, "http://u", "T", body, "f", page=3)
    assert last["chars"] == 10
    assert "next" not in last["pages"], "last page must not advertise a next page"


def test_page_beyond_total_is_404():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        _build_extract_response("c" * 16, "http://u", "T", "short", "f", page=2)
    assert e.value.status_code == 404


def test_unknown_extract_id_is_404():
    with TestClient(app) as client:
        assert client.get(f"/extract/{'0' * 16}/1").status_code == 404


def test_extract_endpoint_caches_by_url(monkeypatch):
    calls = []

    async def fake_extract_url(url):
        calls.append(url)
        return "T", "# H\n\nbody text", "extracted"

    monkeypatch.setattr(main, "_extract_url", fake_extract_url)
    main._extract_cache.clear()

    with TestClient(app) as client:
        first = client.post("/extract", json={"url": "http://u/a", "size": "m"}).json()
        second = client.post("/extract", json={"url": "http://u/a", "size": "m"}).json()

    assert first["id"] == second["id"]
    assert calls == ["http://u/a"], "second call must be served from cache"


@pytest.mark.asyncio
async def test_fetch_raw_content_markdown_over_http():
    async with TestServer(_server(SMALL_HTML)) as server:
        url = f"http://localhost:{server.port}/p"
        async with aiohttp.ClientSession() as session:
            markdown = await fetch_raw_content(session, url, "markdown")
            text = await fetch_raw_content(session, url, "text")

    assert "# Main Title" in markdown
    assert text and "Main Title" in text and "#" not in text


@pytest.mark.asyncio
async def test_fetch_raw_content_returns_none_on_http_error():
    async with TestServer(_server("nope", status=503)) as server:
        async with aiohttp.ClientSession() as session:
            assert await fetch_raw_content(
                session, f"http://localhost:{server.port}/p", "markdown"
            ) is None


# ---------- markdown content negotiation ----------
# A site that serves its own markdown gives authored prose at a fraction of the
# size (visayes.app: 8.6 KB markdown vs 51 KB HTML), so it must win over extraction.

MARKDOWN_BODY = "# Native Title\n\nAuthored paragraph, not extracted.\n"


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ("text/html; charset=utf-8", True),
        ("application/xhtml+xml", True),
        ("application/xml", True),
        # Already text. Nothing to convert, whoever labelled it and however they
        # negotiated — which is why no Vary check is needed to get this right.
        ("text/markdown; charset=utf-8", False),
        ("text/x-markdown", False),
        ("text/plain; charset=utf-8", False),
        ("text/plain", False),
        ("", False),
    ],
)
def test_only_markup_needs_converting(content_type, expected):
    assert needs_html_conversion(content_type) is expected


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ("text/markdown; charset=utf-8", True),
        ("text/x-markdown", True),
        # rustman.org negotiates markdown and labels it text/plain. It still passes
        # through unconverted; it just is not *called* negotiated, and the label is
        # cosmetic so being wrong here costs nothing.
        ("text/plain; charset=utf-8", False),
        ("text/html", False),
        ("", False),
    ],
)
def test_negotiated_label_is_cosmetic(content_type, expected):
    assert negotiated_markdown(content_type) is expected


def _server(body, content_type="text/html", vary="", status=200):
    """One app builder for every case in this file."""

    async def handler(request):
        headers = {"Vary": vary} if vary else {}
        if status != 200:
            return web.Response(status=status, text=body)
        return web.Response(text=body, headers=headers, content_type=content_type)

    app_ = web.Application()
    app_.router.add_get("/p", handler)
    return app_


def _md_server(content_type, vary, body=MARKDOWN_BODY):
    return _server(body, content_type=content_type, vary=vary)


@pytest.mark.asyncio
async def test_extract_uses_negotiated_markdown_verbatim():
    async with TestServer(_md_server("text/markdown", "Accept")) as server:
        title, content, source = await _extract_url(f"http://localhost:{server.port}/p")
    assert source == "negotiated"
    assert content == MARKDOWN_BODY, "the site's own markdown must pass through unchanged"
    assert title == "Native Title", "title comes from the first ATX heading"


@pytest.mark.asyncio
async def test_text_plain_passes_through_and_is_not_called_negotiated():
    """rustman.org's shape: negotiated markdown labelled text/plain. It must reach
    the caller unconverted; only the cosmetic source label differs."""
    async with TestServer(_md_server("text/plain", "Accept")) as server:
        _, content, source = await _extract_url(f"http://localhost:{server.port}/p")
    assert content == MARKDOWN_BODY
    assert source == "extracted"

    # Same body with no Vary at all: still passed through verbatim, because the
    # body is already text. Only the label differs.
    async with TestServer(_md_server("text/plain", "")) as server:
        _, content, source = await _extract_url(f"http://localhost:{server.port}/p")
    assert content == MARKDOWN_BODY
    assert source == "extracted"


@pytest.mark.asyncio
async def test_html_still_goes_through_extraction():
    async with TestServer(_server(ARTICLE_HTML)) as server:
        title, content, source = await _extract_url(f"http://localhost:{server.port}/p")
    assert source == "extracted"
    assert "Paragraph 7 explains" in content
    assert "COPYRIGHT FOOTER" not in content


@pytest.mark.asyncio
async def test_search_scraping_uses_negotiated_markdown():
    async with TestServer(_md_server("text/markdown", "Accept")) as server:
        async with aiohttp.ClientSession() as session:
            out = await fetch_raw_content(
                session, f"http://localhost:{server.port}/p", "markdown"
            )
    assert out == MARKDOWN_BODY


def test_source_is_reported_in_the_response():
    r = _build_extract_response("d" * 16, "http://u", "T", "body", "m", source="negotiated")
    assert r["source"] == "negotiated"
    assert _build_extract_response("d" * 16, "http://u", "T", "body", "m")["source"] == "extracted"


# ---------- unresponsive engines must reach the caller ----------
# A zero-result answer with every engine banned reads as "the subject does not
# exist" unless the ban is reported. That is how a search failure becomes a
# wrong conclusion.

def test_search_response_carries_unresponsive_engines():
    r = TavilyResponse(
        query="q", results=[], response_time=0.1, request_id="x",
        unresponsive_engines=[["google", "Suspended: CAPTCHA"]],
    )
    d = r.model_dump()
    assert d["unresponsive_engines"] == [["google", "Suspended: CAPTCHA"]]


def test_unresponsive_engines_defaults_to_empty():
    d = TavilyResponse(query="q", results=[], response_time=0.1, request_id="x").model_dump()
    assert d["unresponsive_engines"] == []


# ---------- SearXNG's other output channels ----------
# `results` is one of four. Engines that write only to `answers` or `infoboxes`
# looked broken until the response carried them: wikipedia ships as
# display_type ["infobox"], and `currency` answers with no result at all.

def test_response_carries_answers_and_infoboxes():
    d = TavilyResponse(
        query="100 EUR in USD",
        results=[],
        response_time=0.1,
        request_id="x",
        answer="100.0 EUR = 116.75 USD",
        answers=["100.0 EUR = 116.75 USD"],
        infoboxes=[{"infobox": "Beat detection", "content": "In signal analysis..."}],
    ).model_dump()

    assert d["answer"] == "100.0 EUR = 116.75 USD"
    assert d["answers"] == ["100.0 EUR = 116.75 USD"]
    assert d["infoboxes"][0]["infobox"] == "Beat detection"


def test_both_channels_default_to_empty():
    d = TavilyResponse(query="q", results=[], response_time=0.1, request_id="x").model_dump()
    assert d["answers"] == [] and d["infoboxes"] == []

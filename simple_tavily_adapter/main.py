"""
FastAPI server that provides Tavily-compatible API using SearXNG backend.

Endpoints:
- POST /search                 — Tavily-compatible search (smart engine routing)
- POST /extract                — page main content as markdown, size s/m/l/f
- GET  /extract/{id}/{page}    — pagination for size=f
- POST /transcript             — YouTube captions as text
- GET  /health
"""

import asyncio
import hashlib
import logging
import math
import os
import random
import time
import uuid
from typing import Any, Literal

import aiohttp
import nh3
import trafilatura
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path
from markdownify import markdownify as md
from pydantic import BaseModel, Field

from tavily_client import TavilyResponse, TavilyResult
from config_loader import config
from engine_selector import get_smart_engines

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Using search server: {config.searxng_url}")
logger.info(f"Server will run on: {config.server_host}:{config.server_port}")

# Список User-Agent'ов для ротации (Chrome 131, Firefox 134, Safari 18 — 2025)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

# Fallback engine lists for retry logic (when primary engines fail/captcha)
ENGINE_FALLBACKS = [
    "google,duckduckgo,brave",              # Primary: broad web search
    "google,brave,wikipedia",               # Retry: alternative mix
    "duckduckgo,brave,wikipedia",           # Retry: alternative combo
    "google,duckduckgo,wikipedia,wikidata", # Retry: reference-heavy
]



app = FastAPI(title="SearXNG Tavily Adapter", version="1.0.0")


class SearchRequest(BaseModel):
    query: str
    max_results: int = 10
    include_raw_content: bool = False
    content_format: Literal["text", "markdown"] = "markdown"
    engines: str | None = None  # Пользовательский выбор движков (например: "google,wikipedia")


# A site that implements markdown content negotiation serves its own authored
# markdown, which beats anything extracted from its HTML — and is far smaller
# (visayes.app: 8.6 KB of markdown against 51 KB of HTML). Rank markdown above
# html so negotiating servers pick it, and keep html acceptable so the ~all
# sites that ignore Accept still answer normally.
_ACCEPT_MARKDOWN_FIRST = (
    "text/markdown,text/plain;q=0.9,text/html;q=0.8,"
    "application/xhtml+xml;q=0.8,*/*;q=0.7"
)
_MARKDOWN_TYPES = ("text/markdown", "text/x-markdown")


def served_markdown(content_type: str, vary: str) -> bool:
    """True when the response body is already markdown, so no conversion is needed.

    text/markdown is unambiguous. text/plain is only trusted when the response
    also varies on Accept, which proves negotiation happened — rustman.org
    negotiates but labels its markdown text/plain, while a bare .txt file would
    otherwise be mistaken for markdown.
    """
    ct = content_type.split(";")[0].strip().lower()
    if ct in _MARKDOWN_TYPES:
        return True
    if ct != "text/plain":
        return False
    # Vary is a token list and must be matched per token, not by substring:
    # "Vary: Accept-Encoding" ships with almost every gzip response and contains
    # "accept", which would mark every plain-text file as negotiated markdown.
    tokens = {t.strip().lower() for t in vary.split(",")}
    return "accept" in tokens or "*" in tokens


def scrape_headers() -> dict[str, str]:
    """Browser-shaped headers with a rotating UA. Shared by /search scraping and
    /extract: sites that gate on Sec-Fetch-* reject a bare User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": _ACCEPT_MARKDOWN_FIRST,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


_ALLOWED_TAGS = {
    "p", "div", "span", "a", "img", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "strong", "em", "b", "i", "br", "blockquote", "pre",
    "code", "table", "tr", "td", "th", "thead", "tbody",
}
_STRIP_TAGS = ["script", "style", "nav", "header", "footer", "aside", "iframe"]

# Markers that prove the converter actually emitted markdown rather than
# flattening the document to plain text.
_MD_MARKERS = ("\n#", "**", "](", "\n- ", "\n* ", "\n|", "\n> ")


def clean_soup(html: str) -> BeautifulSoup:
    """Sanitize with nh3, then drop chrome tags. Shared by both markdown paths."""
    clean_html = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes={"a": {"href"}, "img": {"src", "alt"}, "*": {"class", "id"}},
    )
    soup = BeautifulSoup(clean_html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    return soup


def trafilatura_markdown(html: str) -> str | None:
    """Main-content extraction. Drops nav, ads and footers by structure, which
    tag-name stripping cannot do. Returns None when there is no article to find."""
    try:
        return trafilatura.extract(
            html,
            output_format="markdown",
            include_formatting=True,
            include_links=True,
            include_tables=True,
            favor_recall=True,
        )
    except Exception as e:
        logger.warning(f"trafilatura failed: {e}")
        return None


def html_to_markdown(html: str, soup: BeautifulSoup | None = None) -> str | None:
    """HTML to markdown, picking the better of two converters per document.

    trafilatura wins on real articles: it removes navigation, ads and footers by
    structure, which stripping tags by name cannot do, and it keeps tables. But on
    small or atypical documents its markdown writer degrades to flat text with no
    headings, bold, links or list bullets — verified against a 10-line test page.
    So its output is only taken when it actually carries markdown structure;
    otherwise markdownify over the sanitized soup, which never loses formatting.
    """
    extracted = trafilatura_markdown(html)
    if extracted and any(m in "\n" + extracted for m in _MD_MARKERS):
        return extracted

    if soup is None:
        soup = clean_soup(html)
    fallback = md(str(soup), heading_style="ATX", strip=["script", "style"])
    return fallback or extracted


async def fetch_raw_content(
    session: aiohttp.ClientSession, url: str, content_format: str = "text"
) -> str | None:
    """Скрапит страницу и возвращает контент в указанном формате"""
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=config.scraper_timeout),
            headers=scrape_headers(),
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                return None

            body = await response.text()

            if served_markdown(
                response.headers.get("content-type", ""),
                response.headers.get("vary", ""),
            ):
                text = body
                if len(text) > config.scraper_max_length:
                    text = text[: config.scraper_max_length] + "..."
                return text

            html = body
            soup = clean_soup(html)

            if content_format == "markdown":
                text = html_to_markdown(html, soup)
            else:
                # Берем простой текст
                text = soup.get_text(separator=" ", strip=True)

            # Обрезаем до настроенного размера
            if len(text) > config.scraper_max_length:
                text = text[: config.scraper_max_length] + "..."

            return text
    except Exception as e:
        logger.warning(f"Error fetching content from {url}: {e}")
        return None


_GITHUB_STOP_WORDS = {
    "library", "libraries", "framework", "frameworks", "tool", "tools",
    "package", "packages", "module", "modules", "api", "sdk", "cli",
    "python", "javascript", "typescript", "rust", "go", "java", "ruby",
    "nodejs", "node", "best", "top", "good", "awesome", "list",
    "github", "repo", "repository", "open", "source", "open-source",
    "for", "with", "and", "the", "using", "how", "what", "find",
    "a", "an", "in", "on", "of", "to", "is", "are", "from",
    "библиотек", "инструмент", "фреймворк", "пакет", "лучший",
}
_GITHUB_MAX_WORDS = 3


def _trim_query_for_github(query: str, engines: str | None) -> str:
    """Trim query to 3 keywords when GitHub engine is used.

    GitHub search API returns 0 results for queries with 4+ words.
    We strip stop words and keep the most specific terms.
    """
    if not engines:
        return query
    engine_list = [e.strip() for e in engines.split(",")]
    if "github" not in engine_list:
        return query
    words = query.split()
    if len(words) <= _GITHUB_MAX_WORDS:
        return query
    # Keep words that are not stop words
    keywords = [w for w in words if w.lower() not in _GITHUB_STOP_WORDS]
    # If all words were stop words, fall back to original first 3
    if not keywords:
        keywords = words[:_GITHUB_MAX_WORDS]
    trimmed = " ".join(keywords[:_GITHUB_MAX_WORDS])
    if trimmed != query:
        logger.info(f"GitHub query trimmed: '{query}' -> '{trimmed}'")
    return trimmed


def _rewrite_reddit_engines(query: str, engines: str | None) -> tuple[str, str | None]:
    """Expand 'reddit' engine to use both PullPush and OAuth API engines.

    When user requests 'reddit', we add 'reddit_api' (OAuth) alongside it.
    Also add Google site:reddit.com as extra source for better coverage.
    """
    if not engines:
        return query, engines
    engine_list = [e.strip() for e in engines.split(",")]
    if "reddit" not in engine_list:
        return query, engines
    # Add reddit api (OAuth) if not already present
    if "reddit api" not in engine_list:
        engine_list.append("reddit api")
    # Add Google site:reddit.com for extra coverage
    if "google" not in engine_list:
        engine_list.append("google")
    if "site:reddit.com" not in query:
        query = f"site:reddit.com {query}"
    return query, ",".join(engine_list)


def _all_requested_unresponsive(engines: str, data: dict) -> bool:
    """True when every engine asked for came back unresponsive.

    SearXNG names engines with spaces ("google cse", "lemmy posts"), so compare
    normalised names rather than tokens.
    """
    requested = {e.strip().lower() for e in engines.split(",") if e.strip()}
    if not requested:
        return False
    down = {
        str(entry[0]).strip().lower()
        for entry in (data.get("unresponsive_engines") or [])
        if entry
    }
    return requested.issubset(down)


async def perform_search_with_retry(
    query: str, max_results: int, max_retries: int = 3, user_engines: str | None = None
) -> dict:
    """Выполняет поиск с повторными попытками и разными движками при капче"""

    # Expand reddit to use PullPush + OAuth API + Google site:reddit.com
    query, user_engines = _rewrite_reddit_engines(query, user_engines)
    # Trim long queries for GitHub (API returns 0 results for 4+ words)
    query = _trim_query_for_github(query, user_engines)

    # Kept across attempts so a final failure still reports WHY. Returning a bare
    # {"results": []} threw away the unresponsive_engines SearXNG had already sent,
    # and an empty answer with no reason reads as "the subject does not exist".
    last_data: dict | None = None

    for attempt in range(max_retries):
        # Выбираем движки для текущей попытки
        if user_engines:
            # Пользователь указал движки - используем их для всех попыток
            engines = user_engines
        elif attempt == 0:
            # Первая попытка - умный выбор на основе запроса
            engines = get_smart_engines(query)
        else:
            # Последующие попытки - используем fallback список
            engines = ENGINE_FALLBACKS[(attempt - 1) % len(ENGINE_FALLBACKS)]

        user_agent = random.choice(USER_AGENTS)

        logger.info(
            f"Search attempt {attempt + 1}/{max_retries} with engines: {engines}"
        )

        # Формируем запрос к SearXNG
        searxng_params = {
            "q": query,
            "format": "json",
            "engines": engines,
            "pageno": 1,
            "language": "auto",
            "safesearch": 1,
        }
        # Only add categories for auto-selected engines (smart routing).
        # When user specifies engines explicitly, omit categories so SearXNG
        # uses ONLY the specified engines without mixing in category defaults.
        if not user_engines:
            searxng_params["categories"] = "general"

        # Рандомизируем заголовки для обхода блокировок
        headers = {
            "X-Forwarded-For": f"192.168.1.{random.randint(1, 254)}",
            "X-Real-IP": f"10.0.0.{random.randint(1, 254)}",
            "User-Agent": user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

        try:
            # Добавляем случайную задержку для имитации человеческого поведения
            if attempt > 0:
                delay = random.uniform(1, 3)
                logger.info(f"Waiting {delay:.1f}s before retry...")
                await asyncio.sleep(delay)

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{config.searxng_url}/search",
                    data=searxng_params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        last_data = data
                        results = data.get("results", [])
                        if results:  # Если есть результаты, возвращаем
                            logger.info(f"Search successful on attempt {attempt + 1}")
                            return data

                        logger.warning(f"No results on attempt {attempt + 1}")
                        # Retrying a suspended engine is waiting for nothing: a
                        # suspension lasts minutes, not the 1-3s of backoff here.
                        # Only bail early when the caller pinned the engines, since
                        # auto-routing has other engine sets left to try.
                        if user_engines and _all_requested_unresponsive(
                            engines, data
                        ):
                            logger.info(
                                "Every requested engine is suspended, not retrying"
                            )
                            return data
                    else:
                        logger.warning(
                            f"HTTP {response.status} on attempt {attempt + 1}"
                        )

        except aiohttp.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt + 1}")
        except Exception as e:
            logger.warning(f"Error on attempt {attempt + 1}: {e}")

    # Если все попытки провалились, возвращаем пустые результаты,
    # но с диагностикой последнего ответа — иначе непонятно, почему пусто.
    logger.error(f"All {max_retries} search attempts failed")
    if last_data is not None:
        last_data["results"] = []
        return last_data
    return {"results": []}


async def perform_simple_search(query: str, user_engines: str | None = None) -> dict:
    """Простой поиск без anti-captcha логики (старое поведение)"""

    # Expand reddit to use PullPush + OAuth API + Google site:reddit.com
    query, user_engines = _rewrite_reddit_engines(query, user_engines)
    # Trim long queries for GitHub (API returns 0 results for 4+ words)
    query = _trim_query_for_github(query, user_engines)

    # Выбираем движки: пользовательские или умный выбор
    engines = user_engines if user_engines else get_smart_engines(query)
    
    searxng_params = {
        "q": query,
        "format": "json",
        "engines": engines,
        "pageno": 1,
        "language": "auto",
        "safesearch": 1,
    }
    if not user_engines:
        searxng_params["categories"] = "general"

    headers = {
        "X-Forwarded-For": "127.0.0.1",
        "X-Real-IP": "127.0.0.1",
        "User-Agent": "Mozilla/5.0 (compatible; TavilyBot/1.0)",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{config.searxng_url}/search",
                data=searxng_params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=500, detail="SearXNG request failed"
                    )
                return await response.json()
    except aiohttp.TimeoutError:
        raise HTTPException(status_code=504, detail="SearXNG timeout")
    except Exception as e:
        logger.error(f"SearXNG error: {e}")
        raise HTTPException(status_code=500, detail="Search service unavailable")


@app.post("/search")
async def search(request: SearchRequest) -> dict[str, Any]:
    """
    Tavily-compatible search endpoint
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())

    logger.info(f"Search request: {request.query}")

    # Выполняем поиск с retry логикой и обходом капчи
    max_retries = int(os.getenv("MAX_SEARCH_RETRIES", "3"))
    enable_anti_captcha = os.getenv("ENABLE_ANTI_CAPTCHA", "true").lower() == "true"

    if enable_anti_captcha:
        searxng_data = await perform_search_with_retry(
            request.query, request.max_results, max_retries, request.engines
        )
    else:
        # Простой поиск без retry (старое поведение)
        searxng_data = await perform_simple_search(request.query, request.engines)

    # Конвертируем результаты в формат Tavily
    results = []
    searxng_results = searxng_data.get("results", [])

    # Если нужен raw_content, скрапим страницы
    raw_contents = {}
    if request.include_raw_content and searxng_results:
        urls_to_scrape = [
            r["url"] for r in searxng_results[: request.max_results] if r.get("url")
        ]

        async with aiohttp.ClientSession() as scrape_session:
            tasks = [
                fetch_raw_content(scrape_session, url, request.content_format)
                for url in urls_to_scrape
            ]
            page_contents = await asyncio.gather(*tasks, return_exceptions=True)

            for url, content in zip(urls_to_scrape, page_contents):
                if isinstance(content, str) and content:
                    raw_contents[url] = content

    for i, result in enumerate(searxng_results[: request.max_results]):
        if not result.get("url"):
            continue

        raw_content = None
        if request.include_raw_content:
            raw_content = raw_contents.get(result["url"])

        tavily_result = TavilyResult(
            url=result["url"],
            title=result.get("title", ""),
            content=result.get("content", ""),
            score=0.9 - (i * 0.05),  # Простая имитация скора
            raw_content=raw_content,
        )
        results.append(tavily_result)

    response_time = time.time() - start_time

    unresponsive = [
        [str(x) for x in entry][:2]
        for entry in (searxng_data.get("unresponsive_engines") or [])
        if entry
    ]

    response = TavilyResponse(
        query=request.query,
        follow_up_questions=None,
        answer=None,
        images=[],
        results=results,
        response_time=response_time,
        request_id=request_id,
        unresponsive_engines=unresponsive,
    )

    logger.info(f"Search completed: {len(results)} results in {response_time:.2f}s")
    if unresponsive:
        logger.info(
            "Unresponsive engines: "
            + ", ".join(f"{e[0]}={e[1] if len(e) > 1 else '?'}" for e in unresponsive)
        )

    return response.model_dump()


class TranscriptRequest(BaseModel):
    video_id: str  # YouTube video ID (e.g. "dQw4w9WgXcQ") or full URL
    languages: list[str] = ["en", "ru"]
    max_length: int = 5000


@app.post("/transcript")
async def transcript(request: TranscriptRequest) -> dict[str, Any]:
    """
    Extract YouTube video transcript/subtitles via youtube-transcript-api.
    Returns plain text transcript (auto-generated or manual captions).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise HTTPException(status_code=500, detail="youtube-transcript-api not installed")

    # Extract video ID from URL if needed
    video_id = request.video_id
    if "youtube.com" in video_id or "youtu.be" in video_id:
        import re
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", video_id)
        if match:
            video_id = match.group(1)
        else:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    logger.info(f"Transcript request: {video_id}")

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=request.languages)
        text = " ".join([s.text for s in fetched.snippets])

        if len(text) > request.max_length:
            text = text[: request.max_length] + "..."

        return {
            "video_id": video_id,
            "language": fetched.language,
            "text": text,
            "snippet_count": len(fetched.snippets),
            "char_count": len(text),
        }
    except Exception as e:
        logger.warning(f"Transcript error for {video_id}: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"Transcript not available: {type(e).__name__}",
        )


# ---------- /extract — full-page markdown with size presets and pagination ----------
# Ported from upstream vakovalskii/searcharvester v2.x. /search returns snippets;
# this returns the whole article, sized to a context budget.

SIZE_LIMITS: dict[str, int] = {"s": 5000, "m": 10000, "l": 25000}
PAGE_SIZE = 25000
EXTRACT_CACHE_TTL_SEC = 1800  # 30 min — long enough to page through one document

# extract_id -> {"url", "title", "content", "created_at"}
_extract_cache: dict[str, dict[str, Any]] = {}


class ExtractRequest(BaseModel):
    url: str
    size: Literal["s", "m", "l", "f"] = Field(
        default="m",
        description="s=5000, m=10000, l=25000 chars (truncated); f=full, paginated",
    )


def _extract_id(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]


def _gc_extract_cache() -> None:
    now = time.time()
    for k in [k for k, v in _extract_cache.items() if now - v["created_at"] > EXTRACT_CACHE_TTL_SEC]:
        _extract_cache.pop(k, None)


async def _extract_url(url: str) -> tuple[str, str, str]:
    """Fetch one page as markdown. Returns (title, markdown, source).

    source is "negotiated" when the site served markdown itself, "extracted" when
    it was converted from HTML here. Worth surfacing: negotiated content is the
    site's own prose, extracted content is a best effort.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=config.scraper_timeout),
                headers=scrape_headers(),
                allow_redirects=True,
            ) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=502, detail=f"Fetch failed for {url}: HTTP {response.status}"
                    )
                body = await response.text()
                native_md = served_markdown(
                    response.headers.get("Content-Type", ""),
                    response.headers.get("Vary", ""),
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Fetch failed for {url}: {type(e).__name__}")

    if native_md:
        # The site authored this markdown. Take its first ATX heading as the title
        # rather than parsing HTML metadata that is not in this response.
        first = next((ln for ln in body.splitlines() if ln.startswith("# ")), "")
        return first[2:].strip(), body, "negotiated"

    content = html_to_markdown(body)
    if not content:
        raise HTTPException(
            status_code=422, detail="No main content found on the page after cleaning"
        )

    title = ""
    try:
        metadata = trafilatura.extract_metadata(body)
        if metadata and metadata.title:
            title = metadata.title
    except Exception:
        pass

    return title, content, "extracted"


def _build_extract_response(
    extract_id: str,
    url: str,
    title: str,
    full_content: str,
    size: str,
    page: int = 1,
    source: str = "extracted",
) -> dict[str, Any]:
    total_chars = len(full_content)

    if size == "f":
        total_pages = max(1, math.ceil(total_chars / PAGE_SIZE))
        if page > total_pages:
            raise HTTPException(
                status_code=404, detail=f"Page {page} does not exist (total {total_pages})"
            )
        start = (page - 1) * PAGE_SIZE
        chunk = full_content[start : start + PAGE_SIZE]
        pages_info: dict[str, Any] = {
            "current": page,
            "total": total_pages,
            "page_size": PAGE_SIZE,
        }
        if page < total_pages:
            pages_info["next"] = f"/extract/{extract_id}/{page + 1}"
    else:
        limit = SIZE_LIMITS[size]
        chunk = full_content[:limit]
        pages_info = {"current": 1, "total": 1, "page_size": limit}

    return {
        "id": extract_id,
        "url": url,
        "title": title,
        "format": "md",
        "source": source,
        "size": size,
        "content": chunk,
        "chars": len(chunk),
        "total_chars": total_chars,
        "pages": pages_info,
    }


@app.post("/extract")
async def extract(request: ExtractRequest) -> dict[str, Any]:
    """Extract a page's main content as markdown. Returns an id for paging size=f."""
    _gc_extract_cache()
    extract_id = _extract_id(request.url)

    cached = _extract_cache.get(extract_id)
    if cached and cached["url"] == request.url:
        title, content, source = cached["title"], cached["content"], cached["source"]
        logger.info(f"Extract cache hit: {request.url}")
    else:
        logger.info(f"Extract request: {request.url}")
        title, content, source = await _extract_url(request.url)
        logger.info(f"Extract {source}: {request.url} ({len(content)} chars)")
        _extract_cache[extract_id] = {
            "url": request.url,
            "title": title,
            "content": content,
            "source": source,
            "created_at": time.time(),
        }

    return _build_extract_response(
        extract_id, request.url, title, content, request.size, source=source
    )


@app.get("/extract/{extract_id}/{page}")
async def extract_page(
    extract_id: str = Path(..., min_length=16, max_length=16),
    page: int = Path(..., ge=1),
) -> dict[str, Any]:
    """Return page N of a previously extracted document (size=f only)."""
    _gc_extract_cache()
    cached = _extract_cache.get(extract_id)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail="id unknown or expired (TTL 30 min). Repeat POST /extract.",
        )
    return _build_extract_response(
        extract_id,
        cached["url"],
        cached["title"],
        cached["content"],
        size="f",
        page=page,
        source=cached.get("source", "extracted"),
    )


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "searxng-tavily-adapter"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.server_host, port=config.server_port)

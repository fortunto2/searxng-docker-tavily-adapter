"""
FastAPI server that provides Tavily-compatible API using SearXNG backend
"""

import asyncio
import logging
import os
import random
import time
import uuid
from typing import Any, Literal

import aiohttp
import nh3
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from markdownify import markdownify as md
from pydantic import BaseModel

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

# Список User-Agent'ов для ротации
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (compatible; TavilyBot/1.0)",
    "Mozilla/5.0 (compatible; SearchBot/1.0)",
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


async def fetch_raw_content(
    session: aiohttp.ClientSession, url: str, content_format: str = "text"
) -> str | None:
    """Скрапит страницу и возвращает контент в указанном формате"""
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=config.scraper_timeout),
            headers={"User-Agent": config.scraper_user_agent},
        ) as response:
            if response.status != 200:
                return None

            html = await response.text()

            # Очищаем HTML с помощью nh3 для безопасности
            clean_html = nh3.clean(
                html,
                tags={
                    "p",
                    "div",
                    "span",
                    "a",
                    "img",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "ul",
                    "ol",
                    "li",
                    "strong",
                    "em",
                    "b",
                    "i",
                    "br",
                    "blockquote",
                    "pre",
                    "code",
                    "table",
                    "tr",
                    "td",
                    "th",
                    "thead",
                    "tbody",
                },
                attributes={"a": {"href"}, "img": {"src", "alt"}, "*": {"class", "id"}},
            )

            soup = BeautifulSoup(clean_html, "html.parser")

            # Удаляем ненужные элементы
            for tag in soup(
                ["script", "style", "nav", "header", "footer", "aside", "iframe"]
            ):
                tag.decompose()

            if content_format == "markdown":
                # Конвертируем в Markdown
                text = md(str(soup), heading_style="ATX", strip=["script", "style"])
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


def _rewrite_reddit_to_google(query: str, engines: str | None) -> tuple[str, str | None]:
    """If 'reddit' is requested as engine, use Google with site:reddit.com instead.

    PullPush API (SearXNG reddit engine) returns SEO spam with poor relevance.
    Google site:reddit.com produces much better Reddit results.
    """
    if not engines:
        return query, engines
    engine_list = [e.strip() for e in engines.split(",")]
    if "reddit" not in engine_list:
        return query, engines
    # Remove reddit, add google if not present
    engine_list = [e for e in engine_list if e != "reddit"]
    if "google" not in engine_list:
        engine_list.insert(0, "google")
    # Prepend site:reddit.com to query (avoid duplicating)
    if "site:reddit.com" not in query:
        query = f"site:reddit.com {query}"
    return query, ",".join(engine_list)


async def perform_search_with_retry(
    query: str, max_results: int, max_retries: int = 3, user_engines: str | None = None
) -> dict:
    """Выполняет поиск с повторными попытками и разными движками при капче"""

    # Rewrite reddit engine to google+site:reddit.com for better results
    query, user_engines = _rewrite_reddit_to_google(query, user_engines)

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
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
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
                        results = data.get("results", [])
                        if results:  # Если есть результаты, возвращаем
                            logger.info(f"Search successful on attempt {attempt + 1}")
                            return data
                        else:
                            logger.warning(f"No results on attempt {attempt + 1}")
                    else:
                        logger.warning(
                            f"HTTP {response.status} on attempt {attempt + 1}"
                        )

        except aiohttp.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt + 1}")
        except Exception as e:
            logger.warning(f"Error on attempt {attempt + 1}: {e}")

    # Если все попытки провалились, возвращаем пустые результаты
    logger.error(f"All {max_retries} search attempts failed")
    return {"results": []}


async def perform_simple_search(query: str, user_engines: str | None = None) -> dict:
    """Простой поиск без anti-captcha логики (старое поведение)"""

    # Rewrite reddit engine to google+site:reddit.com for better results
    query, user_engines = _rewrite_reddit_to_google(query, user_engines)

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

    response = TavilyResponse(
        query=request.query,
        follow_up_questions=None,
        answer=None,
        images=[],
        results=results,
        response_time=response_time,
        request_id=request_id,
    )

    logger.info(f"Search completed: {len(results)} results in {response_time:.2f}s")

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


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "searxng-tavily-adapter"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.server_host, port=config.server_port)

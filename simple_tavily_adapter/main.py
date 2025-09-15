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

# Список движков для фолбэка (более надежные и менее блокируемые)
ENGINE_FALLBACKS = [
    "google,duckduckgo,wikipedia,wikidata,arxiv,reddit",  # Основная комбинация с качественными источниками
    "wikipedia,wikidata,arxiv,reddit",  # Академические + структурированные данные
    "bing,qwant,wikipedia,wikidata",  # Альтернативная комбинация
    "searx,mojeek,reddit,wikidata",  # Запасная комбинация
    "yandex,wikipedia,wikidata",  # Последний резерв
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


async def perform_search_with_retry(
    query: str, max_results: int, max_retries: int = 3, user_engines: str | None = None
) -> dict:
    """Выполняет поиск с повторными попытками и разными движками при капче"""

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
            "categories": "general",
            "engines": engines,
            "pageno": 1,
            "language": "auto",
            "safesearch": 1,
        }

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
    
    # Выбираем движки: пользовательские или умный выбор
    engines = user_engines if user_engines else get_smart_engines(query)
    
    searxng_params = {
        "q": query,
        "format": "json",
        "categories": "general",
        "engines": engines,
        "pageno": 1,
        "language": "auto",
        "safesearch": 1,
    }

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


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "searxng-tavily-adapter"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.server_host, port=config.server_port)

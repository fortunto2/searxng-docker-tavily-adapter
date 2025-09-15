"""
FastAPI server that provides Tavily-compatible API using SearXNG backend
"""
import asyncio
import logging
import os
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

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Using search server: {config.searxng_url}")
logger.info(f"Server will run on: {config.server_host}:{config.server_port}")

app = FastAPI(title="SearXNG Tavily Adapter", version="1.0.0")


class SearchRequest(BaseModel):
    query: str
    max_results: int = 10
    include_raw_content: bool = False
    content_format: Literal["text", "markdown"] = "markdown"


async def fetch_raw_content(session: aiohttp.ClientSession, url: str, content_format: str = "text") -> str | None:
    """Скрапит страницу и возвращает контент в указанном формате"""
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=config.scraper_timeout),
            headers={'User-Agent': config.scraper_user_agent}
        ) as response:
            if response.status != 200:
                return None
            
            html = await response.text()
            
            # Очищаем HTML с помощью nh3 для безопасности
            clean_html = nh3.clean(html, tags={
                'p', 'div', 'span', 'a', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'ul', 'ol', 'li', 'strong', 'em', 'b', 'i', 'br', 'blockquote',
                'pre', 'code', 'table', 'tr', 'td', 'th', 'thead', 'tbody'
            }, attributes={
                'a': {'href'}, 'img': {'src', 'alt'}, '*': {'class', 'id'}
            })
            
            soup = BeautifulSoup(clean_html, 'html.parser')
            
            # Удаляем ненужные элементы
            for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
                tag.decompose()
            
            if content_format == "markdown":
                # Конвертируем в Markdown
                text = md(str(soup), heading_style="ATX", strip=['script', 'style'])
            else:
                # Берем простой текст
                text = soup.get_text(separator=' ', strip=True)
            
            # Обрезаем до настроенного размера
            if len(text) > config.scraper_max_length:
                text = text[:config.scraper_max_length] + "..."
            
            return text
    except Exception as e:
        logger.warning(f"Error fetching content from {url}: {e}")
        return None


@app.post("/search")
async def search(request: SearchRequest) -> dict[str, Any]:
    """
    Tavily-compatible search endpoint
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    logger.info(f"Search request: {request.query}")
    
    # Формируем запрос к SearXNG
    searxng_params = {
        "q": request.query,
        "format": "json",
        "categories": "general",
        "engines": "google,duckduckgo,brave",  # Убрали Bing
        "pageno": 1,
        "language": "auto",
        "safesearch": 1,
    }
    
# Убрали обработку доменов - не нужно для упрощенного API
    
    # Выполняем запрос к SearXNG
    headers = {
        'X-Forwarded-For': '127.0.0.1',
        'X-Real-IP': '127.0.0.1',
        'User-Agent': 'Mozilla/5.0 (compatible; TavilyBot/1.0)',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{config.searxng_url}/search",
                data=searxng_params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    raise HTTPException(status_code=500, detail="SearXNG request failed")
                searxng_data = await response.json()
        except aiohttp.TimeoutError:
            raise HTTPException(status_code=504, detail="SearXNG timeout")
        except Exception as e:
            logger.error(f"SearXNG error: {e}")
            raise HTTPException(status_code=500, detail="Search service unavailable")
    
    # Конвертируем результаты в формат Tavily
    results = []
    searxng_results = searxng_data.get("results", [])
    
    # Если нужен raw_content, скрапим страницы
    raw_contents = {}
    if request.include_raw_content and searxng_results:
        urls_to_scrape = [r["url"] for r in searxng_results[:request.max_results] if r.get("url")]
        
        async with aiohttp.ClientSession() as scrape_session:
            tasks = [fetch_raw_content(scrape_session, url, request.content_format) for url in urls_to_scrape]
            page_contents = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, content in zip(urls_to_scrape, page_contents):
                if isinstance(content, str) and content:
                    raw_contents[url] = content
    
    for i, result in enumerate(searxng_results[:request.max_results]):
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
            raw_content=raw_content
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

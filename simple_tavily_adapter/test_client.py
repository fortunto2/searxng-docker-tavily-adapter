"""
Тест для проверки совместимости с оригинальным Tavily API
"""
import asyncio
import os
import aiohttp
from dotenv import load_dotenv
from tavily_client import TavilyClient

# Загружаем переменные окружения
load_dotenv()

# Получаем порт сервера из переменной окружения
ADAPTER_PORT = os.getenv("ADAPTER_PORT", "8013")
API_BASE_URL = f"http://localhost:{ADAPTER_PORT}"

async def test_direct_api():
    """Тест прямого обращения к API с новым параметром content_format"""
    print("=== Тест прямого API (текстовый формат) ===")
    async with aiohttp.ClientSession() as session:
        payload = {
            "query": "Python programming",
            "max_results": 3,
            "include_raw_content": True,
            "content_format": "text"
        }
        async with session.post(f"{API_BASE_URL}/search", json=payload) as response:
            data = await response.json()
            print(f"Results count: {len(data['results'])}")
            if data['results'] and data['results'][0].get('raw_content'):
                print(f"Raw content preview: {data['results'][0]['raw_content'][:200]}...")
    
    print("\n=== Тест прямого API (Markdown формат) ===")
    async with aiohttp.ClientSession() as session:
        payload = {
            "query": "Python programming",
            "max_results": 3,
            "include_raw_content": True,
            "content_format": "markdown"
        }
        async with session.post(f"{API_BASE_URL}/search", json=payload) as response:
            data = await response.json()
            print(f"Results count: {len(data['results'])}")
            if data['results'] and data['results'][0].get('raw_content'):
                print(f"Markdown content preview: {data['results'][0]['raw_content'][:200]}...")

async def test_tavily_api_compatibility():
    """Тест совместимости с Tavily API через адаптер"""
    print("\n=== Тест совместимости Tavily API ===")
    async with aiohttp.ClientSession() as session:
        # Эмулируем стандартный Tavily запрос
        payload = {
            "query": "цена bmw x6",
            "max_results": 5,
            "include_raw_content": True
            # content_format по умолчанию "markdown"
        }
        async with session.post(f"{API_BASE_URL}/search", json=payload) as response:
            data = await response.json()
            
            # Проверяем структуру ответа Tavily
            expected_keys = ['query', 'follow_up_questions', 'answer', 'images', 'results', 'response_time', 'request_id']
            print("Response keys:", list(data.keys()))
            print("All expected keys present:", all(key in data for key in expected_keys))
            print("Results count:", len(data['results']))
            
            if data['results']:
                first_result = data['results'][0]
                print("First result URL:", first_result["url"])
                print("First result title:", first_result["title"])
                if first_result.get("raw_content"):
                    print("Has raw content:", len(first_result["raw_content"]), "chars")
                    print("Content type: Markdown (default)")
                    # Проверяем, что это действительно Markdown
                    content = first_result["raw_content"]
                    if any(marker in content for marker in ['#', '**', '*', '```', '>']):
                        print("✅ Markdown formatting detected")
                    else:
                        print("⚠️  No obvious Markdown formatting")

def test_tavily_client():
    """Заглушка для совместимости - TavilyClient работает напрямую с SearXNG"""
    print("\n=== Тест через Tavily Client (Legacy) ===")
    print("⚠️  TavilyClient подключается напрямую к SearXNG, минуя адаптер")
    print("📍 Для тестирования адаптера используйте прямые API вызовы выше")

if __name__ == "__main__":
    # Тест через клиент (обратная совместимость)  
    test_tavily_client()
    
    # Тесты новой функциональности
    asyncio.run(test_direct_api())
    
    # Тест совместимости с Tavily API
    asyncio.run(test_tavily_api_compatibility())

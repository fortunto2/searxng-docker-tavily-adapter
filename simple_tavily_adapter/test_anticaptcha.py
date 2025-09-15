#!/usr/bin/env python3
"""
Тест anti-captcha функциональности
"""
import asyncio
import os
import aiohttp
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

ADAPTER_PORT = os.getenv("ADAPTER_PORT", "8013")
API_BASE_URL = f"http://localhost:{ADAPTER_PORT}"

async def test_anticaptcha_enabled():
    """Тест с включенным anti-captcha"""
    print("=== Тест с Anti-CAPTCHA (включено) ===")
    
    async with aiohttp.ClientSession() as session:
        payload = {
            "query": "test captcha bypass",
            "max_results": 3,
            "include_raw_content": False
        }
        
        try:
            async with session.post(f"{API_BASE_URL}/search", json=payload) as response:
                data = await response.json()
                print(f"Status: {response.status}")
                print(f"Results count: {len(data.get('results', []))}")
                print(f"Response time: {data.get('response_time', 0):.2f}s")
                
                if len(data.get('results', [])) > 0:
                    print("✅ Поиск успешен (anti-captcha работает)")
                else:
                    print("⚠️ Нет результатов (возможно, все движки заблокированы)")
                    
        except Exception as e:
            print(f"❌ Ошибка: {e}")

async def test_different_queries():
    """Тест разных запросов для проверки стабильности"""
    queries = [
        "python programming",
        "машинное обучение",
        "weather today",
        "новости технологий"
    ]
    
    print("\n=== Тест стабильности с разными запросами ===")
    
    for i, query in enumerate(queries, 1):
        print(f"\n{i}. Запрос: '{query}'")
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "query": query,
                "max_results": 2,
                "include_raw_content": False
            }
            
            try:
                async with session.post(f"{API_BASE_URL}/search", json=payload) as response:
                    data = await response.json()
                    results_count = len(data.get('results', []))
                    response_time = data.get('response_time', 0)
                    
                    if results_count > 0:
                        print(f"✅ {results_count} результатов за {response_time:.2f}с")
                    else:
                        print(f"⚠️ Нет результатов за {response_time:.2f}с")
                        
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        # Пауза между запросами
        await asyncio.sleep(1)

if __name__ == "__main__":
    print("🚀 Тестирование Anti-CAPTCHA функциональности")
    print("=" * 50)
    print(f"🔗 API URL: {API_BASE_URL}")
    print()
    
    asyncio.run(test_anticaptcha_enabled())
    asyncio.run(test_different_queries())
    
    print("\n💡 Настройки:")
    print("  ENABLE_ANTI_CAPTCHA=true/false - включить/выключить")
    print("  MAX_SEARCH_RETRIES=3 - количество попыток")
    print("  В логах сервера видны детали retry попыток")
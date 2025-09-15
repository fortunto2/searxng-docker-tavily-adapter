#!/usr/bin/env python3
"""
Тест для проверки функций конвертации в Markdown
"""
import asyncio
import aiohttp
from main import fetch_raw_content

async def test_markdown_conversion():
    """Тест конвертации HTML в Markdown"""
    
    # Тестовый HTML
    test_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Main Title</h1>
        <p>This is a <strong>test</strong> paragraph with <em>emphasis</em>.</p>
        <h2>Subtitle</h2>
        <ul>
            <li>Item 1</li>
            <li>Item 2 with <a href="https://example.com">link</a></li>
        </ul>
        <blockquote>This is a quote</blockquote>
        <script>alert('malicious');</script>
        <style>.hidden { display: none; }</style>
    </body>
    </html>
    """
    
    # Создаем мок-сервер для тестирования
    from aiohttp import web
    from aiohttp.test_utils import TestServer, TestClient
    
    async def mock_handler(request):
        return web.Response(text=test_html, content_type='text/html')
    
    app = web.Application()
    app.router.add_get('/test', mock_handler)
    
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            test_url = f"http://localhost:{server.port}/test"
            
            # Тест текстового формата
            async with aiohttp.ClientSession() as session:
                text_result = await fetch_raw_content(session, test_url, "text")
                print("=== Текстовый формат ===")
                print(text_result)
                print()
                
                # Тест Markdown формата
                markdown_result = await fetch_raw_content(session, test_url, "markdown")
                print("=== Markdown формат ===")
                print(markdown_result)
                print()
                
                # Проверки
                assert text_result is not None, "Текстовый результат не должен быть None"
                assert markdown_result is not None, "Markdown результат не должен быть None"
                assert "# Main Title" in markdown_result, "Заголовок должен быть конвертирован"
                assert "**test**" in markdown_result, "Bold должен быть конвертирован"
                assert "*emphasis*" in markdown_result, "Курсив должен быть конвертирован"
                assert "* Item 1" in markdown_result, "Списки должны быть конвертированы"
                assert "[link](https://example.com)" in markdown_result, "Ссылки должны быть конвертированы"
                assert "alert" not in markdown_result, "Скрипты должны быть удалены"
                
                print("✅ Все тесты прошли успешно!")

if __name__ == "__main__":
    asyncio.run(test_markdown_conversion())
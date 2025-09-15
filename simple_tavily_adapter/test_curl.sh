#!/bin/bash
# Тестовые curl команды для проверки API

# Загружаем переменные окружения
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Используем переменную окружения или дефолт
ADAPTER_PORT=${ADAPTER_PORT:-8013}
API_BASE_URL="http://localhost:${ADAPTER_PORT}"

echo "🚀 Тестирование SearXNG Tavily Adapter"
echo "======================================"
echo "🔗 API URL: ${API_BASE_URL}"
echo "💡 Порт ${ADAPTER_PORT} - для локальных тестов (в Docker используется :8000)"
echo ""

# Проверка health endpoint
echo "1. Health check:"
curl -s ${API_BASE_URL}/health | jq '.' || echo "❌ Сервер не запущен"
echo ""

# Базовый поиск (по умолчанию markdown)
echo "2. Базовый поиск (markdown по умолчанию):"
curl -s -X POST "${API_BASE_URL}/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "Python programming", "max_results": 2}' | jq '.results[0].title' || echo "❌ Ошибка запроса"
echo ""

# Поиск с raw content в markdown
echo "3. Поиск с raw content (markdown):"
curl -s -X POST "${API_BASE_URL}/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "Python programming", "max_results": 1, "include_raw_content": true, "content_format": "markdown"}' | jq '.results[0] | {title, url, has_raw_content: (.raw_content != null)}' || echo "❌ Ошибка запроса"
echo ""

# Поиск с raw content в text
echo "4. Поиск с raw content (text):"
curl -s -X POST "${API_BASE_URL}/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "Python programming", "max_results": 1, "include_raw_content": true, "content_format": "text"}' | jq '.results[0] | {title, url, has_raw_content: (.raw_content != null)}' || echo "❌ Ошибка запроса"
echo ""

echo "✅ Тестирование завершено!"
echo ""
echo "💡 Для запуска сервера используйте:"
echo "   ADAPTER_PORT=8013 uv run python main.py"
echo "   или"
echo "   uv run python run_with_uv.py"
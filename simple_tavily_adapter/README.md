# Тестирование SearXNG Tavily Adapter

## Конфигурация портов

### Продакшн (Docker)
- **SearXNG**: порт 8999 (внешний) → 8080 (внутренний)
- **Adapter**: порт 8000 (внешний и внутренний)
- **Adapter → SearXNG**: `http://searxng:8080` (Docker network)

### Локальные тесты
- **Adapter**: порт 8013 (настроен в `.env`)
- **SearXNG**: `http://localhost:8013` (тестовый сервер)

## Переменные окружения

Файл `.env` содержит:
```bash
ADAPTER_PORT=8013  # Только для локальных тестов
```

Поддерживаемые переменные:
- `SEARCH_SERVER` - URL SearXNG сервера
- `ADAPTER_HOST` - хост адаптера (по умолчанию 0.0.0.0)
- `ADAPTER_PORT` - порт адаптера (по умолчанию 8000, тестовый 8013)
- `SCRAPER_TIMEOUT` - таймаут скрапера (по умолчанию 10)
- `SCRAPER_MAX_LENGTH` - максимальная длина контента (по умолчанию 2500)
- `SCRAPER_USER_AGENT` - User-Agent для скрапера

## Команды для тестирования

```bash
# Unit тесты
uv run python test_unit.py

# Тест конвертации Markdown
uv run python test_markdown.py

# Запуск сервера на порту 8013
uv run python main.py

# Curl тесты (нужен запущенный сервер)
./test_curl.sh
```

## Новые возможности

### Markdown контент по умолчанию
```json
{
  "query": "test",
  "include_raw_content": true
  // content_format по умолчанию "markdown"
}
```

### Выбор формата контента
```json
{
  "query": "test", 
  "include_raw_content": true,
  "content_format": "text"  // или "markdown"
}
```
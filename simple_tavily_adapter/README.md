# Тестирование SearXNG Tavily Adapter

## Конфигурация портов

### Продакшн (Docker)
- **SearXNG**: порт 8999 (внешний) → 8080 (внутренний)
- **Adapter**: порт 8000 (внешний и внутренний)
- **Adapter → SearXNG**: `http://searxng:8080` (Docker network)
- **Python**: 3.12 + uv для управления зависимостями

### Локальные тесты
- **Adapter**: порт 8013 (настроен в `.env`)
- **SearXNG**: `http://localhost:8013` (тестовый сервер)

## Переменные окружения

Файл `.env` содержит:
```bash
ADAPTER_PORT=8013  # Только для локальных тестов

# Anti-CAPTCHA настройки (опционально)
# MAX_SEARCH_RETRIES=3
# ENABLE_ANTI_CAPTCHA=true
```

Поддерживаемые переменные:
- `SEARCH_SERVER` - URL SearXNG сервера
- `ADAPTER_HOST` - хост адаптера (по умолчанию 0.0.0.0)
- `ADAPTER_PORT` - порт адаптера (по умолчанию 8000, тестовый 8013)
- `SCRAPER_TIMEOUT` - таймаут скрапера (по умолчанию 10)
- `SCRAPER_MAX_LENGTH` - максимальная длина контента (по умолчанию 2500)
- `SCRAPER_USER_AGENT` - User-Agent для скрапера
- `ENABLE_ANTI_CAPTCHA` - включить обход капчи (по умолчанию true)
- `MAX_SEARCH_RETRIES` - количество попыток при капче (по умолчанию 3)

## Команды для тестирования

```bash
# Unit тесты
uv run python test_unit.py

# Тест конвертации Markdown
uv run python test_markdown.py

# Тест клиента и API
uv run python test_client.py

# Тест anti-captcha функциональности
uv run python test_anticaptcha.py

# Запуск сервера на порту 8013
uv run python main.py

# Curl тесты (нужен запущенный сервер)
./test_curl.sh
```

### Docker команды
```bash
# Сборка образа
docker build -t searxng-tavily-adapter .

# Запуск контейнера
docker run -p 8000:8000 searxng-tavily-adapter

# Через docker-compose (рекомендуется)
cd ..
docker compose up -d
```

## Новые возможности

### Anti-CAPTCHA система
Автоматический обход капчи от поисковиков:
- **3 попытки** с разными комбинациями движков
- **Ротация User-Agent** для имитации разных браузеров
- **Рандомные IP адреса** в заголовках 
- **Задержки между запросами** (1-3 секунды)
- **Fallback движки**: Google+DuckDuckGo → Bing+Qwant → Searx+Mojeek → Yandex

Стратегия обхода:
1. Попытка 1: `google,duckduckgo,brave`
2. Попытка 2: `bing,qwant,startpage` 
3. Попытка 3: `searx,mojeek`
4. Попытка 4: `yandex`

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

### Управление Anti-CAPTCHA
```bash
# Включить/выключить обход капчи
ENABLE_ANTI_CAPTCHA=true/false

# Количество попыток (по умолчанию 3)
MAX_SEARCH_RETRIES=5
```
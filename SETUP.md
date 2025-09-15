# SearXNG Tavily Adapter Setup Guide

## Быстрый старт

1. **Клонируйте репозиторий:**
```bash
git clone <repo-url>
cd searxng-docker-tavily-adapter
```

2. **Настройте конфигурацию:**
```bash
# Скопируйте примеры конфигурации
cp config.example.yaml config.yaml
cp .env.example .env

# Сгенерируйте секретный ключ (ОБЯЗАТЕЛЬНО!)
python3 -c "import secrets; print(secrets.token_hex(32))"
# Вставьте сгенерированный ключ в config.yaml как server.secret_key
```

3. **Запустите основные сервисы:**
```bash
# Без Cloudflare Tunnel (рекомендуется для начала)
docker compose up -d

# С Cloudflare Tunnel (требует настройки)
docker compose --profile cloudflare up -d
```

## Доступ к сервисам

- **SearXNG**: http://localhost:8999
- **Tavily Adapter**: http://localhost:8000 
- **Health Check**: http://localhost:8000/health

## Конфигурация Cloudflare Tunnel (опционально)

Для публичного доступа через Cloudflare:

1. **Создайте tunnel:**
```bash
# Установите cloudflared
brew install cloudflared  # macOS
# или wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

# Авторизуйтесь
cloudflared tunnel login

# Создайте tunnel
cloudflared tunnel create searxng-tunnel

# Получите токен
cloudflared tunnel token searxng-tunnel
```

2. **Настройте токен:**
```bash
# Добавьте в .env файл
echo "CLOUDFLARE_TUNNEL_TOKEN=your_token_here" >> .env
```

3. **Запустите с Cloudflare:**
```bash
docker compose --profile cloudflare up -d
```

## Локальная разработка

Для разработки адаптера без Docker:

```bash
cd simple_tavily_adapter

# Создайте .env для тестов
echo "ADAPTER_PORT=8013" > .env

# Установите зависимости
uv sync

# Запустите адаптер
uv run python main.py

# Тестирование
uv run python test_unit.py
uv run python test_client.py
```

## Устранение проблем

### SearXNG не стартует
- Проверьте, что `config.yaml` существует и содержит `secret_key`
- Убедитесь, что порты 8999 и 8000 свободны

### Cloudflared ошибки
- Проверьте токен в `.env` файле
- Убедитесь, что tunnel создан и активен в Cloudflare Dashboard

### Капчи от поисковиков
- Anti-captcha система включена по умолчанию
- Настройте в `.env`: `MAX_SEARCH_RETRIES=5`

## Архитектура

```
Internet
    ↓
[Cloudflare Tunnel] (опционально)
    ↓
[Tavily Adapter :8000] ← API запросы
    ↓
[SearXNG :8999] ← поиск через поисковики
    ↓
[Redis/Valkey] ← кэширование
```

## API Использование

```bash
# Основной поиск
curl -X POST "http://localhost:8000/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "python programming", "max_results": 5}'

# С raw content в Markdown (по умолчанию)
curl -X POST "http://localhost:8000/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "python", "include_raw_content": true}'

# Текстовый формат
curl -X POST "http://localhost:8000/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "python", "include_raw_content": true, "content_format": "text"}'
```
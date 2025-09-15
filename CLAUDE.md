# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

This is a **SearXNG Docker Tavily Adapter** - a free Tavily API replacement using SearXNG. The system consists of:

- **SearXNG** (port 8999) - Meta-search engine that aggregates results from Google, DuckDuckGo, Brave, etc.
- **Tavily Adapter** (port 8000) - FastAPI service that provides Tavily-compatible API interface
- **Redis/Valkey** - Caching layer for SearXNG
- **Unified Configuration** - Single `config.yaml` file configures all services

### Key Components

- `simple_tavily_adapter/` - FastAPI adapter service (Python)
  - `main.py` - FastAPI application with `/search` endpoint
  - `tavily_client.py` - Drop-in replacement for Tavily Python client  
  - `config_loader.py` - YAML config parsing
- `docker-compose.yaml` - Multi-service orchestration
- `config.yaml` - Unified configuration for SearXNG + adapter
- `Caddyfile` - Reverse proxy configuration

## Essential Commands

### Setup & Configuration
```bash
# Initial setup (required)
cp config.example.yaml config.yaml
# Edit config.yaml and change server.secret_key (minimum 32 chars)

# Start all services
docker compose up -d

# View logs
docker compose logs tavily-adapter
docker compose logs searxng

# Stop services
docker compose down
```

### Development Commands
```bash
# Local development of adapter
cd simple_tavily_adapter
pip install -r requirements.txt
python main.py

# Run adapter tests
python test_client.py

# Health checks
curl -f http://localhost:8000/health
curl "http://localhost:8999/search?q=test&format=json"

# Test API endpoint
curl -X POST "http://localhost:8000/search" \
     -H "Content-Type: application/json" \
     -d '{"query": "test query", "max_results": 3}'
```

### Generate Secret Key (Required)
```bash
# For config.yaml server.secret_key
python3 -c "import secrets; print(secrets.token_hex(32))"
# or
openssl rand -hex 32
```

## Configuration Notes

- **Critical**: Must change `server.secret_key` in `config.yaml` (32+ characters)
- SearXNG and Adapter share the same `config.yaml` file
- SearXNG config is at root level, Adapter config under `adapter:` section
- Adapter connects to SearXNG via internal Docker network: `http://searxng:8080`

## API Compatibility

The adapter provides 100% Tavily API compatibility:
- Same request/response format
- Drop-in replacement for `tavily-python` client
- Supports `include_raw_content` with web scraping
- No API keys required (ignored if provided)

## Web Scraping Feature

When `include_raw_content: true`:
1. SearXNG returns search results with URLs
2. Adapter scrapes each URL in parallel
3. HTML is cleaned and converted to text (max 2500 chars)
4. Full content returned in `raw_content` field

Scraping timeout and limits configured in `config.yaml` under `adapter.scraper`.
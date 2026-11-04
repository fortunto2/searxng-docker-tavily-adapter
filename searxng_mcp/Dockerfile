FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.29 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock server.py ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH" MCP_TRANSPORT=http TAVILY_API_URL=http://tavily-adapter:8000
EXPOSE 8000
CMD ["python", "server.py"]

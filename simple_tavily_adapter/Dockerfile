FROM python:3.12-slim

ENV PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    UV_VERSION=0.5.29

# Install system dependencies
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY . .

# Install dependencies and project
RUN uv sync --no-dev

# Add virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

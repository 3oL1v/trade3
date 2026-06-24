# syntax=docker/dockerfile:1
# Backend image: FastAPI + the always-on collectors (auto-signal forward test,
# live market engine). No GPU and no Ollama — the AI analyst stays optional and
# is disabled in the cloud via TRADE3_OLLAMA_ENABLED=false.
FROM python:3.12-slim

# uv for fast, reproducible installs from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies as a cached layer, then the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
RUN uv sync --frozen --no-dev

# SQLite journals live here; mount a volume to persist them across restarts.
RUN mkdir -p /app/data
EXPOSE 8000

CMD ["uvicorn", "trade3_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

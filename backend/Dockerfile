# AgentGrid API (FastAPI + LangGraph). One process serves HTTP, WebSockets and the background job runner.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    FASTEMBED_CACHE=/app/.data/fastembed HF_HUB_DISABLE_SYMLINKS_WARNING=1

COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# Bake the local embedding model into the image so cold starts don't download it.
RUN uv run --no-dev python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/.data/fastembed')" \
    && useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
# Single worker on purpose: WebSocket rooms and per-conversation locks live in this process (see docs/SCALING.md).
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

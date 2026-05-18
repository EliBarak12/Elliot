# Multi-stage build: produce a slim runtime image that doesn't ship pip / uv.
# Stage 1 — build the resolved venv with uv.
FROM python:3.13-slim AS build
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
# uv.lock covers the whole workspace, so `uv sync --frozen` needs every
# workspace member present — even the ones this image doesn't run.
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/connector-runtime packages/connector-runtime
COPY packages/mcp-plugin packages/mcp-plugin
RUN pip install --no-cache-dir uv \
 && uv sync --frozen --no-dev

# Stage 2 — slim runtime, non-root.
FROM python:3.13-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
 && mkdir -p /app/.elliot \
 && chown -R app:app /app
COPY --from=build --chown=app:app /app /app
USER app
EXPOSE 3001
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -fsS http://127.0.0.1:3001/health || exit 1
CMD ["uvicorn", "elliot_connector_runtime.server:app", "--host", "0.0.0.0", "--port", "3001"]

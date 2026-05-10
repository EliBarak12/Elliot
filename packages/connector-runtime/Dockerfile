FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/connector-runtime packages/connector-runtime
RUN pip install uv && uv sync --frozen --no-dev
EXPOSE 3001
CMD ["uv", "run", "uvicorn", "elliot_connector_runtime.server:app", \
     "--host", "0.0.0.0", "--port", "3001"]

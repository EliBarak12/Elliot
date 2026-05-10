FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/mcp-plugin packages/mcp-plugin
RUN pip install uv && uv sync --frozen --no-dev
EXPOSE 3000
CMD ["uv", "run", "uvicorn", "elliot_mcp_plugin.main:app", \
     "--host", "0.0.0.0", "--port", "3000"]

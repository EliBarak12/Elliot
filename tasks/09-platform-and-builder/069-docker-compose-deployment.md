# Task 069 — Docker Compose + Production Deployment

## Goal
Provide a `docker-compose.yml` that spins up all Elliot services in one command, plus an `.env.example` with every variable documented. Users can go from zero to running on a server without touching `uvicorn` or `vite` directly.

## Files to create

### `docker-compose.yml`

```yaml
services:
  plugin:
    build:
      context: .
      dockerfile: packages/mcp-plugin/Dockerfile
    ports:
      - "3000:3000"
    env_file: .env
    volumes:
      - ./connectors:/app/connectors:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/healthz"]
      interval: 30s
      retries: 3

  runtime:
    build:
      context: .
      dockerfile: packages/connector-runtime/Dockerfile
    ports:
      - "3001:3001"
    env_file: .env
    volumes:
      - ./connectors:/app/connectors:ro
      - elliot-data:/app/.elliot
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3001/healthz"]
      interval: 30s
      retries: 3

  studio:
    build:
      context: packages/studio
      dockerfile: Dockerfile
    ports:
      - "80:80"
    env_file: .env
    depends_on:
      - plugin
      - runtime

  # Optional: remote observation DB
  # Enable with: docker compose --profile mysql up
  mysql:
    image: mysql:8.0
    profiles: ["mysql"]
    environment:
      MYSQL_DATABASE: elliot
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
    volumes:
      - mysql-data:/var/lib/mysql
    ports:
      - "3306:3306"

volumes:
  elliot-data:
  mysql-data:
```

### `packages/mcp-plugin/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/mcp-plugin packages/mcp-plugin
RUN pip install uv && uv sync --frozen --no-dev
EXPOSE 3000
CMD ["uv", "run", "uvicorn", "elliot_mcp_plugin.server:app", "--host", "0.0.0.0", "--port", "3000"]
```

### `packages/connector-runtime/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/connector-runtime packages/connector-runtime
RUN pip install uv && uv sync --frozen --no-dev
EXPOSE 3001
CMD ["uv", "run", "uvicorn", "elliot_connector_runtime.server:app", "--host", "0.0.0.0", "--port", "3001"]
```

### `packages/studio/Dockerfile`

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY packages/studio/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### `.env.example`

```dotenv
# ── Elliot Auth ────────────────────────────────────────────
# Leave blank for local dev (no auth). Set for any server deployment.
ELLIOT_API_KEY=
VITE_API_KEY=

# ── Connectors ─────────────────────────────────────────────
ELLIOT_CONNECTORS_DIR=./connectors

# ── Observation DB ─────────────────────────────────────────
# Default: local SQLite. For MySQL: mysql+pymysql://user:pass@host/elliot
ELLIOT_DB_URL=sqlite:///.elliot/observations.db
# Only needed when using the mysql profile:
MYSQL_ROOT_PASSWORD=changeme

# ── Logging ────────────────────────────────────────────────
LOG_LEVEL=INFO

# ── Studio ─────────────────────────────────────────────────
VITE_PLUGIN_URL=http://localhost:3000
VITE_RUNTIME_URL=http://localhost:3001
```

## Usage

```bash
# Local dev (existing Procfile workflow unchanged)
honcho start

# Production — all services
cp .env.example .env   # fill in values
docker compose up -d

# Production — with remote MySQL
docker compose --profile mysql up -d
```

## Estimate
4–5 hours

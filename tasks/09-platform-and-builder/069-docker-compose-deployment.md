# Task 069 — Docker Compose + Production Deployment

## Goal
Provide a `docker-compose.yml` that spins up all Elliot services in one command, plus an `.env.example` with every variable documented.

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

  # Optional remote observation DB
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
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/mcp-plugin packages/mcp-plugin
RUN pip install uv && uv sync --frozen --no-dev
EXPOSE 3000
CMD ["uv", "run", "uvicorn", "elliot_mcp_plugin.main:app", \
     "--host", "0.0.0.0", "--port", "3000"]
```

### `packages/connector-runtime/Dockerfile`

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/connector-runtime packages/connector-runtime
RUN pip install uv && uv sync --frozen --no-dev
EXPOSE 3001
CMD ["uv", "run", "uvicorn", "elliot_connector_runtime.server:app", \
     "--host", "0.0.0.0", "--port", "3001"]
```

### `packages/studio/Dockerfile`

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile
COPY . .
ARG VITE_PLUGIN_URL=http://localhost:3000
ARG VITE_RUNTIME_URL=http://localhost:3001
ARG VITE_API_KEY
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### `packages/studio/nginx.conf`

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### `.env.example`

```dotenv
# ── Auth ────────────────────────────────────────────────────────
# Leave blank for local dev (no auth). Set for any server deployment.
ELLIOT_API_KEY=
VITE_API_KEY=

# ── Connectors ───────────────────────────────────────────────
ELLIOT_CONNECTORS_DIR=./connectors
# Single-connector mode:
ELLIOT_CONNECTOR=./connectors/my-api.connector.json

# ── Observation DB ───────────────────────────────────────────
# Default: local SQLite. For MySQL: mysql+pymysql://user:pass@host/elliot
ELLIOT_DB_URL=sqlite:///.elliot/observations.db
MYSQL_ROOT_PASSWORD=changeme

# ── Sessions / Audit ─────────────────────────────────────────
ELLIOT_SESSIONS_LOG=.elliot/sessions.ndjson
ELLIOT_AUDIT_LOG=.elliot/audit.ndjson

# ── Rate limiting ──────────────────────────────────────────
ELLIOT_RATE_LIMIT=120/minute

# ── Logging ────────────────────────────────────────────────
LOG_LEVEL=INFO

# ── Studio ───────────────────────────────────────────────
VITE_PLUGIN_URL=http://localhost:3000
VITE_RUNTIME_URL=http://localhost:3001
```

## Usage

```bash
# Local dev (Procfile workflow unchanged)
honcho start

# Production
cp .env.example .env   # fill in values
docker compose up -d

# Production with MySQL observation DB
docker compose --profile mysql up -d
```

## Done When
- [ ] `docker compose up -d` starts plugin + runtime + studio without error
- [ ] `docker compose --profile mysql up -d` starts all 4 services
- [ ] `curl http://localhost:3000/healthz` returns 200 inside container
- [ ] Studio served at `http://localhost:80` loads correctly
- [ ] `.env.example` documents every variable used anywhere in the codebase

## Estimate
4–5 hours

# Multi-stage build: vite → nginx-served static bundle, non-root.
FROM node:22-alpine AS build
WORKDIR /app
# Pin pnpm to the same major as CI to keep lockfile resolution consistent.
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# No VITE_* build args: the browser bundle talks only to same-origin /api/*
# paths. Backend origins + the API key are supplied at *runtime* to nginx
# (see the runtime stage) and never baked into the JS.
RUN pnpm --filter @elliot/studio run build

FROM nginx:alpine AS runtime
# Drop root for the worker processes — nginx still needs root to bind privileged
# ports but we serve on the unprivileged 8080 below.
RUN apk add --no-cache curl \
 && adduser -D -u 10001 app
COPY --from=build --chown=app:app /app/packages/studio/dist /usr/share/nginx/html
# nginx.conf is a *.template: the stock nginx entrypoint runs envsubst over
# /etc/nginx/templates/*.template at container start, writing the rendered
# config to /etc/nginx/conf.d/.
COPY --chown=root:root packages/studio/nginx.conf.template /etc/nginx/templates/default.conf.template
# Only substitute Elliot-owned vars so nginx runtime vars ($uri, $1, ...) in the
# template are left untouched by envsubst.
ENV NGINX_ENVSUBST_FILTER="ELLIOT_"
# Runtime config templated into the nginx conf. Override per deployment.
# ELLIOT_PLUGIN_ORIGIN / ELLIOT_RUNTIME_ORIGIN are the reverse-proxy targets;
# ELLIOT_API_KEY is injected as X-Elliot-Key on every proxied request (empty =
# unauthenticated, for local dev). Defaults match the dev localhost services.
ENV ELLIOT_PLUGIN_ORIGIN=http://localhost:3000 \
    ELLIOT_RUNTIME_ORIGIN=http://localhost:3001 \
    ELLIOT_API_KEY="" \
    ELLIOT_HSTS=""
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=5s \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
# nginx's stock entrypoint already drops to the `nginx` user for workers.

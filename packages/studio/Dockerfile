# Multi-stage build: vite → nginx-served static bundle, non-root.
FROM node:22-alpine AS build
WORKDIR /app
# Pin pnpm to the same major as CI to keep lockfile resolution consistent.
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# NOTE: VITE_API_KEY is baked into the bundle and is therefore PUBLIC. It's a
# deployment-scoped token, not a per-user secret. Never pass a high-trust
# backend secret here.
ARG VITE_PLUGIN_URL=http://localhost:3000
ARG VITE_RUNTIME_URL=http://localhost:3001
ARG VITE_API_KEY=
ENV VITE_PLUGIN_URL=$VITE_PLUGIN_URL \
    VITE_RUNTIME_URL=$VITE_RUNTIME_URL \
    VITE_API_KEY=$VITE_API_KEY
RUN pnpm --filter @elliot/studio run build

FROM nginx:alpine AS runtime
# Drop root for the worker processes — nginx still needs root to bind privileged
# ports but we serve on the unprivileged 8080 below.
RUN apk add --no-cache curl \
 && adduser -D -u 10001 app
COPY --from=build --chown=app:app /app/packages/studio/dist /usr/share/nginx/html
COPY --chown=root:root packages/studio/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=5s \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
# nginx's stock entrypoint already drops to the `nginx` user for workers.

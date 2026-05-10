FROM node:22-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile
COPY . .
ARG VITE_PLUGIN_URL=http://localhost:3000
ARG VITE_RUNTIME_URL=http://localhost:3001
ARG VITE_API_KEY
RUN pnpm --filter @elliot/studio run build

FROM nginx:alpine
COPY --from=build /app/packages/studio/dist /usr/share/nginx/html
COPY packages/studio/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

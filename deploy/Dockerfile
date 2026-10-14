# Caddy image with the built website baked in. Build context: repo root.

# ---------- Stage 1: build the Vue website ----------
FROM node:22-bookworm-slim AS frontend

WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
# Same origin in production: the API lives under /api on this host.
RUN VITE_API_BASE_URL=/api npm run build


# ---------- Stage 2: Caddy ----------
FROM caddy:2.8-alpine

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/dist /srv

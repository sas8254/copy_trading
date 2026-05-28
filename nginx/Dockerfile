# ---------- Stage 1: build the frontend ----------
FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /app

# Build context is the project root (set in docker-compose.yml).
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./

# Same-origin in prod: API lives under /api on the nginx host.
RUN echo "VITE_API_BASE_URL=/api" > .env.production
RUN npm run build


# ---------- Stage 2: nginx serving the built assets ----------
FROM nginx:1.27-alpine

# Replace the default config with ours.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Copy the built SPA into nginx's web root.
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

EXPOSE 80

# (Default nginx CMD is fine — kept implicit.)

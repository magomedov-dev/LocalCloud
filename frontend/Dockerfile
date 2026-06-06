# syntax=docker/dockerfile:1

# ── Этап 1: сборка Vite SPA ──────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Сначала устанавливаем зависимости для лучшего кеширования слоёв.
COPY package.json package-lock.json ./
RUN npm ci

# Собираем production-бандл (tsc -b && vite build → /app/dist).
COPY . .
RUN npm run build

# ── Этап 2: раздача статического бандла через nginx ─────────────────────────
FROM nginx:1.27-alpine

# Конфигурация SPA-сервера: fallback для History API и кеширование ассетов.
# API и объектное хранилище проксируются отдельным gateway nginx-сервисом.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

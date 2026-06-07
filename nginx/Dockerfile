# syntax=docker/dockerfile:1

# ── Gateway / reverse proxy LocalCloud ───────────────────────────────────────
# Единая публичная точка входа:
# раздаёт SPA через frontend-сервис,
# REST API через /api → api-сервис
# и presigned URL объектного хранилища
# через bucket-пути → minio-сервис.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

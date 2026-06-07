# syntax=docker/dockerfile:1

# ── Серверная часть LocalCloud (FastAPI API + фоновый рабочий интерфейс) ────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Зависимости сначала кэшируются до тех пор, пока pyproject.toml / uv.lock не изменятся.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# 2) Исходники приложения.
COPY . .
RUN uv sync --frozen

# 3) Точка входа: ожидает Postgres/MinIO, запускает migrations + admin seed (только API),
#    затем выполняет сервисную команду. Нормализуйте CRLF в случае проверки Windows.
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

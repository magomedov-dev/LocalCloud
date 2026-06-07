#!/bin/sh
# ── Точка входа backend LocalCloud ───────────────────────────────────────────
# 1. Ждёт, пока PostgreSQL и MinIO начнут принимать TCP-подключения.
# 2. Только для API-сервиса при RUN_MIGRATIONS=true: применяет миграции Alembic
#    и создаёт администратора — обе операции идемпотентны.
# 3. Выполняет команду сервиса через exec: uvicorn для API или worker для воркера.
set -e

python <<'PY'
import os
import socket
import sys
import time


def wait_for(host, port, name, timeout=180):
    deadline = time.time() + timeout
    port = int(port)
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"[entrypoint] {name} is ready at {host}:{port}", flush=True)
                return
        except OSError:
            print(f"[entrypoint] waiting for {name} at {host}:{port} ...", flush=True)
            time.sleep(2)
    print(
        f"[entrypoint] ERROR: timed out waiting for {name} at {host}:{port}",
        file=sys.stderr,
        flush=True,
    )
    sys.exit(1)


wait_for(os.getenv("POSTGRES_HOST", "postgres"), os.getenv("POSTGRES_PORT", "5432"), "PostgreSQL")
wait_for(os.getenv("MINIO_HOST", "minio"), os.getenv("MINIO_PORT", "9000"), "MinIO")
PY

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
    alembic upgrade head

    echo "[entrypoint] Seeding admin user (idempotent)..."
    python seed_admin.py || echo "[entrypoint] WARN: admin seed skipped/failed, continuing."
fi

echo "[entrypoint] Starting: $*"
exec "$@"

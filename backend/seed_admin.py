import asyncio
import os
import uuid
from datetime import UTC, datetime

import asyncpg
from passlib.context import CryptContext

DB_DSN = os.getenv("DATABASE_DSN") or (
    f"postgresql://{os.getenv('POSTGRES_USER', 'localcloud')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'localcloud')}@"
    f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
    f"{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'localcloud')}"
)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@localcloud.dev")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@LocalCloud123")

# Дефолтный пароль администратора опубликован в репозитории и .env.example,
# поэтому в production он недопустим. Вне DEBUG отказываемся создавать админа
# с известным паролем — иначе первый же деплой «из коробки» уже скомпрометирован.
_DEBUG = os.getenv("DEBUG", "false").strip().lower() in ("1", "true", "yes", "on")
_DEFAULT_ADMIN_PASSWORD = "Admin@LocalCloud123"

ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12)


async def main() -> None:
    """Создаёт администратора и квоту по умолчанию.

    Подключается к базе данных, создаёт администратора с системной ролью
    `admin` и добавляет запись квоты по умолчанию.

    Raises:
        asyncpg.PostgresError: Если запрос к PostgreSQL завершился ошибкой.
        OSError: Если не удалось установить сетевое подключение к базе данных.
    """

    if not _DEBUG and ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD:
        raise SystemExit(
            "Отказ создания администратора: используется дефолтный пароль "
            "ADMIN_PASSWORD. Задайте надёжный ADMIN_PASSWORD через переменные "
            "окружения (.env) перед production-развёртыванием или включите DEBUG "
            "для локальной разработки."
        )

    conn = await asyncpg.connect(DB_DSN)
    try:
        # Проверка, существует ли пользователь с правами администратора
        admin_id = await conn.fetchval(
            "SELECT id FROM users WHERE email=$1", ADMIN_EMAIL
        )
        if not admin_id:
            admin_id = uuid.uuid4()
            pw_hash = ctx.hash(ADMIN_PASSWORD)
            now = datetime.now(UTC)
            await conn.execute(
                """INSERT INTO users (id, email, username, password_hash, status,
                   role, approved_at, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, 'active', 'admin', $5, $5, $5)""",
                admin_id,
                ADMIN_EMAIL,
                ADMIN_USERNAME,
                pw_hash,
                now,
            )
            print(f"Created admin user: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            print(f"Admin user exists: {ADMIN_EMAIL}")

        # Создание квоты по умолчанию для администратора
        quota_exists = await conn.fetchval(
            "SELECT id FROM user_quotas WHERE user_id=$1", admin_id
        )
        if not quota_exists:
            await conn.execute(
                """INSERT INTO user_quotas (id, user_id, storage_limit_bytes, storage_used_bytes,
                   max_file_size_bytes, files_limit, files_used, public_links_limit, public_links_used,
                   active_upload_sessions_limit, active_upload_sessions_used,
                   created_at, updated_at)
                   VALUES ($1, $2, 10737418240, 0, 1073741824, 10000, 0, 100, 0, 10, 0, now(), now())""",
                uuid.uuid4(),
                admin_id,
            )
            print("Created default quota for admin")

        print("\n=== Admin user ready ===")
        print(f"  Email:    {ADMIN_EMAIL}")
        print(f"  Username: {ADMIN_USERNAME}")
        print(f"  Password: {ADMIN_PASSWORD}")
        print(f"  ID:       {admin_id}")

    finally:
        await conn.close()


asyncio.run(main())

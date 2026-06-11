"""Проверка секретов на небезопасные значения по умолчанию.

Дефолты секретов в `core.constants` и `.env.example` намеренно нестрогие — они
позволяют поднять стек одной командой для локальной разработки. Но если такой
секрет утечёт в production (забыли заменить при деплое), это прямая
компрометация. Этот модуль выявляет оставшиеся дефолтные/placeholder-значения и
позволяет приложению отказаться стартовать вне debug-режима.

Модуль не зависит от слоёв приложения и пригоден для unit-тестирования.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Settings

# Подстроки-маркеры незаменённых секретов (регистронезависимо). Покрывают и
# литералы из core.constants, и placeholder-комментарии из .env.example.
_INSECURE_MARKERS: tuple[str, ...] = (
    "change-me",
    "change_me",
    "changeme",
    "development-secret",
    "localcloud_password",
)

# Точные дефолтные значения, которые сами по себе небезопасны как секрет, даже
# если не содержат маркер-подстроку.
_INSECURE_EXACT: tuple[str, ...] = (
    "localcloud",
)


@dataclass(frozen=True, slots=True)
class InsecureSecret:
    """Найденный небезопасный секрет.

    Attributes:
        field: Человекочитаемое имя секрета (имя переменной окружения).
        reason: Почему значение считается небезопасным.
    """

    field: str
    reason: str


def _is_insecure(value: str | None) -> str | None:
    """Возвращает причину небезопасности значения секрета или ``None``.

    Args:
        value: Значение секрета.

    Returns:
        Строку-причину, если значение пустое, дефолтное или содержит
        placeholder-маркер; иначе ``None``. Не-строки (в реальных Settings
        невозможны, но встречаются в тестовых mock'ах) считаются безопасными.
    """

    if not isinstance(value, str):
        return None
    if not value.strip():
        return "пустое значение"
    normalized = value.strip().lower()
    if normalized in _INSECURE_EXACT:
        return "дефолтное значение по умолчанию"
    for marker in _INSECURE_MARKERS:
        if marker in normalized:
            return f"содержит placeholder-маркер «{marker}»"
    return None


def find_insecure_secrets(settings: Settings) -> list[InsecureSecret]:
    """Находит секреты с небезопасными значениями по умолчанию.

    Проверяет ключевые секреты приложения: ключ подписи JWT, пароль PostgreSQL
    и секретный ключ MinIO. Access key MinIO не секрет и не проверяется.

    Args:
        settings: Настройки приложения.

    Returns:
        Список найденных небезопасных секретов (пустой, если все в порядке).
    """

    candidates = (
        ("SECRET_KEY", settings.security.secret_key),
        ("POSTGRES_PASSWORD", settings.database.postgres_password),
        ("MINIO_SECRET_KEY", settings.storage.minio_secret_key),
    )
    findings: list[InsecureSecret] = []
    for field, value in candidates:
        reason = _is_insecure(value)
        if reason is not None:
            findings.append(InsecureSecret(field=field, reason=reason))
    return findings


def validate_secrets_or_raise(settings: Settings) -> None:
    """Проверяет секреты и в production-режиме запрещает старт с дефолтами.

    В debug-режиме (``DEBUG=true``) найденные проблемы только логируются —
    локальная разработка должна работать «из коробки». Вне debug наличие хотя
    бы одного небезопасного секрета приводит к ``RuntimeError``: лучше явный
    отказ на старте, чем тихая компрометация в проде.

    Args:
        settings: Настройки приложения.

    Raises:
        RuntimeError: Если вне debug-режима найден небезопасный секрет.
    """

    findings = find_insecure_secrets(settings)
    if not findings:
        return

    listing = "; ".join(f"{f.field} ({f.reason})" for f in findings)
    if settings.app.debug:
        from core.logging import get_logger

        get_logger("core.secret_validation").warning(
            "Обнаружены небезопасные секреты по умолчанию (допустимо только в "
            "debug): %s. Замените их перед production-развёртыванием.",
            listing,
        )
        return

    raise RuntimeError(
        "Отказ запуска: обнаружены небезопасные секреты по умолчанию — "
        f"{listing}. Задайте надёжные значения через переменные окружения "
        "(.env) перед запуском в production или включите DEBUG для локальной "
        "разработки."
    )


def warn_if_cookies_insecure(settings: Settings) -> None:
    """Предупреждает, если auth-cookie отдаются без флага ``Secure`` в проде.

    ``COOKIE_SECURE=false`` означает, что cookie аутентификации передаются и по
    HTTP — на публичной сети это позволяет перехватить сессию. За HTTPS
    (TLS на nginx) обязательно выставлять ``COOKIE_SECURE=true``.

    Это не ошибка старта, а громкое предупреждение: для доверенной локальной
    сети без TLS работа по HTTP с ``Secure=false`` легитимна, и достоверно
    определить наличие TLS на уровне приложения нельзя. В debug не логируется
    вовсе.

    Args:
        settings: Настройки приложения.
    """

    if settings.app.debug or settings.cookies.cookie_secure:
        return

    from core.logging import get_logger

    get_logger("core.secret_validation").warning(
        "COOKIE_SECURE=false: auth-cookie передаются без флага Secure (по HTTP). "
        "Для публичного развёртывания за HTTPS выставьте COOKIE_SECURE=true, "
        "иначе сессию можно перехватить. Допустимо только в доверённой сети "
        "без TLS. Пример TLS-конфигурации: nginx/nginx-tls.conf.example."
    )

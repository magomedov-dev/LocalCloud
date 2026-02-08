from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.exc import SQLAlchemyError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database.exceptions import (
    DatabaseTimeoutError,
    TransactionCommitError,
    TransactionError,
    TransactionRollbackError,
)

logger = get_logger("database.transactions")

ModelT = TypeVar("ModelT")


def _build_error_details(
    exc: BaseException,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Формирует диагностические данные для ошибки транзакции.

    Args:
        exc: Исходное исключение.
        extra: Дополнительные диагностические данные, которые нужно добавить
            к базовой информации об ошибке.

    Returns:
        Словарь с диагностическими данными ошибки.
    """

    details: dict[str, Any] = {
        "original_error": str(exc),
        "original_error_type": exc.__class__.__name__,
    }

    if extra:
        details.update(extra)

    return details


async def _rollback_after_failure(session: AsyncSession) -> dict[str, Any]:
    """Пытается выполнить rollback после неудачной операции.

    Используется как вспомогательная функция после ошибки commit. Если rollback
    завершается успешно, возвращает пустой словарь. Если rollback также
    завершается ошибкой, возвращает диагностические данные этой ошибки.

    Args:
        session: Асинхронная SQLAlchemy-сессия.

    Returns:
        Пустой словарь при успешном rollback или словарь с диагностическими
        данными ошибки rollback.
    """

    try:
        await session.rollback()

    except SQLAlchemyError as exc:
        return {
            "rollback_error": str(exc),
            "rollback_error_type": exc.__class__.__name__,
        }

    return {}


async def safe_commit(
    session: AsyncSession,
    *,
    operation: str = "commit",
) -> None:
    """Безопасно фиксирует текущую транзакцию.

    Выполняет `commit` текущей сессии. При ошибке commit пытается выполнить
    rollback, добавляет диагностические данные об исходной ошибке и результате
    rollback, а затем преобразует исключение SQLAlchemy в исключение приложения.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        operation: Название операции для диагностических данных.

    Raises:
        DatabaseTimeoutError: Если commit завершился по timeout.
        TransactionCommitError: Если commit завершился ошибкой SQLAlchemy.
    """

    try:
        await session.commit()

    except TimeoutError as exc:
        rollback_details = await _rollback_after_failure(session)

        details = _build_error_details(
            exc,
            extra={
                "operation": operation,
                **rollback_details,
            },
        )

        raise DatabaseTimeoutError(
            "Время фиксации транзакции базы данных истекло.",
            operation=operation,
            details=details,
            cause=exc,
        ) from exc

    except SQLAlchemyError as exc:
        rollback_details = await _rollback_after_failure(session)

        details = _build_error_details(
            exc,
            extra={
                "operation": operation,
                **rollback_details,
            },
        )

        raise TransactionCommitError(
            "Не удалось зафиксировать транзакцию базы данных.",
            details=details,
            cause=exc,
        ) from exc


async def safe_rollback(
    session: AsyncSession,
    *,
    operation: str = "rollback",
    suppress_errors: bool = False,
) -> None:
    """Безопасно откатывает текущую транзакцию.

    Выполняет `rollback` текущей сессии. Если rollback завершается ошибкой,
    функция либо логирует и подавляет ошибку, либо преобразует её в
    `TransactionRollbackError`.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        operation: Название операции для диагностических данных.
        suppress_errors: Признак подавления ошибки rollback. Если `True`,
            ошибка логируется как warning и не пробрасывается выше.

    Raises:
        TransactionRollbackError: Если rollback завершился ошибкой и
            `suppress_errors` равен `False`.
    """

    try:
        await session.rollback()

    except SQLAlchemyError as exc:
        details = _build_error_details(
            exc,
            extra={"operation": operation},
        )

        if suppress_errors:
            logger.warning(
                "Ошибка rollback подавлена",
                extra=details,
            )
            return

        raise TransactionRollbackError(
            "Не удалось выполнить откат транзакции базы данных.",
            details=details,
            cause=exc,
        ) from exc


async def safe_flush(
    session: AsyncSession,
    *,
    operation: str = "flush",
) -> None:
    """Безопасно синхронизирует изменения текущей сессии с базой данных.

    Выполняет `flush`, отправляя накопленные изменения в базу данных без
    фиксации транзакции. Ошибки SQLAlchemy преобразуются в доменные исключения
    приложения.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        operation: Название операции для диагностических данных.

    Raises:
        DatabaseTimeoutError: Если flush завершился по timeout.
        TransactionError: Если flush завершился ошибкой SQLAlchemy.
    """

    try:
        await session.flush()

    except TimeoutError as exc:
        raise DatabaseTimeoutError(
            "Время синхронизации изменений с базой данных истекло.",
            operation=operation,
            details=_build_error_details(
                exc,
                extra={"operation": operation},
            ),
            cause=exc,
        ) from exc

    except SQLAlchemyError as exc:
        raise TransactionError(
            "Не удалось синхронизировать изменения с базой данных.",
            operation=operation,
            details=_build_error_details(
                exc,
                extra={"operation": operation},
            ),
            cause=exc,
        ) from exc


async def safe_refresh(
    session: AsyncSession,
    instance: ModelT,
    *,
    operation: str = "refresh",
    attribute_names: list[str] | None = None,
) -> ModelT:
    """Безопасно обновляет ORM-объект данными из базы данных.

    Выполняет `refresh` для переданного ORM-объекта. При необходимости
    обновляет только перечисленные атрибуты. Ошибки SQLAlchemy преобразуются
    в доменные исключения приложения.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        instance: ORM-объект, который нужно обновить.
        operation: Название операции для диагностических данных.
        attribute_names: Список атрибутов, которые нужно обновить. Если
            `None`, обновляется весь объект.

    Returns:
        Тот же ORM-объект после обновления из базы данных.

    Raises:
        DatabaseTimeoutError: Если refresh завершился по timeout.
        TransactionError: Если refresh завершился ошибкой SQLAlchemy.
    """

    details_extra = {
        "operation": operation,
        "model": instance.__class__.__name__,
        "attribute_names": attribute_names,
    }

    try:
        await session.refresh(instance, attribute_names=attribute_names)
        return instance

    except TimeoutError as exc:
        raise DatabaseTimeoutError(
            "Время обновления объекта из базы данных истекло.",
            operation=operation,
            details=_build_error_details(exc, extra=details_extra),
            cause=exc,
        ) from exc

    except SQLAlchemyError as exc:
        raise TransactionError(
            "Не удалось обновить объект из базы данных.",
            operation=operation,
            details=_build_error_details(exc, extra=details_extra),
            cause=exc,
        ) from exc


async def ensure_transaction_closed(
    session: AsyncSession,
    *,
    operation: str = "ensure_transaction_closed",
) -> None:
    """Откатывает активную транзакцию, если она есть.

    Проверяет наличие активной транзакции в сессии. Если активной транзакции
    нет, функция завершается без действий. Если транзакция есть, выполняется
    безопасный rollback через `safe_rollback`.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        operation: Название операции для диагностических данных.

    Raises:
        TransactionRollbackError: Если rollback активной транзакции завершился
            ошибкой.
    """

    if not session.in_transaction():
        return

    await safe_rollback(
        session,
        operation=operation,
    )

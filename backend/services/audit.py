from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from enum import Enum
from io import StringIO
from typing import Any, cast
from uuid import UUID

from core.logging import get_logger
from database import (
    DatabaseError,
    EntityNotFoundError,
    UnitOfWorkFactory,
    create_unit_of_work_factory,
)
from database.models.audit import AuditLog
from database.models.enums import AuditAction, AuditResourceType, AuditResult
from database.repositories.audit import AuditSortField
from schemas.audit import (
    AuditExportRequest,
    AuditLogCreate,
    AuditLogListItem,
    AuditLogRead,
    AuditQueryParams,
    AuditSummaryRead,
)
from schemas.common import PageMeta, PageResponse
from services.exceptions import (
    NotFoundServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
)

logger = get_logger("services.audit")

# Полезная нагрузка экспорта журнала аудита.
AuditExportPayload = dict[str, Any]


class AuditService:
    """Сервисный фасад для работы с событиями аудита LocalCloud.

    Сервис не импортирует FastAPI и не строит SQLAlchemy-запросы напрямую.
    Все операции сохранения и чтения выполняются через `UnitOfWork` и
    `AuditLogRepository`, а наружу возвращаются DTO из `schemas.audit`.

    Attributes:
        uow_factory: Фабрика UnitOfWork для создания транзакционных контекстов.
    """

    _SCAN_LIMIT = 100_000
    _EXPORT_DEFAULT_LIMIT = 10_000
    _REPOSITORY_SORT_FIELDS = frozenset(
        {"created_at", "action", "entity_type", "ip_address"}
    )
    _SERVICE_SORT_FIELDS = frozenset(
        {
            "created_at",
            "action",
            "result",
            "resource_type",
            "entity_type",
            "entity_id",
            "ip_address",
            "request_id",
            "correlation_id",
            "user_id",
        }
    )

    def __init__(self, *, uow_factory: UnitOfWorkFactory | None = None) -> None:
        """Инициализирует сервис аудита.

        Args:
            uow_factory: Фабрика UnitOfWork. Если не передана, создаётся
                стандартная фабрика через `create_unit_of_work_factory()`.
        """

        self.uow_factory = uow_factory or create_unit_of_work_factory()

    async def log_event(
        self,
        *,
        action: AuditAction,
        result: AuditResult = AuditResult.SUCCESS,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        resource_type: AuditResourceType | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLogRead:
        """Создаёт и сохраняет одно событие аудита.

        Args:
            action: Тип действия, которое фиксируется в журнале аудита.
            result: Результат действия.
            user_id: Идентификатор пользователя, связанного с событием.
            entity_type: Тип бизнес-сущности, связанной с событием.
            entity_id: Идентификатор бизнес-сущности.
            resource_type: Тип ресурса, связанного с событием.
            request_id: Идентификатор HTTP-запроса или внешней операции.
            correlation_id: Идентификатор корреляции для связанных операций.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            message: Человекочитаемое описание события.
            error_code: Машинно-читаемый код ошибки, если событие неуспешное.
            metadata: Дополнительные JSON-сериализуемые данные события.

        Returns:
            DTO созданного события аудита.

        Raises:
            ServiceError: Если созданное событие не удалось получить после
                сохранения или произошла сервисная ошибка.
            DatabaseError: Преобразуется в сервисную ошибку через
                `service_error_from_database()`.
        """

        created_read: AuditLogRead | None = None
        try:
            async with self.uow_factory() as uow:
                created_log = await uow.audit.create_event(
                    user_id=user_id,
                    action=action,
                    result=result,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    resource_type=resource_type,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    message=self._normalize_optional_string(message),
                    error_code=error_code,
                    metadata=self._normalize_metadata(metadata),
                    flush=True,
                    refresh=True,
                )
                snapshot = _audit_log_snapshot(created_log)
                await uow.commit()
                created_read = AuditLogRead.model_validate(snapshot)

            if created_read is None:
                raise ServiceError(
                    "Не удалось получить созданное событие аудита.",
                    service="audit",
                    operation="log_event",
                )
            return created_read

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="log_event",
                service="audit",
                message="Не удалось записать событие аудита.",
            ) from exc
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation="log_event",
                message="Не удалось записать событие аудита.",
            ) from exc

    async def log_from_schema(self, data: AuditLogCreate) -> AuditLogRead:
        """Создаёт событие аудита из DTO `AuditLogCreate`.

        Args:
            data: Входная схема с данными события аудита.

        Returns:
            DTO созданного события аудита.

        Raises:
            ServiceError: Если событие не удалось сохранить.
        """

        return await self.log_event(
            user_id=data.user_id,
            action=data.action,
            result=data.result,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            resource_type=data.resource_type,
            request_id=data.request_id,
            correlation_id=data.correlation_id,
            ip_address=data.ip_address,
            user_agent=data.user_agent,
            message=data.message,
            error_code=data.error_code,
            metadata=data.metadata,
        )

    async def log_success(self, *, action: AuditAction, **kwargs: Any) -> AuditLogRead:
        """Создаёт успешное событие аудита.

        Args:
            action: Тип выполненного действия.
            **kwargs: Дополнительные параметры события, передаваемые в
                `log_event()`.

        Returns:
            DTO созданного успешного события аудита.

        Raises:
            ServiceError: Если событие не удалось сохранить.
        """

        return await self.log_event(action=action, result=AuditResult.SUCCESS, **kwargs)

    async def log_failure(
        self,
        *,
        action: AuditAction,
        error_code: str | None = None,
        **kwargs: Any,
    ) -> AuditLogRead:
        """Создаёт неуспешное событие аудита.

        Args:
            action: Тип действия, завершившегося ошибкой.
            error_code: Машинно-читаемый код ошибки.
            **kwargs: Дополнительные параметры события, передаваемые в
                `log_event()`.

        Returns:
            DTO созданного неуспешного события аудита.

        Raises:
            ServiceError: Если событие не удалось сохранить.
        """

        return await self.log_event(
            action=action, result=AuditResult.FAILURE, error_code=error_code, **kwargs
        )

    async def log_denied(self, *, action: AuditAction, **kwargs: Any) -> AuditLogRead:
        """Создаёт событие аудита для отказа в доступе.

        Args:
            action: Тип действия, которое было запрещено.
            **kwargs: Дополнительные параметры события, передаваемые в
                `log_event()`.

        Returns:
            DTO созданного события отказа.

        Raises:
            ServiceError: Если событие не удалось сохранить.
        """

        return await self.log_event(action=action, result=AuditResult.DENIED, **kwargs)

    async def log_system_event(
        self,
        *,
        action: AuditAction,
        result: AuditResult = AuditResult.SUCCESS,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        resource_type: AuditResourceType | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLogRead:
        """Создаёт системное событие аудита без привязки к пользователю.

        Args:
            action: Тип системного действия.
            result: Результат системного действия.
            entity_type: Тип бизнес-сущности, связанной с событием.
            entity_id: Идентификатор бизнес-сущности.
            resource_type: Тип ресурса, связанного с событием.
            request_id: Идентификатор запроса.
            correlation_id: Идентификатор корреляции.
            message: Человекочитаемое описание события.
            error_code: Машинно-читаемый код ошибки.
            metadata: Дополнительные JSON-сериализуемые данные события.

        Returns:
            DTO созданного системного события аудита.

        Raises:
            ServiceError: Если событие не удалось сохранить.
        """

        return await self.log_event(
            action=action,
            result=result,
            user_id=None,
            entity_type=entity_type,
            entity_id=entity_id,
            resource_type=resource_type,
            request_id=request_id,
            correlation_id=correlation_id,
            message=message,
            error_code=error_code,
            metadata=metadata,
        )

    async def log_user_event(
        self,
        *,
        user_id: UUID,
        action: AuditAction,
        result: AuditResult = AuditResult.SUCCESS,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        resource_type: AuditResourceType | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditLogRead:
        """Создаёт пользовательское событие аудита.

        Args:
            user_id: Идентификатор пользователя, связанного с событием.
            action: Тип пользовательского действия.
            result: Результат пользовательского действия.
            entity_type: Тип бизнес-сущности, связанной с событием.
            entity_id: Идентификатор бизнес-сущности.
            resource_type: Тип ресурса, связанного с событием.
            request_id: Идентификатор запроса.
            correlation_id: Идентификатор корреляции.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            message: Человекочитаемое описание события.
            error_code: Машинно-читаемый код ошибки.
            metadata: Дополнительные JSON-сериализуемые данные события.

        Returns:
            DTO созданного пользовательского события аудита.

        Raises:
            ServiceError: Если событие не удалось сохранить.
        """

        return await self.log_event(
            action=action,
            result=result,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            resource_type=resource_type,
            request_id=request_id,
            correlation_id=correlation_id,
            ip_address=ip_address,
            user_agent=user_agent,
            message=message,
            error_code=error_code,
            metadata=metadata,
        )

    async def get_log(self, log_id: UUID) -> AuditLogRead:
        """Возвращает одно событие аудита по идентификатору.

        Args:
            log_id: Идентификатор события аудита.

        Returns:
            DTO найденного события аудита.

        Raises:
            NotFoundServiceError: Если событие аудита не найдено.
            ServiceError: Если событие не удалось получить.
        """

        log_read: AuditLogRead | None = None
        try:
            async with self.uow_factory() as uow:
                audit_log = await uow.audit.get_required_log_by_id(log_id)
                snapshot = _audit_log_snapshot(audit_log)
                log_read = AuditLogRead.model_validate(snapshot)

            if log_read is None:
                raise ServiceError(
                    "Не удалось получить событие аудита.",
                    service="audit",
                    operation="get_log",
                )
            return log_read

        except EntityNotFoundError as exc:
            raise NotFoundServiceError(
                "Событие аудита не найдено.",
                entity_name="AuditLog",
                entity_id=log_id,
                cause=exc,
            ) from exc
        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="get_log",
                service="audit",
                message="Не удалось получить событие аудита.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation="get_log", message="Не удалось получить событие аудита."
            ) from exc

    async def list_logs(
        self, params: AuditQueryParams
    ) -> PageResponse[AuditLogListItem]:
        """Возвращает постраничный список событий аудита.

        Args:
            params: Параметры фильтрации, сортировки и пагинации журнала аудита.

        Returns:
            Страница событий аудита с метаданными пагинации.

        Raises:
            ServiceError: Если журнал аудита не удалось получить.
        """

        try:
            logs = await self._load_filtered_logs(params=params, ignore_pagination=True)
            total = len(logs)
            page_logs = logs[params.offset : params.offset + params.limit]

            return PageResponse[AuditLogListItem](
                items=[
                    AuditLogListItem.model_validate(_audit_log_snapshot(log))
                    for log in page_logs
                ],
                meta=PageMeta(
                    limit=params.limit,
                    offset=params.offset,
                    total=total,
                    count=len(page_logs),
                ),
            )

        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="list_logs",
                service="audit",
                message="Не удалось получить журнал аудита.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc, operation="list_logs", message="Не удалось получить журнал аудита."
            ) from exc

    async def get_summary(self, params: AuditQueryParams) -> AuditSummaryRead:
        """Формирует сводку аудита по тем же фильтрам, что и `list_logs()`.

        Args:
            params: Параметры фильтрации журнала аудита.

        Returns:
            Сводка с общим количеством событий и группировками по действию,
            типу ресурса и результату.

        Raises:
            ServiceError: Если сводку аудита не удалось сформировать.
        """

        try:
            logs = await self._load_filtered_logs(params=params, ignore_pagination=True)

            by_action: dict[AuditAction, int] = {}
            by_resource_type: dict[AuditResourceType, int] = {}
            by_result: dict[AuditResult, int] = {}

            for audit_log in logs:
                by_action[audit_log.action] = by_action.get(audit_log.action, 0) + 1
                by_result[audit_log.result] = by_result.get(audit_log.result, 0) + 1
                if audit_log.resource_type is not None:
                    by_resource_type[audit_log.resource_type] = (
                        by_resource_type.get(audit_log.resource_type, 0) + 1
                    )

            return AuditSummaryRead(
                total_count=len(logs),
                success_count=by_result.get(AuditResult.SUCCESS, 0),
                failure_count=by_result.get(AuditResult.FAILURE, 0),
                denied_count=by_result.get(AuditResult.DENIED, 0),
                warning_count=by_result.get(AuditResult.WARNING, 0),
                by_action=by_action,
                by_resource_type=by_resource_type,
                by_result=by_result,
                period_from=params.created_from,
                period_to=params.created_to,
            )

        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="get_summary",
                service="audit",
                message="Не удалось сформировать сводку аудита.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation="get_summary",
                message="Не удалось сформировать сводку аудита.",
            ) from exc

    async def export_logs(self, request: AuditExportRequest) -> AuditExportPayload:
        """Экспортирует события аудита в JSON или CSV.

        Args:
            request: Параметры экспорта, включая фильтры, формат, лимит и
                необходимость включать metadata.

        Returns:
            Словарь с форматом, именем файла, MIME-типом, количеством строк и
            строковым содержимым экспорта.

        Raises:
            ValidationServiceError: Если указан неподдерживаемый формат экспорта.
            ServiceError: Если журнал аудита не удалось экспортировать.
        """

        try:
            params = self._export_request_to_query_params(request)
            logs = await self._load_filtered_logs(params=params, ignore_pagination=True)
            limit = request.limit or self._EXPORT_DEFAULT_LIMIT
            rows = [
                self._audit_log_to_export_row(
                    log, include_metadata=request.include_metadata
                )
                for log in logs[:limit]
            ]

            export_format = request.format.lower()
            if export_format == "json":
                content = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
                filename = "audit_logs.json"
                content_type = "application/json"
            elif export_format == "csv":
                content = self._rows_to_csv(rows)
                filename = "audit_logs.csv"
                content_type = "text/csv; charset=utf-8"
            else:
                raise ValidationServiceError(
                    "Неподдерживаемый формат экспорта аудита.",
                    field="format",
                    value=request.format,
                    reason="unsupported_format",
                    details={"supported_formats": ["json", "csv"]},
                )

            return {
                "format": export_format,
                "filename": filename,
                "content_type": content_type,
                "count": len(rows),
                "content": content,
            }

        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="export_logs",
                service="audit",
                message="Не удалось экспортировать журнал аудита.",
            ) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation="export_logs",
                message="Не удалось экспортировать журнал аудита.",
            ) from exc

    async def get_latest_user_logs(
        self, user_id: UUID, *, limit: int = 20
    ) -> list[AuditLogListItem]:
        """Возвращает последние события аудита для одного пользователя.

        Args:
            user_id: Идентификатор пользователя.
            limit: Максимальное количество событий. Значение должно быть от 1
                до 100 включительно.

        Returns:
            Список последних событий пользователя.

        Raises:
            ValidationServiceError: Если `limit` находится вне допустимого
                диапазона.
            ServiceError: Если события не удалось получить.
        """

        self._validate_limit(limit, max_limit=100)
        items: list[AuditLogListItem] | None = None
        try:
            async with self.uow_factory() as uow:
                logs = await uow.audit.get_latest_user_logs(user_id, limit=limit)
                snapshots = [_audit_log_snapshot(log) for log in logs]
                items = [
                    AuditLogListItem.model_validate(snapshot) for snapshot in snapshots
                ]

            if items is None:
                raise ServiceError(
                    "Не удалось получить последние события пользователя.",
                    service="audit",
                    operation="get_latest_user_logs",
                )
            return items
        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="get_latest_user_logs",
                service="audit",
                message="Не удалось получить последние события пользователя.",
            ) from exc
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation="get_latest_user_logs",
                message="Не удалось получить последние события пользователя.",
            ) from exc

    async def cleanup_before(
        self,
        *,
        created_before: datetime,
        action: AuditAction | None = None,
        entity_type: str | None = None,
        system_only: bool | None = None,
    ) -> int:
        """Удаляет события аудита, созданные раньше указанной даты.

        Args:
            created_before: Верхняя граница даты создания. События старше этого
                значения подлежат удалению.
            action: Опциональный фильтр по действию.
            entity_type: Опциональный фильтр по типу сущности.
            system_only: Если задано, ограничивает удаление системными или
                пользовательскими событиями согласно значению фильтра.

        Returns:
            Количество удалённых событий аудита.

        Raises:
            ServiceError: Если очистку журнала аудита не удалось выполнить.
        """

        deleted_count: int | None = None
        try:
            async with self.uow_factory() as uow:
                deleted_count = await uow.audit.delete_logs_before(
                    created_before=created_before,
                    action=action,
                    entity_type=entity_type,
                    system_only=system_only,
                    flush=True,
                )
                await uow.commit()

            if deleted_count is None:
                raise ServiceError(
                    "Не удалось получить количество удалённых событий аудита.",
                    service="audit",
                    operation="cleanup_before",
                )
            return deleted_count
        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                operation="cleanup_before",
                service="audit",
                message="Не удалось очистить журнал аудита.",
            ) from exc
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation="cleanup_before",
                message="Не удалось очистить журнал аудита.",
            ) from exc

    async def _load_filtered_logs(
        self, *, params: AuditQueryParams, ignore_pagination: bool = False
    ) -> list[AuditLog]:
        """Загружает события аудита и применяет сервисные фильтры.

        Репозиторий поддерживает только часть полей сортировки и фильтрации.
        Оставшиеся условия применяются на уровне сервиса после загрузки
        ограниченного набора записей.

        Args:
            params: Параметры фильтрации, сортировки и пагинации.
            ignore_pagination: Если `True`, возвращает все отфильтрованные
                записи без применения `offset` и `limit`.

        Returns:
            Список ORM-моделей `AuditLog`, соответствующих фильтрам.
        """

        sort_by = self._normalize_sort_by(params.sort_by)
        sort_direction = "desc" if params.sort_desc else "asc"
        repository_sort_by = (
            sort_by if sort_by in self._REPOSITORY_SORT_FIELDS else "created_at"
        )
        repository_sort_direction = (
            sort_direction if sort_by in self._REPOSITORY_SORT_FIELDS else "desc"
        )

        logs: list[AuditLog] = []

        async with self.uow_factory() as uow:
            logs = await uow.audit.list_logs(
                offset=0,
                limit=self._SCAN_LIMIT,
                user_id=params.user_id,
                action=params.action,
                entity_type=params.entity_type,
                entity_id=params.entity_id,
                ip_address=params.ip_address,
                created_from=params.created_from,
                created_to=params.created_to,
                sort_by=cast(AuditSortField, repository_sort_by),
                sort_direction=repository_sort_direction,
            )
            # Отсоединяем экземпляры перед откатом сессии, чтобы их загруженные
            # значения столбцов оставались доступными после закрытия сессии.
            uow.session.expunge_all()

        filtered_logs = [log for log in logs if self._matches_params(log, params)]

        if (
            sort_by not in self._REPOSITORY_SORT_FIELDS
            or repository_sort_direction != sort_direction
        ):
            filtered_logs = self._sort_logs(
                filtered_logs, sort_by=sort_by, sort_desc=params.sort_desc
            )

        if ignore_pagination:
            return list(filtered_logs)

        return filtered_logs[params.offset : params.offset + params.limit]

    def _matches_params(self, audit_log: AuditLog, params: AuditQueryParams) -> bool:
        """Проверяет, соответствует ли событие сервисным фильтрам запроса.

        Args:
            audit_log: Событие аудита для проверки.
            params: Параметры фильтрации.

        Returns:
            `True`, если событие соответствует всем сервисным фильтрам.
        """

        if params.result is not None and audit_log.result != params.result:
            return False
        if (
            params.resource_type is not None
            and audit_log.resource_type != params.resource_type
        ):
            return False
        if params.request_id is not None and audit_log.request_id != params.request_id:
            return False
        if (
            params.correlation_id is not None
            and audit_log.correlation_id != params.correlation_id
        ):
            return False
        if params.query is not None and not self._matches_query(
            audit_log, params.query
        ):
            return False
        return True

    def _matches_query(self, audit_log: AuditLog, query: str) -> bool:
        """Проверяет, содержит ли событие аудита поисковую строку.

        Поиск выполняется без учёта регистра по основным текстовым и enum-полям
        события аудита.

        Args:
            audit_log: Событие аудита для проверки.
            query: Поисковая строка.

        Returns:
            `True`, если строка найдена хотя бы в одном проверяемом поле.
            Пустая строка считается совпадением.
        """

        normalized_query = query.strip().lower()
        if not normalized_query:
            return True

        values: Iterable[Any] = (
            audit_log.action.value,
            audit_log.result.value,
            audit_log.entity_type,
            audit_log.resource_type.value if audit_log.resource_type else None,
            audit_log.request_id,
            audit_log.correlation_id,
            audit_log.ip_address,
            audit_log.user_agent,
            audit_log.message,
            audit_log.error_code,
        )
        return any(
            normalized_query in str(value).lower()
            for value in values
            if value is not None
        )

    def _sort_logs(
        self, logs: list[AuditLog], *, sort_by: str, sort_desc: bool
    ) -> list[AuditLog]:
        """Сортирует события аудита на уровне сервиса.

        Args:
            logs: Список событий аудита.
            sort_by: Имя поля для сортировки.
            sort_desc: Если `True`, сортировка выполняется по убыванию.

        Returns:
            Новый отсортированный список событий аудита.
        """

        def sort_key(audit_log: AuditLog) -> tuple[bool, Any]:
            """Возвращает ключ сортировки для события аудита.

            Args:
                audit_log: Событие аудита.

            Returns:
                Кортеж, где первый элемент показывает, является ли значение
                `None`, а второй содержит нормализованное значение поля.
            """

            value = getattr(audit_log, sort_by, None)
            if isinstance(value, Enum):
                value = value.value
            if isinstance(value, UUID):
                value = str(value)
            return value is None, value

        return sorted(logs, key=sort_key, reverse=sort_desc)

    def _export_request_to_query_params(
        self, request: AuditExportRequest
    ) -> AuditQueryParams:
        """Преобразует параметры экспорта в параметры запроса журнала аудита.

        Args:
            request: Параметры экспорта журнала аудита.

        Returns:
            Параметры запроса аудита с фильтрами из экспорта и стандартной
            сортировкой по дате создания.
        """

        return AuditQueryParams(
            user_id=request.user_id,
            action=request.action,
            result=request.result,
            resource_type=request.resource_type,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            created_from=request.created_from,
            created_to=request.created_to,
            limit=100,
            offset=0,
            sort_by="created_at",
            sort_desc=True,
        )

    def _audit_log_to_export_row(
        self, audit_log: AuditLog, *, include_metadata: bool
    ) -> dict[str, Any]:
        """Преобразует событие аудита в строку экспорта.

        Args:
            audit_log: Событие аудита.
            include_metadata: Нужно ли включать поле metadata в экспорт.

        Returns:
            Словарь с JSON-сериализуемыми значениями события аудита.
        """

        row: dict[str, Any] = {
            "id": str(audit_log.id),
            "user_id": str(audit_log.user_id) if audit_log.user_id else None,
            "action": audit_log.action.value,
            "result": audit_log.result.value,
            "entity_type": audit_log.entity_type,
            "entity_id": str(audit_log.entity_id) if audit_log.entity_id else None,
            "resource_type": audit_log.resource_type.value
            if audit_log.resource_type
            else None,
            "request_id": audit_log.request_id,
            "correlation_id": audit_log.correlation_id,
            "ip_address": str(audit_log.ip_address) if audit_log.ip_address else None,
            "user_agent": audit_log.user_agent,
            "message": audit_log.message,
            "error_code": audit_log.error_code,
            "created_at": audit_log.created_at.isoformat(),
        }
        if include_metadata:
            row["metadata"] = audit_log.metadata_ or {}
        return row

    def _rows_to_csv(self, rows: list[dict[str, Any]]) -> str:
        """Преобразует строки экспорта в CSV.

        Сложные значения, такие как словари и списки, сериализуются в JSON
        перед записью в CSV.

        Args:
            rows: Список строк экспорта.

        Returns:
            CSV-содержимое в виде строки. Если строк нет, возвращается пустая
            строка.
        """

        if not rows:
            return ""

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, dict | list)
                    else value
                    for key, value in row.items()
                }
            )
        return output.getvalue()

    def _normalize_metadata(
        self, metadata: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        """Нормализует metadata события аудита.

        Ключи приводятся к строкам, а значения — к JSON-сериализуемому виду.

        Args:
            metadata: Исходные metadata или `None`.

        Returns:
            Нормализованный словарь metadata или `None`.
        """

        if metadata is None:
            return None
        return {str(key): self._jsonable(value) for key, value in metadata.items()}

    @staticmethod
    def _jsonable(value: Any) -> Any:
        """Преобразует значение в JSON-сериализуемый формат.

        Args:
            value: Значение для преобразования.

        Returns:
            JSON-сериализуемое представление значения.
        """

        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {
                str(key): AuditService._jsonable(item) for key, item in value.items()
            }
        if isinstance(value, tuple | list | set | frozenset):
            return [AuditService._jsonable(item) for item in value]
        if hasattr(value, "model_dump"):
            return AuditService._jsonable(value.model_dump())
        return str(value)

    @staticmethod
    def _normalize_optional_string(value: str | None) -> str | None:
        """Нормализует опциональную строку.

        Args:
            value: Исходная строка или `None`.

        Returns:
            Обрезанная строка без пробелов по краям или `None`, если значение
            отсутствует либо после нормализации стало пустым.
        """

        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _normalize_sort_by(self, value: str) -> str:
        """Нормализует поле сортировки журнала аудита.

        Args:
            value: Запрошенное поле сортировки.

        Returns:
            Допустимое поле сортировки. Если поле не поддерживается сервисом,
            возвращается `"created_at"`.
        """

        normalized = value.strip()
        if normalized not in self._SERVICE_SORT_FIELDS:
            return "created_at"
        return normalized

    @staticmethod
    def _validate_limit(limit: int, *, max_limit: int) -> None:
        """Проверяет лимит выборки.

        Args:
            limit: Проверяемое значение лимита.
            max_limit: Максимально допустимый лимит.

        Raises:
            ValidationServiceError: Если `limit` меньше 1 или больше
                `max_limit`.
        """

        if limit < 1 or limit > max_limit:
            raise ValidationServiceError(
                "Некорректное значение limit.",
                field="limit",
                value=limit,
                reason="invalid_limit",
                details={"min_limit": 1, "max_limit": max_limit},
            )

    @staticmethod
    def _unexpected_error(
        exc: BaseException, *, operation: str, message: str
    ) -> ServiceError:
        """Логирует непредвиденную ошибку и преобразует её в `ServiceError`.

        Args:
            exc: Исходное исключение.
            operation: Название операции сервиса, во время которой произошла
                ошибка.
            message: Сообщение для логирования и итоговой сервисной ошибки.

        Returns:
            Сервисная ошибка, созданная из исходного исключения.
        """

        logger.exception(
            message,
            extra={"operation": operation, "error_type": exc.__class__.__name__},
        )
        return service_error_from_exception(
            exc, operation=operation, service="audit", message=message
        )


def get_audit_service(*, uow_factory: UnitOfWorkFactory | None = None) -> AuditService:
    """Создаёт экземпляр сервиса аудита.

    Args:
        uow_factory: Фабрика UnitOfWork. Если не передана, сервис создаст
            стандартную фабрику самостоятельно.

    Returns:
        Экземпляр `AuditService`.
    """

    return AuditService(uow_factory=uow_factory)


def _audit_log_snapshot(audit_log: AuditLog) -> dict[str, Any]:
    """Создаёт снимок ORM-модели события аудита для валидации DTO.

    Args:
        audit_log: ORM-модель события аудита.

    Returns:
        Словарь с полями события аудита в формате, подходящем для
        `AuditLogRead` и `AuditLogListItem`.
    """

    return {
        "id": audit_log.id,
        "user_id": audit_log.user_id,
        "action": audit_log.action,
        "result": audit_log.result,
        "entity_type": audit_log.entity_type,
        "entity_id": audit_log.entity_id,
        "resource_type": audit_log.resource_type,
        "request_id": audit_log.request_id,
        "correlation_id": audit_log.correlation_id,
        "ip_address": str(audit_log.ip_address) if audit_log.ip_address else None,
        "user_agent": audit_log.user_agent,
        "message": audit_log.message,
        "error_code": audit_log.error_code,
        "metadata_": audit_log.metadata_,
        "created_at": audit_log.created_at,
    }

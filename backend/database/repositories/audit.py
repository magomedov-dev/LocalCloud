from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, String, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import EntityNotFoundError, InvalidQueryError
from database.models.audit import AuditLog
from database.models.enums import AuditAction, AuditResourceType, AuditResult
from database.repositories.base import BaseRepository

AuditSortField = Literal[
    "created_at",
    "action",
    "entity_type",
    "ip_address",
]

SortDirection = Literal["asc", "desc"]


class AuditLogRepository(BaseRepository[AuditLog]):
    """Репозиторий для работы с журналом аудита.

    Инкапсулирует операции создания, чтения, поиска, подсчёта и очистки
    записей аудита. Используется для фиксации пользовательских, системных
    и связанных с конкретными сущностями действий.

    Репозиторий работает поверх асинхронной SQLAlchemy-сессии и наследует
    базовые CRUD-операции от BaseRepository.

    Важно:
        Репозиторий не выполняет commit самостоятельно. Это позволяет
        записывать события аудита в рамках той же транзакции, что и основная
        бизнес-операция.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Инициализирует репозиторий журнала аудита.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
        """

        super().__init__(session=session, model=AuditLog)

    # Повышенный лимит для внутренних сканов сервиса аудита.
    MAX_LIMIT = 100_000

    # ------------------------------------------------------------------
    # Получение по идентификатору
    # ------------------------------------------------------------------

    async def get_log_by_id(
        self,
        log_id: uuid.UUID,
    ) -> AuditLog | None:
        """Возвращает событие аудита по его идентификатору.

        Args:
            log_id: UUID события аудита.

        Returns:
            Объект AuditLog, если запись найдена, иначе None.
        """

        return await self.get_by_id(log_id)

    async def get_required_log_by_id(
        self,
        log_id: uuid.UUID,
    ) -> AuditLog:
        """Возвращает событие аудита по идентификатору.

        В отличие от get_log_by_id, гарантирует наличие результата и выбрасывает
        исключение, если запись не найдена.

        Args:
            log_id: UUID события аудита.

        Returns:
            Найденный объект AuditLog.

        Raises:
            EntityNotFoundError: Если событие аудита с указанным id не найдено.
        """

        return await self.get_required_by_id(log_id)

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> AuditLog | None:
        """Возвращает событие аудита по идентификатору.

        Переопределяет базовый метод для сохранения типизации и семантики
        репозитория AuditLog.

        Args:
            entity_id: UUID события аудита.

        Returns:
            Объект AuditLog, если запись найдена, иначе None.
        """

        return await super().get_by_id(entity_id)

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> AuditLog:
        """Возвращает событие аудита по идентификатору или выбрасывает исключение.

        Args:
            entity_id: UUID события аудита.

        Returns:
            Найденный объект AuditLog.

        Raises:
            EntityNotFoundError: Если событие аудита не найдено.
        """

        audit_log = await super().get_by_id(entity_id)

        if audit_log is None:
            raise EntityNotFoundError(
                "AuditLog",
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return audit_log

    # ------------------------------------------------------------------
    # Создание событий аудита
    # ------------------------------------------------------------------

    async def create_event(
        self,
        *,
        action: AuditAction,
        result: AuditResult = AuditResult.SUCCESS,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        resource_type: AuditResourceType | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        message: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> AuditLog:
        """Создаёт и сохраняет событие аудита.

        Метод нормализует входные строковые поля, выбирает подходящий фабричный
        метод модели AuditLog в зависимости от результата события и наличия
        пользователя, после чего добавляет событие в текущую сессию.

        Args:
            action: Тип действия аудита.
            result: Результат выполнения действия.
            user_id: UUID пользователя, связанного с событием. Если None,
                событие считается системным.
            entity_type: Тип сущности, связанной с событием.
            entity_id: UUID сущности, связанной с событием.
            resource_type: Тип ресурса, связанного с событием.
            request_id: Идентификатор запроса.
            correlation_id: Идентификатор корреляции для связывания событий.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            message: Человекочитаемое описание события.
            error_code: Код ошибки, если событие связано с ошибкой.
            metadata: Дополнительные структурированные данные события.
            flush: Если True, выполняет flush после добавления события.
            refresh: Если True, обновляет событие из базы после flush.

        Returns:
            Созданный объект AuditLog.

        Raises:
            InvalidQueryError: Если одно из нормализуемых строковых полей
                превышает допустимую длину.
            RepositoryError: При ошибке работы с базой данных.
        """

        common_kwargs: dict[str, Any] = {
            "action": action,
            "entity_type": self._normalize_entity_type(entity_type),
            "entity_id": entity_id,
            "resource_type": resource_type,
            "request_id": self._normalize_identifier(
                request_id,
                field_name="request_id",
            ),
            "correlation_id": self._normalize_identifier(
                correlation_id,
                field_name="correlation_id",
            ),
            "message": message,
            "error_code": self._normalize_identifier(
                error_code,
                field_name="error_code",
            ),
            "metadata": metadata,
        }

        if result == AuditResult.FAILURE:
            audit_log = AuditLog.create_failure_event(
                user_id=user_id,
                ip_address=self._normalize_ip_address(ip_address),
                user_agent=self._normalize_user_agent(user_agent),
                **common_kwargs,
            )
        elif result == AuditResult.DENIED:
            audit_log = AuditLog.create_denied_event(
                action=action,
                user_id=user_id,
                entity_type=common_kwargs["entity_type"],
                entity_id=entity_id,
                resource_type=resource_type,
                ip_address=self._normalize_ip_address(ip_address),
                user_agent=self._normalize_user_agent(user_agent),
                request_id=common_kwargs["request_id"],
                correlation_id=common_kwargs["correlation_id"],
                message=message,
                metadata=metadata,
            )
        elif user_id is not None:
            audit_log = AuditLog.create_user_event(
                user_id=user_id,
                result=result,
                ip_address=self._normalize_ip_address(ip_address),
                user_agent=self._normalize_user_agent(user_agent),
                **common_kwargs,
            )
        else:
            audit_log = AuditLog.create_system_event(
                result=result,
                **common_kwargs,
            )

        return await self.create(audit_log, flush=flush, refresh=refresh)

    async def create_log(
        self,
        *,
        action: AuditAction,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> AuditLog:
        """Создаёт универсальное событие аудита.

        Метод нормализует строковые поля, создаёт объект AuditLog и добавляет его
        в текущую сессию. Может использоваться как для пользовательских, так и для
        системных событий.

        Args:
            action: Тип действия аудита.
            user_id: UUID пользователя, выполнившего действие. None означает
                системное событие.
            entity_type: Тип сущности, связанной с событием.
            entity_id: UUID сущности, связанной с событием.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            metadata: Дополнительные структурированные данные события.
            flush: Если True, выполняет flush после добавления объекта.
            refresh: Если True, обновляет объект из базы после flush.

        Returns:
            Созданный объект AuditLog.

        Raises:
            InvalidQueryError: Если entity_type или ip_address превышают
                допустимую длину.
            RepositoryError: При ошибках работы с базой данных.
        """

        return await self.create_event(
            action=action,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            flush=flush,
            refresh=refresh,
        )

    async def create_user_log(
        self,
        *,
        user_id: uuid.UUID,
        action: AuditAction,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> AuditLog:
        """Создаёт событие аудита от имени пользователя.

        Используется для логирования действий, явно связанных с конкретным
        пользователем.

        Args:
            user_id: UUID пользователя, выполнившего действие.
            action: Тип действия аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            metadata: Дополнительные данные события.
            flush: Если True, выполняет flush после добавления.
            refresh: Если True, обновляет объект из базы после flush.

        Returns:
            Созданный объект AuditLog.
        """

        return await self.create_log(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            flush=flush,
            refresh=refresh,
        )

    async def create_system_log(
        self,
        *,
        action: AuditAction,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> AuditLog:
        """Создаёт системное событие аудита.

        Системное событие не связано с пользователем: поле user_id сохраняется
        как None. Метод подходит для фоновых задач, автоматических процессов,
        технических операций и административных действий системы.

        Args:
            action: Тип действия аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            metadata: Дополнительные данные события.
            flush: Если True, выполняет flush после добавления.
            refresh: Если True, обновляет объект из базы после flush.

        Returns:
            Созданный объект AuditLog.
        """

        return await self.create_log(
            user_id=None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=None,
            user_agent=None,
            metadata=metadata,
            flush=flush,
            refresh=refresh,
        )

    async def create_entity_log(
        self,
        *,
        action: AuditAction,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
        flush: bool = True,
        refresh: bool = False,
    ) -> AuditLog:
        """Создаёт событие аудита, связанное с конкретной сущностью.

        Используется, когда действие относится к определённому объекту системы:
        пользователю, заказу, документу, роли, настройке и т.д.

        Args:
            action: Тип действия аудита.
            entity_type: Тип сущности.
            entity_id: UUID сущности.
            user_id: UUID пользователя, выполнившего действие. None означает
                системное событие.
            ip_address: IP-адрес клиента.
            user_agent: User-Agent клиента.
            metadata: Дополнительные данные события.
            flush: Если True, выполняет flush после добавления.
            refresh: Если True, обновляет объект из базы после flush.

        Returns:
            Созданный объект AuditLog.
        """

        return await self.create_log(
            action=action,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
            flush=flush,
            refresh=refresh,
        )

    # ------------------------------------------------------------------
    # Получение списков событий
    # ------------------------------------------------------------------

    async def list_logs(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        user_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        system_only: bool | None = None,
        metadata_contains: dict[str, Any] | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает список событий аудита с фильтрацией, сортировкой и пагинацией.

        Поддерживает фильтрацию по пользователю, действию, набору действий,
        сущности, IP-адресу, периоду создания, системным событиям и содержимому
        metadata.

        Args:
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей в результате.
            user_id: UUID пользователя.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            ip_address: IP-адрес клиента.
            created_from: Нижняя граница периода создания.
            created_to: Верхняя граница периода создания.
            system_only: Если True — только системные события, если False —
                только пользовательские, если None — все события.
            metadata_contains: JSON-фрагмент, который должен содержаться
                в metadata.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: asc или desc.

        Returns:
            Список объектов AuditLog.

        Raises:
            InvalidQueryError: При некорректной пагинации, периоде, действиях
                или параметрах сортировки.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions = self._build_conditions(
            user_id=user_id,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            created_from=created_from,
            created_to=created_to,
            system_only=system_only,
            metadata_contains=metadata_contains,
        )

        statement = select(AuditLog)

        if conditions:
            statement = statement.where(*conditions)

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(statement, operation="list_logs")

    async def list_user_logs(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает события аудита конкретного пользователя.

        Args:
            user_id: UUID пользователя.
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список событий аудита пользователя.
        """

        return await self.list_logs(
            offset=offset,
            limit=limit,
            user_id=user_id,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            created_from=created_from,
            created_to=created_to,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_system_logs(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает системные события аудита.

        Системными считаются события, у которых user_id равен None.

        Args:
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список системных событий аудита.
        """

        return await self.list_logs(
            offset=offset,
            limit=limit,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            created_from=created_from,
            created_to=created_to,
            system_only=True,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_entity_logs(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает события аудита, связанные с конкретной сущностью.

        Args:
            entity_type: Тип сущности.
            entity_id: UUID сущности.
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список событий аудита по указанной сущности.
        """

        return await self.list_logs(
            offset=offset,
            limit=limit,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            created_from=created_from,
            created_to=created_to,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_by_action(
        self,
        action: AuditAction,
        *,
        offset: int = 0,
        limit: int = 100,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает события аудита с указанным действием.

        Args:
            action: Действие аудита.
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            user_id: UUID пользователя.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список событий аудита с указанным действием.
        """

        return await self.list_logs(
            offset=offset,
            limit=limit,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            created_from=created_from,
            created_to=created_to,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_by_actions(
        self,
        actions: Sequence[AuditAction],
        *,
        offset: int = 0,
        limit: int = 100,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает события аудита по набору действий.

        Args:
            actions: Последовательность действий аудита.
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            user_id: UUID пользователя.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список событий аудита, действие которых входит в actions.

        Raises:
            InvalidQueryError: Если actions передан как пустая последовательность.
        """

        return await self.list_logs(
            offset=offset,
            limit=limit,
            user_id=user_id,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            created_from=created_from,
            created_to=created_to,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def list_by_period(
        self,
        *,
        created_from: datetime,
        created_to: datetime,
        offset: int = 0,
        limit: int = 100,
        user_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Возвращает события аудита за указанный период.

        Args:
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            user_id: UUID пользователя.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список событий аудита за период.

        Raises:
            InvalidQueryError: Если created_from больше created_to.
        """

        return await self.list_logs(
            offset=offset,
            limit=limit,
            user_id=user_id,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            created_from=created_from,
            created_to=created_to,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    async def get_latest_user_logs(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 20,
    ) -> list[AuditLog]:
        """Возвращает последние события аудита пользователя.

        События сортируются по created_at в порядке убывания.

        Args:
            user_id: UUID пользователя.
            limit: Максимальное количество событий.

        Returns:
            Список последних событий аудита пользователя.
        """

        return await self.list_user_logs(
            user_id,
            offset=0,
            limit=limit,
            sort_by="created_at",
            sort_direction="desc",
        )

    async def get_latest_entity_logs(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        limit: int = 20,
    ) -> list[AuditLog]:
        """Возвращает последние события аудита по конкретной сущности.

        События сортируются по created_at в порядке убывания.

        Args:
            entity_type: Тип сущности.
            entity_id: UUID сущности.
            limit: Максимальное количество событий.

        Returns:
            Список последних событий аудита по сущности.
        """

        return await self.list_entity_logs(
            entity_type=entity_type,
            entity_id=entity_id,
            offset=0,
            limit=limit,
            sort_by="created_at",
            sort_direction="desc",
        )

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------

    async def search_logs(
        self,
        *,
        query: str | None = None,
        offset: int = 0,
        limit: int = 100,
        user_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        system_only: bool | None = None,
        metadata_contains: dict[str, Any] | None = None,
        sort_by: AuditSortField = "created_at",
        sort_direction: SortDirection = "desc",
    ) -> list[AuditLog]:
        """Выполняет поиск событий аудита.

        Помимо стандартных фильтров, поддерживает текстовый поиск по полям
        action, entity_type, ip_address и user_agent. Поиск выполняется через
        нечувствительное к регистру совпадение ilike.

        Args:
            query: Поисковая строка.
            offset: Количество записей, которое нужно пропустить.
            limit: Максимальное количество записей.
            user_id: UUID пользователя.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            ip_address: IP-адрес клиента.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            system_only: Фильтр системных или пользовательских событий.
            metadata_contains: JSON-фрагмент, который должен содержаться
                в metadata.
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки.

        Returns:
            Список найденных событий аудита.
        """

        self._validate_pagination(offset=offset, limit=limit)

        conditions = self._build_conditions(
            user_id=user_id,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            created_from=created_from,
            created_to=created_to,
            system_only=system_only,
            metadata_contains=metadata_contains,
        )

        normalized_query = self._normalize_search_query(query)

        if normalized_query is not None:
            pattern = f"%{normalized_query}%"

            conditions.append(
                or_(
                    cast(AuditLog.action, String).ilike(pattern),
                    AuditLog.entity_type.ilike(pattern),
                    AuditLog.ip_address.ilike(pattern),
                    AuditLog.user_agent.ilike(pattern),
                )
            )

        statement = select(AuditLog)

        if conditions:
            statement = statement.where(*conditions)

        statement = (
            statement.order_by(self._get_order_by(sort_by, sort_direction))
            .offset(offset)
            .limit(limit)
        )

        return await self.scalars_all(statement, operation="search_logs")

    # ------------------------------------------------------------------
    # Подсчёт и статистика
    # ------------------------------------------------------------------

    async def count_logs(
        self,
        *,
        user_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        system_only: bool | None = None,
        metadata_contains: dict[str, Any] | None = None,
        query: str | None = None,
    ) -> int:
        """Возвращает количество событий аудита с учётом фильтров.

        Поддерживает те же основные фильтры, что и list_logs, а также текстовый
        поиск по action, entity_type, ip_address и user_agent.

        Args:
            user_id: UUID пользователя.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            ip_address: IP-адрес клиента.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            system_only: Фильтр системных или пользовательских событий.
            metadata_contains: JSON-фрагмент, который должен содержаться
                в metadata.
            query: Поисковая строка.

        Returns:
            Количество событий аудита.

        Raises:
            RepositoryError: При ошибке выполнения SQL-запроса.
        """

        conditions = self._build_conditions(
            user_id=user_id,
            action=action,
            actions=actions,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            created_from=created_from,
            created_to=created_to,
            system_only=system_only,
            metadata_contains=metadata_contains,
        )

        normalized_query = self._normalize_search_query(query)

        if normalized_query is not None:
            pattern = f"%{normalized_query}%"

            conditions.append(
                or_(
                    cast(AuditLog.action, String).ilike(pattern),
                    AuditLog.entity_type.ilike(pattern),
                    AuditLog.ip_address.ilike(pattern),
                    AuditLog.user_agent.ilike(pattern),
                )
            )

        try:
            statement = select(func.count()).select_from(AuditLog)

            if conditions:
                statement = statement.where(*conditions)

            result = await self.session.execute(statement)

            return int(result.scalar_one())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count_logs",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def count_user_logs(
        self,
        user_id: uuid.UUID,
    ) -> int:
        """Возвращает количество событий аудита пользователя.

        Args:
            user_id: UUID пользователя.

        Returns:
            Количество событий аудита указанного пользователя.
        """

        return await self.count_logs(user_id=user_id)

    async def count_entity_logs(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
    ) -> int:
        """Возвращает количество событий аудита по конкретной сущности.

        Args:
            entity_type: Тип сущности.
            entity_id: UUID сущности.

        Returns:
            Количество событий аудита, связанных с указанной сущностью.
        """

        return await self.count_logs(
            entity_type=entity_type,
            entity_id=entity_id,
        )

    async def count_system_logs(self) -> int:
        """Возвращает количество системных событий аудита.

        Returns:
            Количество событий, у которых user_id равен None.
        """

        return await self.count_logs(system_only=True)

    async def count_by_action(
        self,
        action: AuditAction,
    ) -> int:
        """Возвращает количество событий аудита с указанным действием.

        Args:
            action: Действие аудита.

        Returns:
            Количество событий с указанным действием.
        """

        return await self.count_logs(action=action)

    async def get_action_counts(
        self,
        *,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> dict[AuditAction, int]:
        """Возвращает статистику количества событий по действиям.

        Args:
            user_id: UUID пользователя для ограничения выборки.
            entity_type: Тип сущности для ограничения выборки.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.

        Returns:
            Словарь, где ключ — действие аудита, значение — количество событий.
        """

        conditions = self._build_conditions(
            user_id=user_id,
            entity_type=entity_type,
            created_from=created_from,
            created_to=created_to,
        )

        try:
            statement = select(AuditLog.action, func.count(AuditLog.id)).group_by(
                AuditLog.action
            )

            if conditions:
                statement = statement.where(*conditions)

            result = await self.session.execute(statement)

            return {action: int(count) for action, count in result.all()}

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_action_counts",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def get_entity_type_counts(
        self,
        *,
        user_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> dict[str, int]:
        """Возвращает статистику количества событий по типам сущностей.

        Учитываются только события, у которых entity_type не равен None.

        Args:
            user_id: UUID пользователя для ограничения выборки.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.

        Returns:
            Словарь, где ключ — тип сущности, значение — количество событий.
        """

        conditions = self._build_conditions(
            user_id=user_id,
            created_from=created_from,
            created_to=created_to,
        )

        conditions.append(AuditLog.entity_type.is_not(None))

        try:
            statement = (
                select(AuditLog.entity_type, func.count(AuditLog.id))
                .where(*conditions)
                .group_by(AuditLog.entity_type)
            )

            result = await self.session.execute(statement)

            return {
                str(entity_type): int(count)
                for entity_type, count in result.all()
                if entity_type is not None
            }

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_entity_type_counts",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def get_user_activity_counts(
        self,
        *,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 100,
    ) -> dict[uuid.UUID, int]:
        """Возвращает статистику пользовательской активности.

        Подсчитывает количество событий для каждого пользователя, исключая
        системные события. Результат сортируется по убыванию количества событий.

        Args:
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            limit: Максимальное количество пользователей в результате.

        Returns:
            Словарь, где ключ — UUID пользователя, значение — количество событий.
        """

        self._validate_pagination(offset=0, limit=limit)

        conditions = self._build_conditions(
            created_from=created_from,
            created_to=created_to,
            system_only=False,
        )

        try:
            statement = (
                select(AuditLog.user_id, func.count(AuditLog.id).label("events_count"))
                .where(*conditions)
                .group_by(AuditLog.user_id)
                .order_by(func.count(AuditLog.id).desc())
                .limit(limit)
            )

            result = await self.session.execute(statement)

            return {
                user_id: int(count)
                for user_id, count in result.all()
                if user_id is not None
            }

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_user_activity_counts",
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Очистка журнала аудита
    # ------------------------------------------------------------------

    async def delete_logs_before(
        self,
        *,
        created_before: datetime,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        system_only: bool | None = None,
        flush: bool = True,
    ) -> int:
        """Физически удаляет события аудита старше указанной даты.

        Метод предназначен для административной очистки журнала аудита, например
        фоновой задачей retention policy. Удаление является физическим, поэтому
        восстановление записей средствами репозитория невозможно.

        Args:
            created_before: Верхняя граница даты создания удаляемых событий.
            action: Одно действие аудита для ограничения удаления.
            actions: Набор действий аудита для ограничения удаления.
            entity_type: Тип сущности для ограничения удаления.
            system_only: Если True — удалить только системные события, если False —
                только пользовательские, если None — оба типа.
            flush: Если True, выполняет flush после удаления.

        Returns:
            Количество удалённых записей.

        Raises:
            InvalidQueryError: При некорректных фильтрах.
            RepositoryError: При ошибке выполнения SQL-запроса.
        """

        conditions = self._build_conditions(
            action=action,
            actions=actions,
            entity_type=entity_type,
            created_to=created_before,
            system_only=system_only,
        )

        try:
            statement = delete(AuditLog).where(*conditions)
            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            rowcount = getattr(result, "rowcount", 0)
            return int(rowcount or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete_logs_before",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete_logs_before",
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Вспомогательные методы построения условий
    # ------------------------------------------------------------------

    def _build_conditions(
        self,
        *,
        user_id: uuid.UUID | None = None,
        action: AuditAction | None = None,
        actions: Sequence[AuditAction] | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        system_only: bool | None = None,
        metadata_contains: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Формирует список SQLAlchemy-условий для фильтрации событий аудита.

        Метод используется всеми операциями выборки, поиска, подсчёта и удаления,
        чтобы централизовать правила построения WHERE-условий.

        Args:
            user_id: UUID пользователя.
            action: Одно действие аудита.
            actions: Набор действий аудита.
            entity_type: Тип связанной сущности.
            entity_id: UUID связанной сущности.
            ip_address: IP-адрес клиента.
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.
            system_only: Фильтр системных или пользовательских событий.
            metadata_contains: JSON-фрагмент, который должен содержаться
                в metadata.

        Returns:
            Список SQLAlchemy-условий.

        Raises:
            InvalidQueryError: Если период, actions, entity_type или ip_address
                некорректны.
        """

        self._validate_period(
            created_from=created_from,
            created_to=created_to,
        )

        normalized_actions = self._normalize_actions(
            action=action,
            actions=actions,
        )

        conditions: list[Any] = []

        if user_id is not None:
            conditions.append(AuditLog.user_id == user_id)

        if system_only is True:
            conditions.append(AuditLog.user_id.is_(None))
        elif system_only is False:
            conditions.append(AuditLog.user_id.is_not(None))

        if normalized_actions:
            if len(normalized_actions) == 1:
                conditions.append(AuditLog.action == normalized_actions[0])
            else:
                conditions.append(AuditLog.action.in_(normalized_actions))

        if entity_type is not None:
            conditions.append(
                AuditLog.entity_type == self._normalize_entity_type(entity_type),
            )

        if entity_id is not None:
            conditions.append(AuditLog.entity_id == entity_id)

        if ip_address is not None:
            conditions.append(
                AuditLog.ip_address == self._normalize_ip_address(ip_address),
            )

        if created_from is not None:
            conditions.append(AuditLog.created_at >= created_from)

        if created_to is not None:
            conditions.append(AuditLog.created_at <= created_to)

        if metadata_contains is not None:
            conditions.append(AuditLog.metadata_.contains(metadata_contains))

        return conditions

    def _normalize_actions(
        self,
        *,
        action: AuditAction | None,
        actions: Sequence[AuditAction] | None,
    ) -> list[AuditAction]:
        """Нормализует фильтры действий аудита.

        Объединяет одиночное действие action и последовательность actions,
        удаляет дубликаты с сохранением порядка.

        Args:
            action: Одно действие аудита.
            actions: Последовательность действий аудита.

        Returns:
            Список уникальных действий аудита.

        Raises:
            InvalidQueryError: Если actions передан как пустая последовательность.
        """

        normalized: list[AuditAction] = []

        if action is not None:
            normalized.append(action)

        if actions is not None:
            if len(actions) == 0:
                raise InvalidQueryError(
                    "Список actions не должен быть пустым.",
                    repository=self.repository_name,
                    operation="_normalize_actions",
                    details={
                        "model": self.model_name,
                        "field": "actions",
                    },
                )

            normalized.extend(actions)

        unique_actions: list[AuditAction] = []

        for item in normalized:
            if item not in unique_actions:
                unique_actions.append(item)

        return unique_actions

    def _validate_period(
        self,
        *,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> None:
        """Проверяет корректность периода фильтрации.

        Args:
            created_from: Нижняя граница периода.
            created_to: Верхняя граница периода.

        Raises:
            InvalidQueryError: Если created_from больше created_to.
        """

        if (
            created_from is not None
            and created_to is not None
            and created_from > created_to
        ):
            raise InvalidQueryError(
                "Нижняя граница периода не может быть больше верхней.",
                repository=self.repository_name,
                operation="_validate_period",
                details={
                    "model": self.model_name,
                    "created_from": created_from.isoformat(),
                    "created_to": created_to.isoformat(),
                },
            )

    def _normalize_search_query(
        self,
        query: str | None,
    ) -> str | None:
        """Нормализует поисковую строку.

        Удаляет пробелы по краям строки. Пустую строку преобразует в None.

        Args:
            query: Исходная поисковая строка.

        Returns:
            Нормализованная строка поиска или None.
        """

        if query is None:
            return None

        normalized = query.strip()

        return normalized or None

    def _normalize_entity_type(
        self,
        entity_type: str | None,
    ) -> str | None:
        """Нормализует тип сущности.

        Удаляет пробелы по краям строки, пустое значение преобразует в None
        и проверяет максимальную длину.

        Args:
            entity_type: Исходный тип сущности.

        Returns:
            Нормализованный тип сущности или None.

        Raises:
            InvalidQueryError: Если длина entity_type превышает 128 символов.
        """

        if entity_type is None:
            return None

        normalized = entity_type.strip()

        if not normalized:
            return None

        if len(normalized) > 128:
            raise InvalidQueryError(
                "Тип сущности события аудита не должен превышать 128 символов.",
                repository=self.repository_name,
                operation="_normalize_entity_type",
                details={
                    "field": "entity_type",
                    "length": len(normalized),
                    "max_length": 128,
                },
            )

        return normalized

    def _normalize_ip_address(
        self,
        ip_address: str | None,
    ) -> str | None:
        """Нормализует IP-адрес.

        Удаляет пробелы по краям строки, пустое значение преобразует в None
        и проверяет максимальную длину.

        Args:
            ip_address: Исходный IP-адрес.

        Returns:
            Нормализованный IP-адрес или None.

        Raises:
            InvalidQueryError: Если длина ip_address превышает 64 символа.
        """

        if ip_address is None:
            return None

        normalized = ip_address.strip()

        if not normalized:
            return None

        if len(normalized) > 64:
            raise InvalidQueryError(
                "IP-адрес события аудита не должен превышать 64 символа.",
                repository=self.repository_name,
                operation="_normalize_ip_address",
                details={
                    "field": "ip_address",
                    "length": len(normalized),
                    "max_length": 64,
                },
            )

        return normalized

    def _normalize_user_agent(
        self,
        user_agent: str | None,
    ) -> str | None:
        """Нормализует User-Agent.

        Удаляет пробелы по краям строки. Пустую строку преобразует в None.

        Args:
            user_agent: Исходное значение User-Agent.

        Returns:
            Нормализованный User-Agent или None.
        """

        if user_agent is None:
            return None

        normalized = user_agent.strip()

        return normalized or None

    def _normalize_identifier(
        self,
        value: str | None,
        *,
        field_name: str,
        max_length: int = 128,
    ) -> str | None:
        """Нормализует короткий идентификатор события аудита.

        Удаляет пробелы по краям строки, пустое значение преобразует в None
        и проверяет максимальную длину значения. Используется для полей,
        которые хранятся в VARCHAR-колонках: request_id, correlation_id,
        error_code и аналогичных идентификаторов.

        Args:
            value: Исходное значение идентификатора.
            field_name: Название поля для диагностических данных ошибки.
            max_length: Максимально допустимая длина значения.

        Returns:
            Нормализованный идентификатор или None.

        Raises:
            InvalidQueryError: Если длина идентификатора превышает max_length.
        """

        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > max_length:
            raise InvalidQueryError(
                "Идентификатор события аудита превышает допустимую длину.",
                repository=self.repository_name,
                operation="_normalize_identifier",
                details={
                    "field": field_name,
                    "length": len(normalized),
                    "max_length": max_length,
                },
            )
        return normalized

    def _get_order_by(
        self,
        sort_by: AuditSortField,
        sort_direction: SortDirection,
    ) -> Any:
        """Возвращает SQLAlchemy-выражение сортировки.

        Поддерживает сортировку только по заранее разрешённым полям журнала
        аудита. Для NULL-значений используется nullslast.

        Args:
            sort_by: Поле сортировки.
            sort_direction: Направление сортировки: asc или desc.

        Returns:
            SQLAlchemy-выражение order_by.

        Raises:
            InvalidQueryError: Если поле или направление сортировки недопустимы.
        """

        allowed_fields: dict[str, Any] = {
            "created_at": AuditLog.created_at,
            "action": AuditLog.action,
            "entity_type": AuditLog.entity_type,
            "ip_address": AuditLog.ip_address,
        }

        if sort_by not in allowed_fields:
            raise InvalidQueryError(
                "Недопустимое поле сортировки событий аудита.",
                repository=self.repository_name,
                operation="_get_order_by",
                details={
                    "sort_by": sort_by,
                    "allowed_fields": list(allowed_fields.keys()),
                },
            )

        if sort_direction not in {"asc", "desc"}:
            raise InvalidQueryError(
                "Недопустимое направление сортировки.",
                repository=self.repository_name,
                operation="_get_order_by",
                details={
                    "sort_direction": sort_direction,
                    "allowed_directions": ["asc", "desc"],
                },
            )

        column = allowed_fields[sort_by]

        if sort_direction == "desc":
            return column.desc().nullslast()

        return column.asc().nullslast()

    async def _execute_audit_statement(
        self,
        statement: Select[tuple[AuditLog]],
        *,
        operation: str,
    ) -> list[AuditLog]:
        """Выполняет SELECT-запрос для модели AuditLog.

        Метод оборачивает выполнение SQLAlchemy-запроса и приводит результат
        к списку объектов AuditLog.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для сообщения об ошибке.

        Returns:
            Список объектов AuditLog.

        Raises:
            RepositoryError: При ошибке выполнения SQL-запроса.
        """

        try:
            result = await self.session.execute(statement)

            return list(result.scalars().all())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Переопределённые методы
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: AuditLog,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> AuditLog:
        """Добавляет событие аудита в текущую сессию.

        Переопределяет базовый create для обработки ошибок целостности
        в контексте создания audit log.

        Args:
            entity: Объект AuditLog для добавления.
            flush: Если True, выполняет flush после добавления.
            refresh: Если True, обновляет объект из базы после flush.

        Returns:
            Добавленный объект AuditLog.

        Raises:
            RepositoryError: При ошибке целостности или ошибке базы данных.
        """

        try:
            return await super().create(
                entity,
                flush=flush,
                refresh=refresh,
            )

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_log",
            ) from exc

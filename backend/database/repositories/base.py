from __future__ import annotations

import builtins
import uuid
from collections.abc import Iterable, Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from database.exceptions import (
    ConstraintViolationError,
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidPaginationError,
    InvalidQueryError,
    RepositoryError,
)
from database.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Базовый репозиторий для ORM-моделей SQLAlchemy.

    Репозиторий инкапсулирует типовые операции чтения, записи, удаления,
    пагинации и выполнения SELECT-запросов для конкретной ORM-модели.

    Репозиторий намеренно не вызывает commit/rollback. Это позволяет
    объединять несколько операций разных репозиториев в одну транзакцию.

    Args:
        session: Асинхронная SQLAlchemy-сессия.
        model: ORM-модель, с которой работает репозиторий.
    """

    DEFAULT_LIMIT = 100
    MAX_LIMIT = 1000

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
    ) -> None:
        """Инициализирует базовый репозиторий.

        Args:
            session: Асинхронная SQLAlchemy-сессия.
            model: ORM-модель, с которой работает репозиторий.
        """

        self.session = session
        self.model = model

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def repository_name(self) -> str:
        """Возвращает название репозитория.

        Returns:
            Название класса репозитория.
        """

        return self.__class__.__name__

    @property
    def model_name(self) -> str:
        """Возвращает название ORM-модели.

        Returns:
            Название класса ORM-модели.
        """

        return self.model.__name__

    @property
    def table_name(self) -> str:
        """Возвращает название таблицы ORM-модели.

        Returns:
            Название таблицы базы данных.
        """

        return self.model.__tablename__

    # ------------------------------------------------------------------
    # Базовые SELECT-запросы
    # ------------------------------------------------------------------

    def select(self) -> Select[tuple[ModelT]]:
        """Возвращает базовый SELECT для модели репозитория.

        Returns:
            SQLAlchemy SELECT-запрос для ORM-модели.
        """

        return select(self.model)

    def select_where(self, *conditions: Any) -> Select[tuple[ModelT]]:
        """Возвращает SELECT с условиями фильтрации.

        Args:
            *conditions: Условия фильтрации SQLAlchemy.

        Returns:
            SQLAlchemy SELECT-запрос с применёнными условиями.
        """

        statement = self.select()

        if conditions:
            statement = statement.where(*conditions)

        return statement

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> ModelT | None:
        """Возвращает сущность по первичному ключу или ``None``.

        Args:
            entity_id: Идентификатор сущности.

        Returns:
            Найденная ORM-сущность или ``None``.

        Raises:
            RepositoryError: Если операция чтения завершилась ошибкой.
        """

        try:
            return await self.session.get(self.model, entity_id)

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="get_by_id",
                reason=str(exc),
                details={"entity_id": str(entity_id)},
                cause=exc,
            ) from exc

    async def get_required_by_id(
        self,
        entity_id: uuid.UUID,
    ) -> ModelT:
        """Возвращает обязательную сущность по первичному ключу.

        Args:
            entity_id: Идентификатор сущности.

        Returns:
            Найденная ORM-сущность.

        Raises:
            EntityNotFoundError: Если сущность не найдена.
            RepositoryError: Если операция чтения завершилась ошибкой.
        """

        entity = await self.get_by_id(entity_id)

        if entity is None:
            raise EntityNotFoundError(
                self.model_name,
                entity_id=entity_id,
                repository=self.repository_name,
            )

        return entity

    async def get_one_or_none(
        self,
        *conditions: Any,
    ) -> ModelT | None:
        """Возвращает одну сущность по условиям или ``None``.

        Args:
            *conditions: Условия фильтрации SQLAlchemy.

        Returns:
            Найденная ORM-сущность или ``None``.

        Raises:
            RepositoryError: Если операция чтения завершилась ошибкой.
        """

        statement = self.select_where(*conditions)

        return await self.scalar_one_or_none(
            statement,
            operation="get_one_or_none",
        )

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        order_by: Any | Sequence[Any] | None = None,
        conditions: Sequence[Any] | None = None,
    ) -> builtins.list[ModelT]:
        """Возвращает список сущностей с пагинацией.

        Args:
            offset: Смещение выборки.
            limit: Максимальное количество записей.
            order_by: Поле, выражение или последовательность выражений
                сортировки.
            conditions: Условия фильтрации SQLAlchemy.

        Returns:
            Список ORM-сущностей.

        Raises:
            InvalidPaginationError: Если параметры пагинации некорректны.
            RepositoryError: Если операция чтения завершилась ошибкой.
        """

        self._validate_pagination(offset=offset, limit=limit)

        statement = self.select()

        if conditions:
            statement = statement.where(*conditions)

        statement = self._apply_order_by(statement, order_by)
        statement = statement.offset(offset).limit(limit)

        return await self.scalars_all(statement, operation="list")

    async def list_keyset(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        after: Any | None = None,
        cursor_column: InstrumentedAttribute[Any] | None = None,
        ascending: bool = True,
        conditions: Sequence[Any] | None = None,
    ) -> builtins.list[ModelT]:
        """Возвращает страницу данных keyset-пагинацией.

        В отличие от ``list``/``paginate`` метод не использует ``OFFSET`` и не
        считает общее количество записей: страница выбирается по курсору
        (``cursor_column > after``) и сортируется по тому же столбцу. Стоимость
        выборки не зависит от глубины пагинации, поэтому метод подходит для
        пакетных проходов по большим таблицам.

        Args:
            limit: Максимальный размер страницы.
            after: Значение курсора (не включается в результат). Если ``None``,
                возвращается первая страница.
            cursor_column: Столбец-курсор. Если ``None``, используется первичный
                ключ модели. Столбец должен быть уникальным и индексированным,
                иначе возможны пропуски или дубли строк между страницами.
            ascending: Направление сортировки и сравнения курсора.
            conditions: Условия фильтрации SQLAlchemy.

        Returns:
            Список ORM-сущностей размером не больше ``limit``, отсортированный
            по ``cursor_column``.

        Raises:
            InvalidPaginationError: Если ``limit`` некорректен.
            RepositoryError: Если у модели составной первичный ключ и
                ``cursor_column`` не задан, или операция чтения завершилась
                ошибкой.
        """

        self._validate_pagination(offset=0, limit=limit)

        column = (
            cursor_column if cursor_column is not None else self._primary_key_column()
        )

        statement = self.select_where(*(conditions or ()))

        if after is not None:
            statement = statement.where(
                column > after if ascending else column < after,
            )

        statement = statement.order_by(
            column.asc() if ascending else column.desc(),
        )
        statement = statement.limit(limit)

        return await self.scalars_all(statement, operation="list_keyset")

    def _primary_key_column(self) -> InstrumentedAttribute[Any]:
        """Возвращает столбец первичного ключа модели для keyset-пагинации.

        Returns:
            ORM-атрибут единственного столбца первичного ключа.

        Raises:
            RepositoryError: Если модель имеет составной первичный ключ —
                в этом случае курсорный столбец нужно передавать явно.
        """

        primary_key = inspect(self.model).primary_key

        if len(primary_key) != 1:
            raise self._repository_error(
                operation="list_keyset",
                reason=(
                    "Keyset-пагинация по первичному ключу требует одного "
                    "столбца; для составного ключа передайте cursor_column."
                ),
            )

        return getattr(self.model, primary_key[0].name)

    async def exists(
        self,
        *conditions: Any,
    ) -> bool:
        """Проверяет существование хотя бы одной записи.

        Args:
            *conditions: Условия фильтрации SQLAlchemy.

        Returns:
            True, если хотя бы одна запись существует.

        Raises:
            RepositoryError: Если операция проверки завершилась ошибкой.
        """

        try:
            statement = select(
                self.select_where(*conditions).exists(),
            )

            result = await self.session.execute(statement)

            return bool(result.scalar_one())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="exists",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def count(
        self,
        *conditions: Any,
    ) -> int:
        """Возвращает количество записей по условиям.

        Args:
            *conditions: Условия фильтрации SQLAlchemy.

        Returns:
            Количество записей.

        Raises:
            RepositoryError: Если операция подсчёта завершилась ошибкой.
        """

        try:
            statement = select(func.count()).select_from(self.model)

            if conditions:
                statement = statement.where(*conditions)

            result = await self.session.execute(statement)

            return int(result.scalar_one())

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="count",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def paginate(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        order_by: Any | Sequence[Any] | None = None,
        conditions: Sequence[Any] | None = None,
    ) -> tuple[builtins.list[ModelT], int]:
        """Возвращает страницу данных и общее количество записей.

        Args:
            offset: Смещение выборки.
            limit: Максимальное количество записей.
            order_by: Поле, выражение или последовательность выражений
                сортировки.
            conditions: Условия фильтрации SQLAlchemy.

        Returns:
            Кортеж вида ``(items, total)``, где ``items`` — список сущностей,
            а ``total`` — общее количество записей.

        Raises:
            InvalidPaginationError: Если параметры пагинации некорректны.
            RepositoryError: Если операция чтения или подсчёта завершилась
                ошибкой.
        """

        self._validate_pagination(offset=offset, limit=limit)

        items = await self.list(
            offset=offset,
            limit=limit,
            order_by=order_by,
            conditions=conditions,
        )

        total = await self.count(*(conditions or ()))

        return items, total

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    async def create(
        self,
        entity: ModelT,
        *,
        flush: bool = True,
        refresh: bool = False,
    ) -> ModelT:
        """Добавляет новую сущность в сессию.

        Args:
            entity: ORM-сущность для добавления.
            flush: Выполнить ``flush`` после добавления.
            refresh: Обновить сущность из базы после ``flush``.

        Returns:
            Добавленная ORM-сущность.

        Raises:
            DuplicateEntityError: Если нарушено ограничение уникальности.
            ConstraintViolationError: Если нарушено ограничение базы данных.
            RepositoryError: Если операция создания завершилась ошибкой.
        """

        try:
            self.session.add(entity)

            if flush:
                await self.flush()

            if refresh:
                await self.refresh(entity)

            return entity

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="create",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def create_many(
        self,
        entities: Sequence[ModelT],
        *,
        flush: bool = True,
    ) -> builtins.list[ModelT]:
        """Добавляет несколько сущностей в сессию.

        Args:
            entities: Последовательность ORM-сущностей для добавления.
            flush: Выполнить ``flush`` после добавления.

        Returns:
            Список добавленных ORM-сущностей.

        Raises:
            DuplicateEntityError: Если нарушено ограничение уникальности.
            ConstraintViolationError: Если нарушено ограничение базы данных.
            RepositoryError: Если операция создания завершилась ошибкой.
        """

        try:
            entities_list = list(entities)

            if not entities_list:
                return []

            self.session.add_all(entities_list)

            if flush:
                await self.flush()

            return entities_list

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="create_many",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="create_many",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def update(
        self,
        entity: ModelT,
        values: dict[str, Any],
        *,
        flush: bool = True,
        refresh: bool = False,
        exclude_none: bool = False,
        allowed_fields: Iterable[str] | None = None,
    ) -> ModelT:
        """Обновляет поля существующей сущности.

        Args:
            entity: Экземпляр ORM-модели.
            values: Словарь обновляемых полей.
            flush: Выполнить ``flush`` после изменения.
            refresh: Обновить сущность из базы после ``flush``.
            exclude_none: Не применять значения ``None``.
            allowed_fields: Необязательный набор имён полей, которые разрешено
                обновлять. Если параметр не задан, разрешены все существующие
                поля модели.

        Returns:
            Обновлённая ORM-сущность.

        Raises:
            InvalidQueryError: Если поле не разрешено для обновления или
                отсутствует в модели.
            DuplicateEntityError: Если нарушено ограничение уникальности.
            ConstraintViolationError: Если нарушено ограничение базы данных.
            RepositoryError: Если операция обновления завершилась ошибкой.
        """

        try:
            allowed_fields_set = set(allowed_fields) if allowed_fields else None

            for field_name, value in values.items():
                if exclude_none and value is None:
                    continue

                if (
                    allowed_fields_set is not None
                    and field_name not in allowed_fields_set
                ):
                    raise InvalidQueryError(
                        "Поле не разрешено для обновления.",
                        repository=self.repository_name,
                        operation="update",
                        details={
                            "model": self.model_name,
                            "field": field_name,
                            "allowed_fields": sorted(allowed_fields_set),
                        },
                    )

                if not hasattr(entity, field_name):
                    raise InvalidQueryError(
                        "Попытка обновить несуществующее поле модели.",
                        repository=self.repository_name,
                        operation="update",
                        details={
                            "model": self.model_name,
                            "field": field_name,
                        },
                    )

                setattr(entity, field_name, value)

            if flush:
                await self.flush()

            if refresh:
                await self.refresh(entity)

            return entity

        except InvalidQueryError:
            raise

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="update",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="update",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def delete(
        self,
        entity: ModelT,
        *,
        flush: bool = True,
    ) -> None:
        """Физически удаляет сущность из сессии.

        Для моделей с soft delete конкретные репозитории должны реализовать
        отдельные методы мягкого удаления.

        Args:
            entity: ORM-сущность для удаления.
            flush: Выполнить ``flush`` после удаления.

        Raises:
            ConstraintViolationError: Если нарушено ограничение базы данных.
            RepositoryError: Если операция удаления завершилась ошибкой.
        """

        try:
            await self.session.delete(entity)

            if flush:
                await self.flush()

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="delete",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="delete",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def bulk_delete(
        self,
        *conditions: Any,
        flush: bool = True,
    ) -> int:
        """Выполняет массовое физическое удаление записей.

        Args:
            *conditions: Условия фильтрации SQLAlchemy.
            flush: Выполнить ``flush`` после удаления.

        Returns:
            Количество удалённых записей.

        Raises:
            ConstraintViolationError: Если нарушено ограничение базы данных.
            RepositoryError: Если операция массового удаления завершилась
                ошибкой.
        """

        try:
            statement = delete(self.model)

            if conditions:
                statement = statement.where(*conditions)

            result = await self.session.execute(statement)

            if flush:
                await self.flush()

            return int(getattr(result, "rowcount", 0) or 0)

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="bulk_delete",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="bulk_delete",
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Состояние сессии
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Выполняет ``flush`` текущей сессии.

        Raises:
            DuplicateEntityError: Если нарушено ограничение уникальности.
            ConstraintViolationError: Если нарушено ограничение базы данных.
            RepositoryError: Если операция ``flush`` завершилась ошибкой.
        """

        try:
            await self.session.flush()

        except IntegrityError as exc:
            raise self._handle_integrity_error(
                exc,
                operation="flush",
            ) from exc

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="flush",
                reason=str(exc),
                cause=exc,
            ) from exc

    async def refresh(
        self,
        entity: ModelT,
        *,
        attribute_names: builtins.list[str] | None = None,
    ) -> ModelT:
        """Обновляет ORM-объект из базы данных.

        Args:
            entity: ORM-сущность для обновления.
            attribute_names: Список атрибутов, которые нужно обновить.

        Returns:
            Обновлённая ORM-сущность.

        Raises:
            RepositoryError: Если операция обновления завершилась ошибкой.
        """

        try:
            await self.session.refresh(
                entity,
                attribute_names=attribute_names,
            )

            return entity

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation="refresh",
                reason=str(exc),
                details={
                    "entity": repr(entity),
                    "attribute_names": attribute_names,
                },
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Выполнение произвольных SELECT-запросов
    # ------------------------------------------------------------------

    async def scalar_one_or_none(
        self,
        statement: Select[tuple[ModelT]],
        *,
        operation: str = "scalar_one_or_none",
    ) -> ModelT | None:
        """Выполняет SELECT и возвращает одну ORM-сущность или ``None``.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для диагностических данных.

        Returns:
            Найденная ORM-сущность или ``None``.

        Raises:
            RepositoryError: Если выполнение запроса завершилось ошибкой.
        """

        try:
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc

    async def scalar_required(
        self,
        statement: Select[tuple[ModelT]],
        *,
        operation: str = "scalar_required",
        lookup: dict[str, Any] | None = None,
    ) -> ModelT:
        """Выполняет SELECT и возвращает обязательную ORM-сущность.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для диагностических данных.
            lookup: Диагностические параметры поиска сущности.

        Returns:
            Найденная ORM-сущность.

        Raises:
            EntityNotFoundError: Если сущность не найдена.
            RepositoryError: Если выполнение запроса завершилось ошибкой.
        """

        entity = await self.scalar_one_or_none(
            statement,
            operation=operation,
        )

        if entity is None:
            raise EntityNotFoundError(
                self.model_name,
                lookup=lookup,
                repository=self.repository_name,
            )

        return entity

    async def scalars_all(
        self,
        statement: Select[tuple[ModelT]],
        *,
        operation: str = "scalars_all",
    ) -> builtins.list[ModelT]:
        """Выполняет SELECT и возвращает список ORM-сущностей.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для диагностических данных.

        Returns:
            Список ORM-сущностей.

        Raises:
            RepositoryError: Если выполнение запроса завершилось ошибкой.
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

    async def scalar_value(
        self,
        statement: Select[Any],
        *,
        operation: str = "scalar_value",
    ) -> Any:
        """Выполняет SELECT и возвращает одно скалярное значение или ``None``.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            operation: Название операции для диагностических данных.

        Returns:
            Скалярное значение или ``None``.

        Raises:
            RepositoryError: Если выполнение запроса завершилось ошибкой.
        """

        try:
            result = await self.session.execute(statement)
            return result.scalar_one_or_none()

        except SQLAlchemyError as exc:
            raise self._repository_error(
                operation=operation,
                reason=str(exc),
                cause=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Валидация и интроспекция
    # ------------------------------------------------------------------

    def _validate_pagination(
        self,
        *,
        offset: int,
        limit: int,
    ) -> None:
        """Проверяет параметры пагинации.

        Args:
            offset: Смещение выборки.
            limit: Максимальное количество записей.

        Raises:
            InvalidPaginationError: Если ``offset`` отрицательный, ``limit``
                не положительный или превышает максимально допустимое значение.
        """

        if offset < 0:
            raise InvalidPaginationError(
                "Параметр offset не может быть отрицательным.",
                offset=offset,
                limit=limit,
                max_limit=self.MAX_LIMIT,
                details={
                    "repository": self.repository_name,
                    "model": self.model_name,
                },
            )

        if limit <= 0:
            raise InvalidPaginationError(
                "Параметр limit должен быть положительным.",
                offset=offset,
                limit=limit,
                max_limit=self.MAX_LIMIT,
                details={
                    "repository": self.repository_name,
                    "model": self.model_name,
                },
            )

        if limit > self.MAX_LIMIT:
            raise InvalidPaginationError(
                "Параметр limit превышает максимально допустимое значение.",
                offset=offset,
                limit=limit,
                max_limit=self.MAX_LIMIT,
                details={
                    "repository": self.repository_name,
                    "model": self.model_name,
                },
            )

    def _get_primary_key_column(self) -> InstrumentedAttribute[Any]:
        """Возвращает ORM-атрибут первичного ключа модели.

        Для большинства моделей проекта используется поле ``id``. Для составных
        ключей метод пытается определить единственный первичный ключ.

        Returns:
            ORM-атрибут первичного ключа модели.

        Raises:
            RepositoryError: Если первичный ключ не удалось определить.
        """

        if hasattr(self.model, "id"):
            return getattr(self.model, "id")

        mapper = inspect(self.model)
        primary_key_columns = list(mapper.primary_key)

        if len(primary_key_columns) != 1:
            raise RepositoryError(
                "Не удалось определить первичный ключ модели.",
                repository=self.repository_name,
                operation="_get_primary_key_column",
                details={
                    "model": self.model_name,
                    "primary_key_columns": [
                        column.name for column in primary_key_columns
                    ],
                },
            )

        primary_key_column_name = primary_key_columns[0].name

        return getattr(self.model, primary_key_column_name)

    def _apply_order_by(
        self,
        statement: Select[tuple[ModelT]],
        order_by: Any | Sequence[Any] | None,
    ) -> Select[tuple[ModelT]]:
        """Применяет сортировку к SELECT-запросу.

        Args:
            statement: SQLAlchemy SELECT-запрос.
            order_by: Поле, выражение или последовательность выражений
                сортировки.

        Returns:
            SELECT-запрос с применённой сортировкой.
        """

        if order_by is None:
            return statement

        if isinstance(order_by, Sequence) and not isinstance(order_by, str):
            return statement.order_by(*order_by)

        return statement.order_by(order_by)

    # ------------------------------------------------------------------
    # Ошибки
    # ------------------------------------------------------------------

    def _repository_error(
        self,
        *,
        operation: str,
        reason: str,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> RepositoryError:
        """Формирует ``RepositoryError`` с диагностическими данными.

        Args:
            operation: Название операции репозитория.
            reason: Описание причины ошибки.
            details: Дополнительные диагностические данные.
            cause: Исходное исключение, ставшее причиной ошибки.

        Returns:
            Исключение ``RepositoryError``.
        """

        merged_details: dict[str, Any] = {
            "model": self.model_name,
            "table": self.table_name,
            "reason": reason,
        }

        if details:
            merged_details.update(details)

        return RepositoryError(
            "Операция репозитория завершилась ошибкой.",
            repository=self.repository_name,
            operation=operation,
            details=merged_details,
            cause=cause,
        )

    def _handle_integrity_error(
        self,
        exc: IntegrityError,
        *,
        operation: str,
    ) -> RepositoryError:
        """Преобразует ``IntegrityError`` в исключение уровня приложения.

        Обрабатываемые PostgreSQL SQLSTATE-коды:

        * ``23505``: ``unique_violation``.
        * ``23503``: ``foreign_key_violation``.
        * ``23514``: ``check_violation``.
        * ``23502``: ``not_null_violation``.

        Args:
            exc: Исключение SQLAlchemy ``IntegrityError``.
            operation: Название операции репозитория.

        Returns:
            Исключение уровня приложения, соответствующее ошибке целостности.
        """

        original_exception = getattr(exc, "orig", None)

        sqlstate = getattr(original_exception, "sqlstate", None)
        constraint_name = getattr(original_exception, "constraint_name", None)
        table_name = getattr(original_exception, "table_name", None)
        column_name = getattr(original_exception, "column_name", None)

        reason = str(exc)

        if sqlstate == "23505":
            return DuplicateEntityError(
                self.model_name,
                field=constraint_name,
                repository=self.repository_name,
                message="Нарушено ограничение уникальности.",
                cause=exc,
            )

        if sqlstate in {"23503", "23514", "23502"}:
            return ConstraintViolationError(
                "Нарушено ограничение целостности базы данных.",
                constraint_name=constraint_name,
                table_name=table_name,
                column_name=column_name,
                repository=self.repository_name,
                operation=operation,
                details={
                    "model": self.model_name,
                    "sqlstate": sqlstate,
                    "reason": reason,
                },
                cause=exc,
            )

        return RepositoryError(
            "Ошибка целостности данных при выполнении операции репозитория.",
            repository=self.repository_name,
            operation=operation,
            details={
                "model": self.model_name,
                "table": self.table_name,
                "sqlstate": sqlstate,
                "constraint_name": constraint_name,
                "table_name": table_name,
                "column_name": column_name,
                "reason": reason,
            },
            cause=exc,
        )

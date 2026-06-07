from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, computed_field

from database.models.enums import QuotaResourceType
from schemas.common import BaseSchema


class UserQuotaBase(BaseSchema):
    """Базовые поля пользовательской квоты.

    Используется как общий родитель для схем создания и чтения квоты
    пользователя. Описывает лимиты и текущее использование основных ресурсов:
    хранилища, файлов, публичных ссылок и активных upload-сессий.

    Attributes:
        storage_limit_bytes: Максимальный размер хранилища пользователя в
            байтах.
        storage_used_bytes: Текущий использованный объём хранилища в байтах.
        max_file_size_bytes: Максимально допустимый размер одного файла в
            байтах.
        files_limit: Максимальное количество файлов. ``None`` означает
            отсутствие лимита.
        files_used: Текущее количество файлов пользователя.
        public_links_limit: Максимальное количество публичных ссылок. ``None``
            означает отсутствие лимита.
        public_links_used: Текущее количество публичных ссылок пользователя.
        active_upload_sessions_limit: Максимальное количество активных
            upload-сессий. ``None`` означает отсутствие лимита.
        active_upload_sessions_used: Текущее количество активных upload-сессий
            пользователя.
    """

    storage_limit_bytes: int = Field(
        ...,
        ge=0,
        description="Максимальный размер хранилища пользователя в байтах.",
    )
    storage_used_bytes: int = Field(
        default=0,
        ge=0,
        description="Текущий использованный объём хранилища в байтах.",
    )
    max_file_size_bytes: int = Field(
        ...,
        ge=0,
        description="Максимально допустимый размер одного файла в байтах.",
    )
    files_limit: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество файлов. None означает отсутствие лимита.",
    )
    files_used: int = Field(
        default=0,
        ge=0,
        description="Текущее количество файлов пользователя.",
    )
    public_links_limit: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество публичных ссылок. None означает отсутствие лимита.",
    )
    public_links_used: int = Field(
        default=0,
        ge=0,
        description="Текущее количество публичных ссылок пользователя.",
    )
    active_upload_sessions_limit: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество активных upload-сессий. None означает отсутствие лимита.",
    )
    active_upload_sessions_used: int = Field(
        default=0,
        ge=0,
        description="Текущее количество активных upload-сессий пользователя.",
    )


class UserQuotaCreate(UserQuotaBase):
    """Запрос на создание квоты пользователя.

    Используется для создания записи квоты для конкретного пользователя с
    начальными лимитами и счётчиками использования ресурсов.

    Attributes:
        storage_limit_bytes: Максимальный размер хранилища пользователя в
            байтах.
        storage_used_bytes: Текущий использованный объём хранилища в байтах.
        max_file_size_bytes: Максимально допустимый размер одного файла в
            байтах.
        files_limit: Максимальное количество файлов. ``None`` означает
            отсутствие лимита.
        files_used: Текущее количество файлов пользователя.
        public_links_limit: Максимальное количество публичных ссылок. ``None``
            означает отсутствие лимита.
        public_links_used: Текущее количество публичных ссылок пользователя.
        active_upload_sessions_limit: Максимальное количество активных
            upload-сессий. ``None`` означает отсутствие лимита.
        active_upload_sessions_used: Текущее количество активных upload-сессий
            пользователя.
        user_id: Идентификатор пользователя, которому создаётся квота.
    """

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, которому создаётся квота.",
    )


class UserQuotaUpdate(BaseSchema):
    """Запрос на обновление пользовательской квоты.

    Используется для частичного изменения лимитов и текущих счётчиков
    использования ресурсов пользователя.

    Attributes:
        storage_limit_bytes: Новый максимальный размер хранилища пользователя в
            байтах.
        storage_used_bytes: Новое значение использованного объёма хранилища в
            байтах.
        max_file_size_bytes: Новый максимально допустимый размер одного файла в
            байтах.
        files_limit: Новый лимит количества файлов. ``None`` означает
            отсутствие лимита.
        files_used: Новое текущее количество файлов пользователя.
        public_links_limit: Новый лимит количества публичных ссылок. ``None``
            означает отсутствие лимита.
        public_links_used: Новое текущее количество публичных ссылок
            пользователя.
        active_upload_sessions_limit: Новый лимит активных upload-сессий.
            ``None`` означает отсутствие лимита.
        active_upload_sessions_used: Новое текущее количество активных
            upload-сессий пользователя.
    """

    storage_limit_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Новый максимальный размер хранилища пользователя в байтах.",
    )
    storage_used_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Новое значение использованного объёма хранилища в байтах.",
    )
    max_file_size_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Новый максимально допустимый размер одного файла в байтах.",
    )
    files_limit: int | None = Field(
        default=None,
        ge=0,
        description="Новый лимит количества файлов. None означает отсутствие лимита.",
    )
    files_used: int | None = Field(
        default=None,
        ge=0,
        description="Новое текущее количество файлов пользователя.",
    )
    public_links_limit: int | None = Field(
        default=None,
        ge=0,
        description="Новый лимит количества публичных ссылок. None означает отсутствие лимита.",
    )
    public_links_used: int | None = Field(
        default=None,
        ge=0,
        description="Новое текущее количество публичных ссылок пользователя.",
    )
    active_upload_sessions_limit: int | None = Field(
        default=None,
        ge=0,
        description="Новый лимит активных upload-сессий. None означает отсутствие лимита.",
    )
    active_upload_sessions_used: int | None = Field(
        default=None,
        ge=0,
        description="Новое текущее количество активных upload-сессий пользователя.",
    )


class UserQuotaRead(UserQuotaBase):
    """Полное представление пользовательской квоты.

    Используется для возврата квоты пользователя вместе с вычисленными
    значениями доступного хранилища, процента использования и признака
    заполненности хранилища.

    Attributes:
        storage_limit_bytes: Максимальный размер хранилища пользователя в
            байтах.
        storage_used_bytes: Текущий использованный объём хранилища в байтах.
        max_file_size_bytes: Максимально допустимый размер одного файла в
            байтах.
        files_limit: Максимальное количество файлов. ``None`` означает
            отсутствие лимита.
        files_used: Текущее количество файлов пользователя.
        public_links_limit: Максимальное количество публичных ссылок. ``None``
            означает отсутствие лимита.
        public_links_used: Текущее количество публичных ссылок пользователя.
        active_upload_sessions_limit: Максимальное количество активных
            upload-сессий. ``None`` означает отсутствие лимита.
        active_upload_sessions_used: Текущее количество активных upload-сессий
            пользователя.
        id: Уникальный идентификатор записи квоты.
        user_id: Идентификатор пользователя, которому принадлежит квота.
        available_storage_bytes: Доступный объём хранилища в байтах.
        usage_percent: Процент использования хранилища.
        is_storage_full: Признак полного заполнения хранилища.
        created_at: Дата и время создания квоты.
        updated_at: Дата и время последнего обновления квоты.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор записи квоты.",
    )
    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, которому принадлежит квота.",
    )
    available_storage_bytes: int = Field(
        ...,
        ge=0,
        description="Доступный объём хранилища в байтах.",
    )
    usage_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="Процент использования хранилища.",
    )
    is_storage_full: bool = Field(
        ...,
        description="Признак полного заполнения хранилища.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания квоты.",
    )
    updated_at: datetime = Field(
        ...,
        description="Дата и время последнего обновления квоты.",
    )


class QuotaUsageRead(BaseSchema):
    """Сводка использования квот пользователя.

    Используется для отображения текущего использования ресурсов пользователя,
    доступного объёма хранилища, процента использования и признаков достижения
    отдельных лимитов.

    Attributes:
        user_id: Идентификатор пользователя.
        storage_limit_bytes: Максимальный размер хранилища пользователя в
            байтах.
        storage_used_bytes: Использованный объём хранилища в байтах.
        max_file_size_bytes: Максимально допустимый размер одного файла в
            байтах.
        files_limit: Максимальное количество файлов. ``None`` означает
            отсутствие лимита.
        files_used: Текущее количество файлов пользователя.
        public_links_limit: Максимальное количество публичных ссылок. ``None``
            означает отсутствие лимита.
        public_links_used: Текущее количество публичных ссылок пользователя.
        active_upload_sessions_limit: Максимальное количество активных
            upload-сессий. ``None`` означает отсутствие лимита.
        active_upload_sessions_used: Текущее количество активных upload-сессий
            пользователя.
        available_storage_bytes: Доступный объём хранилища в байтах.
        usage_percent: Процент использования хранилища.
        is_storage_full: Признак полного заполнения хранилища.
        is_files_limit_reached: Достигнут ли лимит количества файлов.
        is_public_links_limit_reached: Достигнут ли лимит публичных ссылок.
        is_active_upload_sessions_limit_reached: Достигнут ли лимит активных
            upload-сессий.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя.",
    )
    storage_limit_bytes: int = Field(
        ...,
        ge=0,
        description="Максимальный размер хранилища пользователя в байтах.",
    )
    storage_used_bytes: int = Field(
        ...,
        ge=0,
        description="Использованный объём хранилища в байтах.",
    )
    max_file_size_bytes: int = Field(
        ...,
        ge=0,
        description="Максимально допустимый размер одного файла в байтах.",
    )
    files_limit: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество файлов. None означает отсутствие лимита.",
    )
    files_used: int = Field(
        ...,
        ge=0,
        description="Текущее количество файлов пользователя.",
    )
    public_links_limit: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество публичных ссылок. None означает отсутствие лимита.",
    )
    public_links_used: int = Field(
        ...,
        ge=0,
        description="Текущее количество публичных ссылок пользователя.",
    )
    active_upload_sessions_limit: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество активных upload-сессий. None означает отсутствие лимита.",
    )
    active_upload_sessions_used: int = Field(
        ...,
        ge=0,
        description="Текущее количество активных upload-сессий пользователя.",
    )

    @computed_field(description="Доступный объём хранилища в байтах.")
    @property
    def available_storage_bytes(self) -> int:
        """Вычисляет доступный объём хранилища.

        Returns:
            Разница между лимитом и использованным объёмом хранилища. Если
            использованный объём превышает лимит, возвращает ``0``.
        """

        return max(self.storage_limit_bytes - self.storage_used_bytes, 0)

    @computed_field(description="Процент использования хранилища.")
    @property
    def usage_percent(self) -> float:
        """Вычисляет процент использования хранилища.

        Returns:
            Процент использования хранилища, округлённый до двух знаков после
            запятой. Если лимит хранилища равен нулю, возвращает ``100.0`` при
            наличии использованного объёма и ``0.0`` в остальных случаях.
        """

        if self.storage_limit_bytes <= 0:
            return 100.0 if self.storage_used_bytes > 0 else 0.0

        percent = self.storage_used_bytes / self.storage_limit_bytes * 100
        return round(min(percent, 100.0), 2)

    @computed_field(description="Признак полного заполнения хранилища.")
    @property
    def is_storage_full(self) -> bool:
        """Проверяет, заполнено ли хранилище.

        Returns:
            ``True``, если использованный объём хранилища больше либо равен
            лимиту, иначе ``False``.
        """

        return self.storage_used_bytes >= self.storage_limit_bytes

    @computed_field(description="Достигнут ли лимит количества файлов.")
    @property
    def is_files_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит количества файлов.

        Returns:
            ``True``, если лимит файлов задан и текущее количество файлов
            больше либо равно лимиту, иначе ``False``.
        """

        return self.files_limit is not None and self.files_used >= self.files_limit

    @computed_field(description="Достигнут ли лимит публичных ссылок.")
    @property
    def is_public_links_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит публичных ссылок.

        Returns:
            ``True``, если лимит публичных ссылок задан и текущее количество
            ссылок больше либо равно лимиту, иначе ``False``.
        """

        return (
            self.public_links_limit is not None
            and self.public_links_used >= self.public_links_limit
        )

    @computed_field(description="Достигнут ли лимит активных upload-сессий.")
    @property
    def is_active_upload_sessions_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит активных upload-сессий.

        Returns:
            ``True``, если лимит активных upload-сессий задан и текущее
            количество сессий больше либо равно лимиту, иначе ``False``.
        """

        return (
            self.active_upload_sessions_limit is not None
            and self.active_upload_sessions_used >= self.active_upload_sessions_limit
        )


class QuotaCheckRequest(BaseSchema):
    """Запрос на проверку возможности расходования квоты.

    Используется перед операцией, которая расходует квотируемый ресурс:
    хранилище, файл, публичную ссылку или upload-сессию.

    Attributes:
        user_id: Идентификатор пользователя, для которого проверяется квота.
        resource_type: Тип ресурса, для которого выполняется проверка квоты.
        requested_amount: Запрашиваемый объём ресурса.
    """

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, для которого проверяется квота.",
    )
    resource_type: QuotaResourceType = Field(
        ...,
        description="Тип ресурса, для которого выполняется проверка квоты.",
    )
    requested_amount: int = Field(
        ...,
        ge=0,
        description="Запрашиваемый объём ресурса.",
    )


class QuotaCheckResponse(BaseSchema):
    """Результат проверки квоты.

    Используется для возврата решения о возможности выполнить операцию с учётом
    текущего использования ресурса, установленного лимита и запрошенного объёма.

    Attributes:
        allowed: Разрешена ли операция с учётом текущей квоты.
        user_id: Идентификатор пользователя, для которого выполнена проверка.
        resource_type: Тип проверенного ресурса.
        requested_amount: Запрошенный объём ресурса.
        limit: Установленный лимит ресурса. ``None`` означает отсутствие
            лимита.
        used: Текущий использованный объём ресурса.
        available: Доступный объём ресурса. ``None`` означает отсутствие
            лимита.
        reason: Причина отказа или дополнительное пояснение.
    """

    allowed: bool = Field(
        ...,
        description="Разрешена ли операция с учётом текущей квоты.",
    )
    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, для которого выполнена проверка.",
    )
    resource_type: QuotaResourceType = Field(
        ...,
        description="Тип проверенного ресурса.",
    )
    requested_amount: int = Field(
        ...,
        ge=0,
        description="Запрошенный объём ресурса.",
    )
    limit: int | None = Field(
        default=None,
        ge=0,
        description="Установленный лимит ресурса. None означает отсутствие лимита.",
    )
    used: int = Field(
        ...,
        ge=0,
        description="Текущий использованный объём ресурса.",
    )
    available: int | None = Field(
        default=None,
        ge=0,
        description="Доступный объём ресурса. None означает отсутствие лимита.",
    )
    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина отказа или дополнительное пояснение.",
    )


class QuotaRecalculateRequest(BaseSchema):
    """Запрос на пересчёт квоты пользователя.

    Используется для синхронизации счётчиков использования квот с фактическим
    состоянием данных. Может пересчитывать все поддерживаемые ресурсы или
    только указанные типы.

    Attributes:
        user_id: Идентификатор пользователя, для которого нужно пересчитать
            квоту.
        resource_types: Список типов ресурсов для пересчёта. ``None`` означает
            пересчёт всех поддерживаемых ресурсов.
        force: Выполнить пересчёт принудительно.
    """

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, для которого нужно пересчитать квоту.",
    )
    resource_types: list[QuotaResourceType] | None = Field(
        default=None,
        description=(
            "Список типов ресурсов для пересчёта. "
            "None означает пересчёт всех поддерживаемых ресурсов."
        ),
    )
    force: bool = Field(
        default=False,
        description="Выполнить пересчёт принудительно.",
    )

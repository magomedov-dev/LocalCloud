from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from database.models.enums import (
    BackgroundTaskStatus,
    PublicLinkPermissionType,
    PublicLinkStatus,
)
from schemas.common import BaseSchema, PaginationParams
from schemas.nodes import NodeListItem


class PublicLinkCreateRequest(BaseSchema):
    """Запрос на создание публичной ссылки.

    Используется для создания публичной ссылки на файл или папку с заданным
    типом доступа, сроком действия, лимитом скачиваний, паролем и описанием.

    Attributes:
        node_id: Идентификатор файла или папки, для которого создаётся
            публичная ссылка.
        permission_type: Тип доступа, предоставляемый публичной ссылкой.
        expires_at: Дата и время истечения срока действия публичной ссылки.
        max_downloads: Максимальное количество скачиваний. ``None`` означает
            отсутствие лимита.
        password: Пароль для защиты публичной ссылки. Хэширование выполняется
            в service/security-слое.
        description: Необязательное описание публичной ссылки.
    """

    node_id: UUID = Field(
        ...,
        description="Идентификатор файла или папки, для которого создаётся публичная ссылка.",
    )
    permission_type: PublicLinkPermissionType = Field(
        default=PublicLinkPermissionType.DOWNLOAD,
        description="Тип доступа, предоставляемый публичной ссылкой.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения срока действия публичной ссылки.",
    )
    max_downloads: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество скачиваний. None означает отсутствие лимита.",
    )
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Пароль для защиты публичной ссылки. Хэширование выполняется в service/security-слое.",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Необязательное описание публичной ссылки.",
    )

    @field_validator("password", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует необязательные текстовые поля.

        Args:
            value: Исходное значение текстового поля.

        Returns:
            Строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class PublicLinkUpdateRequest(BaseSchema):
    """Запрос на обновление публичной ссылки.

    Используется для частичного обновления параметров публичной ссылки:
    типа доступа, статуса, срока действия, лимита скачиваний, пароля, описания
    и признака активности.

    Attributes:
        permission_type: Новый тип доступа публичной ссылки.
        status: Новый статус публичной ссылки.
        expires_at: Новая дата истечения срока действия ссылки. ``None`` может
            означать отсутствие срока.
        max_downloads: Новый лимит скачиваний. ``None`` означает отсутствие
            лимита.
        password: Новый пароль публичной ссылки. Хэширование выполняется в
            service/security-слое.
        clear_password: Удалить пароль публичной ссылки.
        description: Новое описание публичной ссылки.
        is_active: Новый признак активности публичной ссылки.
    """

    permission_type: PublicLinkPermissionType | None = Field(
        default=None,
        description="Новый тип доступа публичной ссылки.",
    )
    status: PublicLinkStatus | None = Field(
        default=None,
        description="Новый статус публичной ссылки.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Новая дата истечения срока действия ссылки. None может означать отсутствие срока.",
    )
    max_downloads: int | None = Field(
        default=None,
        ge=0,
        description="Новый лимит скачиваний. None означает отсутствие лимита.",
    )
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Новый пароль публичной ссылки. Хэширование выполняется в service/security-слое.",
    )
    clear_password: bool = Field(
        default=False,
        description="Удалить пароль публичной ссылки.",
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Новое описание публичной ссылки.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Новый признак активности публичной ссылки.",
    )

    @field_validator("password", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует необязательные текстовые поля.

        Args:
            value: Исходное значение текстового поля.

        Returns:
            Строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @model_validator(mode="after")
    def validate_update_fields(self) -> PublicLinkUpdateRequest:
        """Проверяет корректность запроса на обновление публичной ссылки.

        Валидатор требует передать хотя бы одно поле для изменения и запрещает
        одновременно задавать новый пароль и флаг удаления пароля.

        Returns:
            Текущий объект запроса, если он корректен.

        Raises:
            ValueError: Если не передано ни одного поля для изменения публичной
                ссылки.
            ValueError: Если одновременно переданы ``password`` и
                ``clear_password=True``.
        """

        update_fields = {
            "permission_type",
            "status",
            "expires_at",
            "max_downloads",
            "password",
            "clear_password",
            "description",
            "is_active",
        }
        if not (self.model_fields_set & update_fields):
            raise ValueError(
                "Нужно передать хотя бы одно поле для изменения публичной ссылки."
            )
        if self.password is not None and self.clear_password:
            raise ValueError(
                "Нельзя одновременно передавать новый пароль и флаг clear_password."
            )

        return self


class PublicLinkRead(BaseSchema):
    """Полное безопасное представление публичной ссылки для владельца.

    Используется для отображения владельцу всех публичных и управленческих
    данных ссылки без раскрытия хэша пароля.

    Attributes:
        id: Уникальный идентификатор публичной ссылки.
        node_id: Идентификатор узла файловой системы, доступного по ссылке.
        created_by: Идентификатор пользователя, создавшего публичную ссылку.
        token: Публичный токен ссылки.
        permission_type: Тип доступа, предоставляемый публичной ссылкой.
        status: Текущий статус публичной ссылки.
        expires_at: Дата и время истечения срока действия публичной ссылки.
        max_downloads: Максимальное количество скачиваний. ``None`` означает
            отсутствие лимита.
        download_count: Текущее количество скачиваний по публичной ссылке.
        view_count: Количество просмотров публичной ссылки.
        upload_count: Количество загрузок через публичную ссылку.
        is_active: Признак активности публичной ссылки.
        revoked_at: Дата и время отзыва публичной ссылки.
        revoked_by: Идентификатор пользователя, отозвавшего публичную ссылку.
        revoke_reason: Причина отзыва публичной ссылки.
        last_accessed_at: Дата и время последнего обращения к публичной ссылке.
        last_downloaded_at: Дата и время последнего скачивания по публичной
            ссылке.
        last_uploaded_at: Дата и время последней загрузки через публичную
            ссылку.
        description: Описание публичной ссылки.
        created_at: Дата и время создания публичной ссылки.
        has_password: Защищена ли публичная ссылка паролем.
        node: Краткие данные узла файловой системы, если они были загружены.
        is_download_limit_reached: Достигнут ли лимит скачиваний.
        is_revoked: Отозвана ли публичная ссылка.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор публичной ссылки.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор узла файловой системы, доступного по ссылке.",
    )
    created_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, создавшего публичную ссылку.",
    )
    token: str = Field(
        ...,
        description="Публичный токен ссылки.",
    )
    permission_type: PublicLinkPermissionType = Field(
        ...,
        description="Тип доступа, предоставляемый публичной ссылкой.",
    )
    status: PublicLinkStatus = Field(
        ...,
        description="Текущий статус публичной ссылки.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения срока действия публичной ссылки.",
    )
    max_downloads: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество скачиваний. None означает отсутствие лимита.",
    )
    download_count: int = Field(
        ...,
        ge=0,
        description="Текущее количество скачиваний по публичной ссылке.",
    )
    view_count: int = Field(
        ...,
        ge=0,
        description="Количество просмотров публичной ссылки.",
    )
    upload_count: int = Field(
        ...,
        ge=0,
        description="Количество загрузок через публичную ссылку.",
    )
    is_active: bool = Field(
        ...,
        description="Признак активности публичной ссылки.",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="Дата и время отзыва публичной ссылки.",
    )
    revoked_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, отозвавшего публичную ссылку.",
    )
    revoke_reason: str | None = Field(
        default=None,
        description="Причина отзыва публичной ссылки.",
    )
    last_accessed_at: datetime | None = Field(
        default=None,
        description="Дата и время последнего обращения к публичной ссылке.",
    )
    last_downloaded_at: datetime | None = Field(
        default=None,
        description="Дата и время последнего скачивания по публичной ссылке.",
    )
    last_uploaded_at: datetime | None = Field(
        default=None,
        description="Дата и время последней загрузки через публичную ссылку.",
    )
    description: str | None = Field(
        default=None,
        description="Описание публичной ссылки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания публичной ссылки.",
    )
    has_password: bool = Field(
        default=False,
        description="Защищена ли публичная ссылка паролем.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные узла файловой системы, если они были загружены.",
    )

    @computed_field(description="Достигнут ли лимит скачиваний.")
    @property
    def is_download_limit_reached(self) -> bool:
        """Проверяет, достигнут ли лимит скачиваний.

        Returns:
            ``True``, если лимит скачиваний задан и текущее количество
            скачиваний больше либо равно лимиту, иначе ``False``.
        """

        return (
            self.max_downloads is not None and self.download_count >= self.max_downloads
        )

    @computed_field(description="Отозвана ли публичная ссылка.")
    @property
    def is_revoked(self) -> bool:
        """Проверяет, отозвана ли публичная ссылка.

        Returns:
            ``True``, если у ссылки есть дата отзыва или статус
            ``REVOKED``, иначе ``False``.
        """

        return self.revoked_at is not None or self.status == PublicLinkStatus.REVOKED


class PublicLinkListItem(BaseSchema):
    """Краткое представление публичной ссылки для списков.

    Используется в списках публичных ссылок, когда не нужны подробные поля
    вроде причины отзыва и дат последнего доступа.

    Attributes:
        id: Уникальный идентификатор публичной ссылки.
        node_id: Идентификатор узла файловой системы, доступного по ссылке.
        created_by: Идентификатор пользователя, создавшего публичную ссылку.
        token: Публичный токен ссылки.
        permission_type: Тип доступа, предоставляемый публичной ссылкой.
        status: Текущий статус публичной ссылки.
        expires_at: Дата и время истечения срока действия публичной ссылки.
        max_downloads: Максимальное количество скачиваний. ``None`` означает
            отсутствие лимита.
        download_count: Текущее количество скачиваний по публичной ссылке.
        view_count: Количество просмотров публичной ссылки.
        upload_count: Количество загрузок через публичную ссылку.
        is_active: Признак активности публичной ссылки.
        has_password: Защищена ли публичная ссылка паролем.
        created_at: Дата и время создания публичной ссылки.
        node: Краткие данные узла файловой системы, если они были загружены.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор публичной ссылки.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор узла файловой системы, доступного по ссылке.",
    )
    created_by: UUID | None = Field(
        default=None,
        description="Идентификатор пользователя, создавшего публичную ссылку.",
    )
    token: str = Field(
        ...,
        description="Публичный токен ссылки.",
    )
    permission_type: PublicLinkPermissionType = Field(
        ...,
        description="Тип доступа, предоставляемый публичной ссылкой.",
    )
    status: PublicLinkStatus = Field(
        ...,
        description="Текущий статус публичной ссылки.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения срока действия публичной ссылки.",
    )
    max_downloads: int | None = Field(
        default=None,
        ge=0,
        description="Максимальное количество скачиваний. None означает отсутствие лимита.",
    )
    download_count: int = Field(
        ...,
        ge=0,
        description="Текущее количество скачиваний по публичной ссылке.",
    )
    view_count: int = Field(
        ...,
        ge=0,
        description="Количество просмотров публичной ссылки.",
    )
    upload_count: int = Field(
        ...,
        ge=0,
        description="Количество загрузок через публичную ссылку.",
    )
    is_active: bool = Field(
        ...,
        description="Признак активности публичной ссылки.",
    )
    has_password: bool = Field(
        default=False,
        description="Защищена ли публичная ссылка паролем.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания публичной ссылки.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные узла файловой системы, если они были загружены.",
    )


class PublicLinkPublicRead(BaseSchema):
    """Публичное представление ссылки без внутренних и владельческих данных.

    Используется для отображения публичной ссылки внешнему пользователю.
    Не содержит токен, owner-specific поля, счётчики и служебные сведения,
    которые не должны раскрываться публично.

    Attributes:
        id: Уникальный идентификатор публичной ссылки.
        node_id: Идентификатор доступного узла файловой системы.
        permission_type: Тип доступа, предоставляемый публичной ссылкой.
        status: Текущий статус публичной ссылки.
        expires_at: Дата и время истечения срока действия публичной ссылки.
        has_password: Требуется ли пароль для доступа к публичной ссылке.
        description: Описание публичной ссылки.
        node: Краткие данные доступного узла, если их можно показывать
            публично.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор публичной ссылки.",
    )
    node_id: UUID = Field(
        ...,
        description="Идентификатор доступного узла файловой системы.",
    )
    permission_type: PublicLinkPermissionType = Field(
        ...,
        description="Тип доступа, предоставляемый публичной ссылкой.",
    )
    status: PublicLinkStatus = Field(
        ...,
        description="Текущий статус публичной ссылки.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения срока действия публичной ссылки.",
    )
    has_password: bool = Field(
        default=False,
        description="Требуется ли пароль для доступа к публичной ссылке.",
    )
    description: str | None = Field(
        default=None,
        description="Описание публичной ссылки.",
    )
    node: NodeListItem | None = Field(
        default=None,
        description="Краткие данные доступного узла, если их можно показывать публично.",
    )


class PublicLinkAccessRequest(BaseSchema):
    """Запрос на доступ к публичной ссылке.

    Используется для проверки публичного токена и, при необходимости, пароля
    публичной ссылки.

    Attributes:
        token: Публичный токен ссылки.
        password: Пароль публичной ссылки, если она защищена.
    """

    token: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Публичный токен ссылки.",
    )
    password: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Пароль публичной ссылки, если она защищена.",
    )

    @field_validator("token", "password")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует токен или пароль публичной ссылки.

        Args:
            value: Исходное значение токена или пароля.

        Returns:
            Значение без пробелов по краям или ``None``, если значение
            отсутствует.

        Raises:
            ValueError: Если переданное значение содержит только пробельные
                символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Значение не должно быть пустым.")

        return normalized_value


class PublicLinkAccessResponse(BaseSchema):
    """Ответ после проверки доступа к публичной ссылке.

    Возвращает результат проверки публичного токена и пароля, публичные данные
    ссылки и признак необходимости пароля.

    Attributes:
        allowed: Разрешён ли доступ к публичной ссылке.
        link: Публичные данные ссылки, если доступ разрешён.
        requires_password: Требуется ли пароль для доступа.
        message: Дополнительное сообщение о результате проверки доступа.
    """

    allowed: bool = Field(
        ...,
        description="Разрешён ли доступ к публичной ссылке.",
    )
    link: PublicLinkPublicRead | None = Field(
        default=None,
        description="Публичные данные ссылки, если доступ разрешён.",
    )
    requires_password: bool = Field(
        default=False,
        description="Требуется ли пароль для доступа.",
    )
    message: str | None = Field(
        default=None,
        description="Дополнительное сообщение о результате проверки доступа.",
    )


class PublicLinkDownloadResponse(BaseSchema):
    """Ответ со ссылкой на скачивание через публичную ссылку.

    Содержит предварительно подписанную ссылку, срок её действия, HTTP-метод,
    заголовки и сведения о скачиваемом файле.

    Attributes:
        presigned_url: Предварительно подписанная ссылка на скачивание.
        expires_at: Дата и время истечения срока действия ссылки на
            скачивание.
        method: HTTP-метод для скачивания.
        headers: HTTP-заголовки, которые нужно использовать при скачивании.
        filename: Предлагаемое имя скачиваемого файла.
        size_bytes: Размер скачиваемого файла в байтах, если известен.
        mime_type: MIME-тип скачиваемого файла, если известен.
    """

    presigned_url: str = Field(
        ...,
        description="Предварительно подписанная ссылка на скачивание.",
    )
    expires_at: datetime = Field(
        ...,
        description="Дата и время истечения срока действия ссылки на скачивание.",
    )
    method: str = Field(
        default="GET",
        description="HTTP-метод для скачивания.",
        examples=["GET"],
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP-заголовки, которые нужно использовать при скачивании.",
    )
    filename: str | None = Field(
        default=None,
        description="Предлагаемое имя скачиваемого файла.",
    )
    size_bytes: int | None = Field(
        default=None,
        ge=0,
        description="Размер скачиваемого файла в байтах, если известен.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип скачиваемого файла, если известен.",
    )

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        """Нормализует HTTP-метод для скачивания.

        Args:
            value: Исходное значение HTTP-метода.

        Returns:
            HTTP-метод без пробелов по краям в верхнем регистре.

        Raises:
            ValueError: Если HTTP-метод пустой после нормализации.
        """

        normalized_value = value.strip().upper()

        if not normalized_value:
            raise ValueError("HTTP-метод не должен быть пустым.")

        return normalized_value


class PublicLinkFolderArchiveResponse(BaseSchema):
    """Ответ при создании или опросе статуса архива папки по публичной ссылке.

    Attributes:
        task_id: Идентификатор фоновой задачи создания архива.
        status: Текущий статус задачи.
        presigned_url: Предварительно подписанная ссылка на скачивание (только
            если статус completed).
        expires_at: Срок действия ссылки на скачивание.
        filename: Предлагаемое имя ZIP-файла.
        size_bytes: Размер архива в байтах, если известен.
    """

    task_id: UUID = Field(
        ..., description="Идентификатор фоновой задачи создания архива."
    )
    status: BackgroundTaskStatus = Field(..., description="Текущий статус задачи.")
    presigned_url: str | None = Field(
        default=None, description="Ссылка на скачивание (только при статусе completed)."
    )
    expires_at: datetime | None = Field(
        default=None, description="Срок действия ссылки на скачивание."
    )
    filename: str | None = Field(
        default=None, description="Предлагаемое имя ZIP-файла."
    )
    size_bytes: int | None = Field(
        default=None, ge=0, description="Размер архива в байтах."
    )


class PublicLinkRevokeRequest(BaseSchema):
    """Запрос на отзыв публичной ссылки.

    Используется для отзыва публичной ссылки с необязательным указанием причины.
    Причина отзыва нормализуется: пробелы по краям удаляются, пустая строка
    приводится к ``None``.

    Attributes:
        revoke_reason: Причина отзыва публичной ссылки.
    """

    revoke_reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина отзыва публичной ссылки.",
    )

    @field_validator("revoke_reason")
    @classmethod
    def normalize_revoke_reason(cls, value: str | None) -> str | None:
        """Нормализует причину отзыва публичной ссылки.

        Args:
            value: Исходная причина отзыва.

        Returns:
            Причина отзыва без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class PublicLinkQueryParams(PaginationParams):
    """Параметры фильтрации публичных ссылок.

    Используется для постраничного получения публичных ссылок с фильтрами по
    узлу, создателю, типу доступа, статусу, активности, защите паролем, датам
    создания, сроку истечения и поисковой строке.

    Attributes:
        node_id: Фильтр по узлу файловой системы.
        created_by: Фильтр по пользователю, создавшему публичную ссылку.
        permission_type: Фильтр по типу доступа публичной ссылки.
        status: Фильтр по статусу публичной ссылки.
        is_active: Фильтр по признаку активности публичной ссылки.
        has_password: Фильтр по признаку защиты паролем.
        created_from: Фильтр по дате создания: начало диапазона включительно.
        created_to: Фильтр по дате создания: конец диапазона включительно.
        expires_before: Вернуть ссылки, срок действия которых истекает не
            позднее указанного времени.
        query: Поисковая строка по описанию или токену ссылки.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    node_id: UUID | None = Field(
        default=None,
        description="Фильтр по узлу файловой системы.",
    )
    created_by: UUID | None = Field(
        default=None,
        description="Фильтр по пользователю, создавшему публичную ссылку.",
    )
    permission_type: PublicLinkPermissionType | None = Field(
        default=None,
        description="Фильтр по типу доступа публичной ссылки.",
    )
    status: PublicLinkStatus | None = Field(
        default=None,
        description="Фильтр по статусу публичной ссылки.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Фильтр по признаку активности публичной ссылки.",
    )
    has_password: bool | None = Field(
        default=None,
        description="Фильтр по признаку защиты паролем.",
    )
    created_from: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: начало диапазона включительно.",
    )
    created_to: datetime | None = Field(
        default=None,
        description="Фильтр по дате создания: конец диапазона включительно.",
    )
    expires_before: datetime | None = Field(
        default=None,
        description="Вернуть ссылки, срок действия которых истекает не позднее указанного времени.",
    )
    query: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Поисковая строка по описанию или токену ссылки.",
    )
    sort_by: str = Field(
        default="created_at",
        min_length=1,
        max_length=64,
        description="Поле сортировки.",
        examples=["created_at", "expires_at", "download_count", "view_count", "status"],
    )
    sort_desc: bool = Field(
        default=True,
        description="Сортировать по убыванию.",
    )

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        """Нормализует поисковую строку.

        Args:
            value: Исходная поисковая строка.

        Returns:
            Поисковая строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("created_to")
    @classmethod
    def validate_created_range(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        """Проверяет корректность диапазона даты создания.

        Args:
            value: Значение верхней границы диапазона ``created_to``.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Значение ``created_to``, если диапазон корректен.

        Raises:
            ValueError: Если ``created_to`` меньше ``created_from``.
        """

        created_from = info.data.get("created_from")

        if created_from is not None and value is not None and value < created_from:
            raise ValueError("created_to не может быть раньше created_from.")

        return value

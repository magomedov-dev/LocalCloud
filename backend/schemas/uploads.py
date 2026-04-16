from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationInfo, computed_field, field_validator

from database.models.enums import UploadPartStatus, UploadSessionStatus
from schemas.common import BaseSchema, PaginationParams
from schemas.nodes import validate_node_name


class UploadSessionCreateRequest(BaseSchema):
    """Запрос на создание multipart upload-сессии.

    Используется для инициализации загрузки большого файла частями. Содержит
    сведения о папке назначения, имени файла, размере файла, количестве частей,
    MIME-типе и контрольной сумме.

    Attributes:
        parent_node_id: Идентификатор папки назначения, в которой будет создан
            загруженный файл.
        filename: Оригинальное имя загружаемого файла.
        file_size_bytes: Общий размер загружаемого файла в байтах.
        part_size_bytes: Желаемый размер одной части multipart upload в байтах.
            Если ``None``, размер выбирает сервисный слой.
        parts_count: Общее количество частей загрузки.
        mime_type: MIME-тип загружаемого файла.
        checksum: Контрольная сумма всего файла.
        checksum_algorithm: Алгоритм контрольной суммы.
    """

    parent_node_id: UUID = Field(
        ...,
        description="Идентификатор папки назначения, в которой будет создан загруженный файл.",
    )
    filename: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Оригинальное имя загружаемого файла.",
        examples=["document.pdf", "archive.zip", "photo.png"],
    )
    file_size_bytes: int = Field(
        ...,
        gt=0,
        description="Общий размер загружаемого файла в байтах.",
    )
    part_size_bytes: int | None = Field(
        default=None,
        gt=0,
        description="Желаемый размер одной части multipart upload в байтах. Если None, размер выбирает сервисный слой.",
    )
    parts_count: int = Field(
        ...,
        gt=0,
        description="Общее количество частей загрузки.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип загружаемого файла.",
        examples=["application/pdf", "image/png"],
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма всего файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы.",
        examples=["sha256", "md5"],
    )

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        """Проверяет имя загружаемого файла.

        Args:
            value: Исходное имя файла.

        Returns:
            Нормализованное и валидное имя файла.

        Raises:
            ValueError: Если имя файла не проходит правила валидации узла.
        """

        return validate_node_name(value)

    @field_validator("mime_type", "checksum", "checksum_algorithm")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Нормализует необязательные текстовые поля.

        Args:
            value: Исходное текстовое значение.

        Returns:
            Строка без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None

    @field_validator("checksum_algorithm")
    @classmethod
    def normalize_checksum_algorithm(cls, value: str | None) -> str | None:
        """Нормализует название алгоритма контрольной суммы.

        Args:
            value: Исходное название алгоритма.

        Returns:
            Название алгоритма без пробелов по краям в нижнем регистре или
            ``None``.
        """

        if value is None:
            return None

        normalized_value = value.strip().lower()
        return normalized_value or None


class UploadSessionRead(BaseSchema):
    """Полное публичное представление upload-сессии.

    Используется для возврата подробного состояния multipart upload-сессии:
    исходных параметров загрузки, прогресса, статуса, временных меток,
    диагностической информации и клиентского контекста.

    Attributes:
        id: Уникальный идентификатор upload-сессии.
        user_id: Идентификатор пользователя, инициировавшего загрузку.
        parent_node_id: Идентификатор папки назначения.
        file_name: Оригинальное имя загружаемого файла.
        file_size_bytes: Общий размер файла в байтах.
        part_size_bytes: Размер одной части multipart upload в байтах.
        mime_type: MIME-тип загружаемого файла.
        checksum: Контрольная сумма всего файла.
        checksum_algorithm: Алгоритм контрольной суммы.
        status: Текущий статус upload-сессии.
        parts_count: Общее количество частей загрузки.
        uploaded_parts_count: Количество успешно загруженных частей.
        uploaded_bytes: Количество байтов, подтверждённых как загруженные.
        expires_at: Дата и время истечения upload-сессии.
        completed_at: Дата и время завершения загрузки.
        aborted_at: Дата и время отмены загрузки.
        failed_at: Дата и время ошибки загрузки.
        failure_reason: Описание причины ошибки загрузки.
        client_ip: IP-адрес клиента, инициировавшего загрузку.
        user_agent: User-Agent клиента, инициировавшего загрузку.
        created_at: Дата и время создания upload-сессии.
        progress_percent: Процент загрузки файла.
        is_completed: Завершена ли upload-сессия.
        is_terminal: Является ли upload-сессия терминальной.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор upload-сессии.",
    )
    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, инициировавшего загрузку.",
    )
    parent_node_id: UUID = Field(
        ...,
        description="Идентификатор папки назначения.",
    )
    file_name: str = Field(
        ...,
        description="Оригинальное имя загружаемого файла.",
    )
    file_size_bytes: int = Field(
        ...,
        gt=0,
        description="Общий размер файла в байтах.",
    )
    part_size_bytes: int = Field(
        ...,
        gt=0,
        description="Размер одной части multipart upload в байтах.",
    )
    mime_type: str | None = Field(
        default=None,
        max_length=255,
        description="MIME-тип загружаемого файла.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма всего файла.",
    )
    checksum_algorithm: str | None = Field(
        default=None,
        max_length=32,
        description="Алгоритм контрольной суммы.",
    )
    status: UploadSessionStatus = Field(
        ...,
        description="Текущий статус upload-сессии.",
    )
    parts_count: int = Field(
        ...,
        gt=0,
        description="Общее количество частей загрузки.",
    )
    uploaded_parts_count: int = Field(
        ...,
        ge=0,
        description="Количество успешно загруженных частей.",
    )
    uploaded_bytes: int = Field(
        ...,
        ge=0,
        description="Количество байтов, подтверждённых как загруженные.",
    )
    expires_at: datetime = Field(
        ...,
        description="Дата и время истечения upload-сессии.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Дата и время завершения загрузки.",
    )
    aborted_at: datetime | None = Field(
        default=None,
        description="Дата и время отмены загрузки.",
    )
    failed_at: datetime | None = Field(
        default=None,
        description="Дата и время ошибки загрузки.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Описание причины ошибки загрузки.",
    )
    client_ip: str | None = Field(
        default=None,
        max_length=64,
        description="IP-адрес клиента, инициировавшего загрузку.",
    )
    user_agent: str | None = Field(
        default=None,
        description="User-Agent клиента, инициировавшего загрузку.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания upload-сессии.",
    )

    @computed_field(description="Процент загрузки файла.")
    @property
    def progress_percent(self) -> float:
        """Вычисляет процент загрузки файла.

        Returns:
            Процент загруженных байтов относительно общего размера файла,
            округлённый до двух знаков после запятой. Если размер файла
            некорректен, возвращает ``0.0``.
        """

        if self.file_size_bytes <= 0:
            return 0.0

        percent = self.uploaded_bytes / self.file_size_bytes * 100
        return round(min(percent, 100.0), 2)

    @computed_field(description="Завершена ли upload-сессия.")
    @property
    def is_completed(self) -> bool:
        """Проверяет, завершена ли upload-сессия.

        Returns:
            ``True``, если статус сессии равен ``COMPLETED``, иначе ``False``.
        """

        return self.status == UploadSessionStatus.COMPLETED

    @computed_field(description="Является ли upload-сессия терминальной.")
    @property
    def is_terminal(self) -> bool:
        """Проверяет, находится ли upload-сессия в терминальном статусе.

        Returns:
            ``True``, если сессия завершена, завершилась ошибкой, отменена или
            истекла, иначе ``False``.
        """

        return self.status in {
            UploadSessionStatus.COMPLETED,
            UploadSessionStatus.FAILED,
            UploadSessionStatus.ABORTED,
            UploadSessionStatus.EXPIRED,
        }


class UploadSessionListItem(BaseSchema):
    """Краткое представление upload-сессии для списков.

    Используется в списках upload-сессий, когда клиенту нужны основные
    параметры загрузки, статус, прогресс и ключевые временные метки.

    Attributes:
        id: Уникальный идентификатор upload-сессии.
        user_id: Идентификатор пользователя, инициировавшего загрузку.
        parent_node_id: Идентификатор папки назначения.
        file_name: Оригинальное имя загружаемого файла.
        file_size_bytes: Общий размер файла в байтах.
        status: Текущий статус upload-сессии.
        parts_count: Общее количество частей загрузки.
        uploaded_parts_count: Количество успешно загруженных частей.
        uploaded_bytes: Количество байтов, подтверждённых как загруженные.
        expires_at: Дата и время истечения upload-сессии.
        completed_at: Дата и время завершения загрузки.
        created_at: Дата и время создания upload-сессии.
        progress_percent: Процент загрузки файла.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор upload-сессии.",
    )
    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, инициировавшего загрузку.",
    )
    parent_node_id: UUID = Field(
        ...,
        description="Идентификатор папки назначения.",
    )
    file_name: str = Field(
        ...,
        description="Оригинальное имя загружаемого файла.",
    )
    file_size_bytes: int = Field(
        ...,
        gt=0,
        description="Общий размер файла в байтах.",
    )
    status: UploadSessionStatus = Field(
        ...,
        description="Текущий статус upload-сессии.",
    )
    parts_count: int = Field(
        ...,
        gt=0,
        description="Общее количество частей загрузки.",
    )
    uploaded_parts_count: int = Field(
        ...,
        ge=0,
        description="Количество успешно загруженных частей.",
    )
    uploaded_bytes: int = Field(
        ...,
        ge=0,
        description="Количество байтов, подтверждённых как загруженные.",
    )
    expires_at: datetime = Field(
        ...,
        description="Дата и время истечения upload-сессии.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Дата и время завершения загрузки.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания upload-сессии.",
    )

    @computed_field(description="Процент загрузки файла.")
    @property
    def progress_percent(self) -> float:
        """Вычисляет процент загрузки файла.

        Returns:
            Процент загруженных байтов относительно общего размера файла,
            округлённый до двух знаков после запятой. Если размер файла
            некорректен, возвращает ``0.0``.
        """

        if self.file_size_bytes <= 0:
            return 0.0

        percent = self.uploaded_bytes / self.file_size_bytes * 100
        return round(min(percent, 100.0), 2)


class UploadPartRead(BaseSchema):
    """Представление части multipart upload.

    Используется для отображения состояния отдельной части загрузки, включая
    размер, ETag, контрольную сумму, статус и временные метки успешной или
    неуспешной загрузки.

    Attributes:
        id: Уникальный идентификатор части загрузки.
        upload_session_id: Идентификатор upload-сессии, к которой относится
            часть.
        part_number: Номер части multipart upload.
        size_bytes: Размер части в байтах.
        etag: ETag, возвращённый MinIO/S3 после успешной загрузки части.
        checksum: Необязательная контрольная сумма части.
        status: Текущий статус части загрузки.
        uploaded_at: Дата и время успешной загрузки части.
        failed_at: Дата и время ошибки загрузки части.
        failure_reason: Описание причины ошибки загрузки части.
        created_at: Дата и время создания записи части загрузки.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор части загрузки.",
    )
    upload_session_id: UUID = Field(
        ...,
        description="Идентификатор upload-сессии, к которой относится часть.",
    )
    part_number: int = Field(
        ...,
        ge=1,
        description="Номер части multipart upload.",
    )
    size_bytes: int = Field(
        ...,
        gt=0,
        description="Размер части в байтах.",
    )
    etag: str | None = Field(
        default=None,
        max_length=512,
        description="ETag, возвращённый MinIO/S3 после успешной загрузки части.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Необязательная контрольная сумма части.",
    )
    status: UploadPartStatus = Field(
        ...,
        description="Текущий статус части загрузки.",
    )
    uploaded_at: datetime | None = Field(
        default=None,
        description="Дата и время успешной загрузки части.",
    )
    failed_at: datetime | None = Field(
        default=None,
        description="Дата и время ошибки загрузки части.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Описание причины ошибки загрузки части.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания записи части загрузки.",
    )


class UploadPartPresignedUrlRead(BaseSchema):
    """Pre-signed URL для загрузки одной части файла.

    Используется для передачи клиенту временной ссылки, HTTP-метода,
    заголовков и ожидаемого размера конкретной части multipart upload.

    Attributes:
        part_number: Номер части multipart upload.
        url: Предварительно подписанная ссылка для загрузки части.
        method: HTTP-метод для загрузки части.
        expires_at: Дата и время истечения срока действия ссылки.
        headers: HTTP-заголовки, которые нужно передать при загрузке части.
        size_bytes: Ожидаемый размер части в байтах, если известен.
    """

    part_number: int = Field(
        ...,
        ge=1,
        description="Номер части multipart upload.",
    )
    url: str = Field(
        ...,
        description="Предварительно подписанная ссылка для загрузки части.",
    )
    method: str = Field(
        default="PUT",
        description="HTTP-метод для загрузки части.",
        examples=["PUT"],
    )
    expires_at: datetime = Field(
        ...,
        description="Дата и время истечения срока действия ссылки.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP-заголовки, которые нужно передать при загрузке части.",
    )
    size_bytes: int | None = Field(
        default=None,
        gt=0,
        description="Ожидаемый размер части в байтах, если известен.",
    )

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        """Нормализует HTTP-метод загрузки части.

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


class UploadPresignedUrlsResponse(BaseSchema):
    """Ответ со списком pre-signed URL для загрузки частей файла.

    Используется после создания upload-сессии или запроса ссылок для частей.
    Содержит текущий статус сессии и набор ссылок для загрузки.

    Attributes:
        upload_session_id: Идентификатор upload-сессии.
        status: Текущий статус upload-сессии.
        parts: Список ссылок для загрузки частей.
        expires_at: Общая дата истечения ссылок, если она одинакова для всех
            частей.
    """

    upload_session_id: UUID = Field(
        ...,
        description="Идентификатор upload-сессии.",
    )
    status: UploadSessionStatus = Field(
        ...,
        description="Текущий статус upload-сессии.",
    )
    parts: list[UploadPartPresignedUrlRead] = Field(
        default_factory=list,
        description="Список ссылок для загрузки частей.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Общая дата истечения ссылок, если она одинакова для всех частей.",
    )


class UploadPartCompleteRequest(BaseSchema):
    """Запрос на подтверждение успешной загрузки одной части.

    Используется клиентом после загрузки части по pre-signed URL. Передаёт
    номер части, ETag, фактический размер и необязательную контрольную сумму.

    Attributes:
        part_number: Номер загруженной части multipart upload.
        etag: ETag, возвращённый MinIO/S3 после успешной загрузки части.
        size_bytes: Фактический размер загруженной части в байтах.
        checksum: Контрольная сумма части, если она вычислялась клиентом.
    """

    part_number: int = Field(
        ...,
        ge=1,
        description="Номер загруженной части multipart upload.",
    )
    etag: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="ETag, возвращённый MinIO/S3 после успешной загрузки части.",
    )
    size_bytes: int = Field(
        ...,
        gt=0,
        description="Фактический размер загруженной части в байтах.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Контрольная сумма части, если она вычислялась клиентом.",
    )

    @field_validator("etag")
    @classmethod
    def validate_etag(cls, value: str) -> str:
        """Проверяет и нормализует ETag загруженной части.

        Удаляет пробелы по краям и внешние двойные кавычки, если они были
        переданы клиентом.

        Args:
            value: Исходное значение ETag.

        Returns:
            Нормализованное значение ETag.

        Raises:
            ValueError: Если ETag пустой после нормализации.
        """

        normalized_value = value.strip().strip('"')

        if not normalized_value:
            raise ValueError("etag не должен быть пустым.")

        return normalized_value

    @field_validator("checksum")
    @classmethod
    def normalize_checksum(cls, value: str | None) -> str | None:
        """Нормализует контрольную сумму части.

        Args:
            value: Исходное значение контрольной суммы.

        Returns:
            Контрольная сумма без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class UploadCompleteRequest(BaseSchema):
    """Запрос на завершение multipart upload-сессии.

    Используется после успешной загрузки всех частей. Содержит идентификатор
    upload-сессии, список загруженных частей с ETag и необязательную итоговую
    контрольную сумму файла.

    Attributes:
        upload_session_id: Идентификатор upload-сессии, которую нужно
            завершить.
        parts: Список успешно загруженных частей с ETag.
        checksum: Итоговая контрольная сумма файла, если она вычислялась
            клиентом.
    """

    upload_session_id: UUID = Field(
        ...,
        description="Идентификатор upload-сессии, которую нужно завершить.",
    )
    parts: list[UploadPartCompleteRequest] = Field(
        ...,
        min_length=1,
        description="Список успешно загруженных частей с ETag.",
    )
    checksum: str | None = Field(
        default=None,
        max_length=128,
        description="Итоговая контрольная сумма файла, если она вычислялась клиентом.",
    )

    @field_validator("parts")
    @classmethod
    def validate_unique_part_numbers(
        cls,
        value: list[UploadPartCompleteRequest],
    ) -> list[UploadPartCompleteRequest]:
        """Проверяет уникальность номеров частей.

        Args:
            value: Список загруженных частей.

        Returns:
            Исходный список частей, если дубликаты ``part_number`` отсутствуют.

        Raises:
            ValueError: Если список содержит повторяющиеся ``part_number``.
        """

        part_numbers = [part.part_number for part in value]

        if len(part_numbers) != len(set(part_numbers)):
            raise ValueError(
                "Список частей не должен содержать дублирующиеся part_number."
            )

        return value

    @field_validator("checksum")
    @classmethod
    def normalize_checksum(cls, value: str | None) -> str | None:
        """Нормализует итоговую контрольную сумму файла.

        Args:
            value: Исходное значение контрольной суммы.

        Returns:
            Контрольная сумма без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class UploadCompleteResponse(BaseSchema):
    """Ответ после завершения multipart upload.

    Используется для возврата итогового состояния upload-сессии и
    идентификаторов созданного файла и узла файловой системы.

    Attributes:
        upload_session: Upload-сессия после завершения.
        file_id: Идентификатор созданного файла.
        node_id: Идентификатор созданного узла файловой системы.
        message: Сообщение о результате завершения загрузки.
    """

    upload_session: UploadSessionRead = Field(
        ...,
        description="Upload-сессия после завершения.",
    )
    file_id: UUID | None = Field(
        default=None,
        description="Идентификатор созданного файла.",
    )
    node_id: UUID | None = Field(
        default=None,
        description="Идентификатор созданного узла файловой системы.",
    )
    message: str = Field(
        default="Файл успешно загружен.",
        description="Сообщение о результате завершения загрузки.",
    )


class UploadAbortRequest(BaseSchema):
    """Запрос на отмену upload-сессии.

    Используется для прерывания multipart upload-сессии с необязательным
    указанием причины отмены.

    Attributes:
        upload_session_id: Идентификатор upload-сессии, которую нужно отменить.
        reason: Причина отмены upload-сессии.
    """

    upload_session_id: UUID = Field(
        ...,
        description="Идентификатор upload-сессии, которую нужно отменить.",
    )
    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Причина отмены upload-сессии.",
    )

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        """Нормализует причину отмены upload-сессии.

        Args:
            value: Исходная причина отмены.

        Returns:
            Причина отмены без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class UploadProgressRead(BaseSchema):
    """Состояние прогресса upload-сессии.

    Используется для компактного отображения текущего состояния загрузки:
    статуса, количества частей, загруженных байтов, срока действия и причины
    ошибки.

    Attributes:
        upload_session_id: Идентификатор upload-сессии.
        status: Текущий статус upload-сессии.
        file_size_bytes: Общий размер файла в байтах.
        parts_count: Общее количество частей загрузки.
        uploaded_parts_count: Количество успешно загруженных частей.
        uploaded_bytes: Количество байтов, подтверждённых как загруженные.
        expires_at: Дата и время истечения upload-сессии.
        completed_at: Дата и время завершения загрузки.
        failure_reason: Описание причины ошибки загрузки.
        progress_percent: Процент загрузки файла.
    """

    upload_session_id: UUID = Field(
        ...,
        description="Идентификатор upload-сессии.",
    )
    status: UploadSessionStatus = Field(
        ...,
        description="Текущий статус upload-сессии.",
    )
    file_size_bytes: int = Field(
        ...,
        gt=0,
        description="Общий размер файла в байтах.",
    )
    parts_count: int = Field(
        ...,
        gt=0,
        description="Общее количество частей загрузки.",
    )
    uploaded_parts_count: int = Field(
        ...,
        ge=0,
        description="Количество успешно загруженных частей.",
    )
    uploaded_bytes: int = Field(
        ...,
        ge=0,
        description="Количество байтов, подтверждённых как загруженные.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Дата и время истечения upload-сессии.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Дата и время завершения загрузки.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Описание причины ошибки загрузки.",
    )

    @computed_field(description="Процент загрузки файла.")
    @property
    def progress_percent(self) -> float:
        """Вычисляет процент загрузки файла.

        Returns:
            Процент загруженных байтов относительно общего размера файла,
            округлённый до двух знаков после запятой. Если размер файла
            некорректен, возвращает ``0.0``.
        """

        if self.file_size_bytes <= 0:
            return 0.0

        percent = self.uploaded_bytes / self.file_size_bytes * 100
        return round(min(percent, 100.0), 2)

    @field_validator("uploaded_parts_count")
    @classmethod
    def validate_uploaded_parts_count(
        cls,
        value: int,
        info: ValidationInfo,
    ) -> int:
        """Проверяет количество загруженных частей.

        Args:
            value: Количество успешно загруженных частей.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Количество загруженных частей, если оно корректно.

        Raises:
            ValueError: Если ``uploaded_parts_count`` больше ``parts_count``.
        """

        parts_count = info.data.get("parts_count")

        if isinstance(parts_count, int) and value > parts_count:
            raise ValueError("uploaded_parts_count не может превышать parts_count.")

        return value

    @field_validator("uploaded_bytes")
    @classmethod
    def validate_uploaded_bytes(
        cls,
        value: int,
        info: ValidationInfo,
    ) -> int:
        """Проверяет количество загруженных байтов.

        Args:
            value: Количество байтов, подтверждённых как загруженные.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Количество загруженных байтов, если оно корректно.

        Raises:
            ValueError: Если ``uploaded_bytes`` больше ``file_size_bytes``.
        """

        file_size_bytes = info.data.get("file_size_bytes")

        if isinstance(file_size_bytes, int) and value > file_size_bytes:
            raise ValueError("uploaded_bytes не может превышать file_size_bytes.")

        return value


class UploadQueryParams(PaginationParams):
    """Параметры фильтрации upload-сессий.

    Используется для постраничного получения upload-сессий с фильтрами по
    пользователю, папке назначения, статусу, имени файла, дате создания,
    сроку истечения и признаку включения терминальных сессий.

    Attributes:
        user_id: Фильтр по пользователю, инициировавшему загрузку.
        parent_node_id: Фильтр по папке назначения.
        status: Фильтр по статусу upload-сессии.
        filename: Фильтр или поиск по имени загружаемого файла.
        created_from: Фильтр по дате создания: начало диапазона включительно.
        created_to: Фильтр по дате создания: конец диапазона включительно.
        expires_before: Вернуть upload-сессии, истекающие не позднее
            указанного времени.
        include_terminal: Включать ли завершённые, отменённые, просроченные и
            ошибочные сессии.
        sort_by: Поле сортировки.
        sort_desc: Признак сортировки по убыванию.
    """

    user_id: UUID | None = Field(
        default=None,
        description="Фильтр по пользователю, инициировавшему загрузку.",
    )
    parent_node_id: UUID | None = Field(
        default=None,
        description="Фильтр по папке назначения.",
    )
    status: UploadSessionStatus | None = Field(
        default=None,
        description="Фильтр по статусу upload-сессии.",
    )
    filename: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Фильтр или поиск по имени загружаемого файла.",
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
        description="Вернуть upload-сессии, истекающие не позднее указанного времени.",
    )
    include_terminal: bool = Field(
        default=True,
        description="Включать ли завершённые, отменённые, просроченные и ошибочные сессии.",
    )
    sort_by: str = Field(
        default="created_at",
        min_length=1,
        max_length=64,
        description="Поле сортировки.",
        examples=["created_at", "expires_at", "file_name", "status"],
    )
    sort_desc: bool = Field(
        default=True,
        description="Сортировать по убыванию.",
    )

    @field_validator("filename")
    @classmethod
    def normalize_filename(cls, value: str | None) -> str | None:
        """Нормализует фильтр по имени файла.

        Args:
            value: Исходное значение имени файла.

        Returns:
            Имя файла без пробелов по краям или ``None``, если значение
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
        """Проверяет корректность диапазона даты создания upload-сессии.

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

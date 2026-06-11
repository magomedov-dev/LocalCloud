from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from core.config import Settings, get_settings
from core.logging import get_logger
from core.preview_mime import preview_required
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    BackgroundTaskStatus,
    BackgroundTaskType,
    FilePreviewStatus,
    FileProcessingStatus,
    NodeType,
    StorageObjectStatus,
    UploadPartStatus,
    UploadSessionStatus,
)
from database.models.filesystem import FileSystemNode
from database.models.uploads import UploadPart, UploadSession
from schemas.common import PageMeta, PageResponse
from schemas.uploads import (
    UploadAbortRequest,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadPartCompleteRequest,
    UploadPartPresignedUrlRead,
    UploadPartRead,
    UploadPresignedUrlsResponse,
    UploadProgressRead,
    UploadQueryParams,
    UploadSessionCreateRequest,
    UploadSessionListItem,
    UploadSessionRead,
)
from security.permissions import PermissionAction
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    ConflictServiceError,
    PermissionServiceError,
    ServiceError,
    UploadServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
    service_error_from_storage,
)
from storage import StorageError, StorageService, get_storage_service
from storage.keys import build_upload_temp_object_key
from storage.types import StoragePresignedUploadPartUrl

logger = get_logger("services.uploads")

SERVICE_NAME = "uploads"
REPOSITORY_PAGE_LIMIT = 1000
TERMINAL_UPLOAD_STATUSES = {
    UploadSessionStatus.COMPLETED,
    UploadSessionStatus.FAILED,
    UploadSessionStatus.ABORTED,
    UploadSessionStatus.EXPIRED,
}
ACTIVE_UPLOAD_STATUSES = {
    UploadSessionStatus.CREATED,
    UploadSessionStatus.UPLOADING,
}
ALLOWED_UPLOAD_SORT_FIELDS = {
    "created_at",
    "expires_at",
    "file_name",
    "status",
}


class UploadsService:
    """Сервис бизнес-логики для multipart-загрузок файлов.

    Управляет жизненным циклом multipart upload-сессии: создает сессию,
    инициализирует upload в хранилище, выдает URL для частей, подтверждает
    части, завершает загрузку, создает метаданные файла и отменяет активные
    upload-сессии. Также проверяет доступ, квоты и записывает события аудита.

    Attributes:
        settings: Настройки приложения.
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        storage_service: Сервис хранилища для multipart upload-операций.
        access_service: Сервис проверки доступа к узлам файловой системы.
        audit_service: Сервис записи событий аудита.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        uow_factory: UnitOfWorkFactory | None = None,
        storage_service: StorageService | None = None,
        access_service: AccessService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Инициализирует сервис загрузок.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            settings: Настройки приложения. Если None, используются стандартные
                настройки.
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            storage_service: Сервис хранилища. Если None, создается стандартный
                сервис хранилища.
            access_service: Сервис проверки доступа. Если None, создается
                стандартный сервис доступа.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
        """

        self.settings = settings or get_settings()
        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.storage_service = storage_service or get_storage_service(
            settings=self.settings.storage
        )
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )

    async def initiate_upload(
        self,
        data: UploadSessionCreateRequest,
        *,
        user_id: UUID,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[UploadSessionRead, UploadPresignedUrlsResponse]:
        """Создает upload-сессию и возвращает URL для загрузки частей.

        Проверяет размер частей, готовность хранилища, доступ пользователя к
        родительской папке, принадлежность папки пользователю и квоты. Затем
        инициализирует multipart upload в хранилище, создает запись upload-сессии
        и частей в базе, увеличивает счетчик активных upload-сессий, генерирует
        предварительно подписанные URL для всех частей и записывает события аудита.

        Args:
            data: Данные для создания upload-сессии.
            user_id: Идентификатор пользователя, создающего загрузку.
            client_ip: IP-адрес клиента. Если пустой после нормализации, сохраняется
                как None.
            user_agent: User-Agent клиента. Если пустой после нормализации,
                сохраняется как None.

        Returns:
            Кортеж из данных upload-сессии и ответа с предварительно подписанными
            URL для загрузки частей.

        Raises:
            PermissionServiceError: Если пользователь не имеет права записи в папку
                или пытается загрузить файл в папку другого владельца.
            ValidationServiceError: Если родительский узел не является папкой,
                размер файла или количество частей некорректны.
            UploadServiceError: Если загрузка превышает квоты пользователя.
            StorageError: Если хранилище не готово или не удалось инициализировать
                multipart upload.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "initiate_upload"
        part_sizes = _build_part_sizes(
            file_size_bytes=data.file_size_bytes,
            part_size_bytes=data.part_size_bytes,
            parts_count=data.parts_count,
            default_part_size_bytes=self.storage_service.multipart_part_size_bytes,
        )
        object_key = build_upload_temp_object_key(
            user_id=user_id,
            upload_session_id=uuid4(),
        )
        bucket = self.storage_service.default_files_bucket
        multipart_upload = None
        session_snapshot: dict[str, Any] | None = None
        urls_response: UploadPresignedUrlsResponse | None = None

        try:
            await self.storage_service.ensure_storage_ready(
                bucket=bucket,
                create_bucket=True,
            )

            async with self.uow_factory() as uow:
                parent = await self.access_service.get_accessible_node(
                    node_id=data.parent_node_id,
                    user_id=user_id,
                    action=PermissionAction.WRITE,
                    uow=uow,
                )
                _ensure_folder_node(parent, operation=operation)
                if parent.owner_id != user_id:
                    raise PermissionServiceError(
                        "Загрузка в папку другого пользователя запрещена.",
                        user_id=user_id,
                        resource_type="folder",
                        resource_id=parent.id,
                        action=PermissionAction.WRITE,
                        reason="owner_mismatch",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                await _ensure_upload_quota(uow, user_id=user_id, data=data)

                multipart_upload = await self.storage_service.init_multipart_upload(
                    bucket=bucket,
                    object_key=object_key,
                    user_id=user_id,
                    content_type=data.mime_type,
                    checksum=data.checksum,
                    checksum_algorithm=data.checksum_algorithm,
                    original_filename=data.filename,
                    created_by=user_id,
                    metadata={
                        "upload_parent_node_id": str(data.parent_node_id),
                        "upload_parts_count": str(data.parts_count),
                    },
                )
                expires_at = multipart_upload.expires_at or (
                    datetime.now(UTC)
                    + timedelta(
                        seconds=self.storage_service.presigned_upload_expire_seconds
                    )
                )

                upload_session = await uow.upload_sessions.create_session(
                    user_id=user_id,
                    parent_node_id=data.parent_node_id,
                    file_name=data.filename,
                    file_size_bytes=data.file_size_bytes,
                    part_size_bytes=part_sizes[0],
                    storage_bucket=multipart_upload.bucket,
                    storage_key=multipart_upload.object_key,
                    upload_id=multipart_upload.upload_id,
                    parts_count=len(part_sizes),
                    expires_at=expires_at,
                    mime_type=data.mime_type,
                    checksum=data.checksum,
                    checksum_algorithm=data.checksum_algorithm,
                    client_ip=_normalize_optional_text(client_ip),
                    user_agent=_normalize_optional_text(user_agent),
                    flush=True,
                    refresh=True,
                )
                await uow.upload_parts.create_parts_by_sizes(
                    upload_session.id,
                    part_sizes,
                    flush=True,
                    check_session_exists=False,
                )
                # Синхронизировать кэшированный счетчик с реальным количеством активных сеансов
                # (только что созданный сеанс уже сброшен, поэтому онвключен в
                # ). Это автоматически устраняет любые исторические отклонения вместо
                # blind +1, которые могут превысить допустимый предел и привести к сбою.
                actual_active_sessions = (
                    await uow.quotas.count_user_active_upload_sessions(
                        user_id=user_id,
                        exclude_time_expired=True,
                    )
                )
                await uow.quotas.set_active_upload_sessions_used(
                    user_id=user_id,
                    count=actual_active_sessions,
                    flush=True,
                    refresh=False,
                )

                presigned_urls = await self.storage_service.create_upload_part_urls(
                    bucket=upload_session.storage_bucket,
                    object_key=upload_session.storage_key,
                    upload_id=upload_session.upload_id,
                    part_numbers=list(range(1, upload_session.parts_count + 1)),
                )
                urls_response = _presigned_urls_response(
                    upload_session,
                    presigned_urls,
                    part_sizes=part_sizes,
                )
                session_snapshot = _session_snapshot(upload_session)
                await uow.commit()

            if session_snapshot is None or urls_response is None:
                raise _empty_result_error(operation)

            await self._safe_log_upload_event(
                user_id=user_id,
                action=AuditAction.UPLOAD_SESSION_CREATED,
                snapshot=session_snapshot,
                message="Создан сеанс загрузки нескольких частей.",
            )
            await self._safe_log_upload_event(
                user_id=user_id,
                action=AuditAction.FILE_UPLOAD_STARTED,
                snapshot=session_snapshot,
                resource_type=AuditResourceType.FILE,
                message="Начата загрузка составного файла.",
            )
            return UploadSessionRead.model_validate(session_snapshot), urls_response

        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось инициализировать загрузку нескольких частей в хранилище объектов.",
            ) from exc
        except DatabaseError as exc:
            await self._abort_storage_upload_safely(multipart_upload)
            raise service_error_from_database(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать сеанс загрузки.",
            ) from exc
        except ServiceError:
            await self._abort_storage_upload_safely(multipart_upload)
            raise
        except Exception as exc:
            await self._abort_storage_upload_safely(multipart_upload)
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Непредвиденная ошибка при запуске загрузки нескольких частей.",
            ) from exc

    async def get_upload_session(
        self,
        upload_session_id: UUID,
        *,
        user_id: UUID,
    ) -> UploadSessionRead:
        """Возвращает upload-сессию пользователя.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            user_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Данные upload-сессии.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            ServiceError: Если сессия не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_upload_session"
        result: UploadSessionRead | None = None
        try:
            async with self.uow_factory() as uow:
                upload_session = await self._get_owned_session(
                    uow,
                    upload_session_id=upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )
                result = UploadSessionRead.model_validate(
                    _session_snapshot(upload_session)
                )
            if result is None:
                raise _empty_result_error(operation)
            return result
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить сеанс загрузки.",
            ) from exc

    async def list_uploads(
        self,
        params: UploadQueryParams,
        *,
        user_id: UUID,
    ) -> PageResponse[UploadSessionListItem]:
        """Возвращает список upload-сессий пользователя.

        Проверяет параметры пагинации и запрещает пользователю просматривать чужие
        upload-сессии. Если указан parent_node_id, дополнительно проверяет право
        чтения к родительскому узлу.

        Args:
            params: Параметры фильтрации, сортировки и пагинации upload-сессий.
            user_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Страница upload-сессий и метаданные пагинации.

        Raises:
            PermissionServiceError: Если пользователь пытается получить чужие
                upload-сессии или не имеет доступа к parent_node_id.
            ValidationServiceError: Если параметры пагинации или поле сортировки
                некорректны.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_uploads"
        _validate_pagination(limit=params.limit, offset=params.offset)
        requested_user_id = params.user_id or user_id
        result: PageResponse[UploadSessionListItem] | None = None
        if requested_user_id != user_id:
            raise PermissionServiceError(
                "Пользователи могут указывать только свои собственные сеансы загрузки.",
                user_id=user_id,
                resource_type="upload_session",
                action=PermissionAction.READ,
                reason="not_owner",
                details={"service": SERVICE_NAME, "operation": operation},
            )

        try:
            async with self.uow_factory() as uow:
                if params.parent_node_id is not None:
                    await self.access_service.require_access(
                        node_id=params.parent_node_id,
                        user_id=user_id,
                        action=PermissionAction.READ,
                        uow=uow,
                    )
                total = await _count_uploads(uow, params=params, user_id=user_id)
                uploads = await _select_uploads(uow, params=params, user_id=user_id)
                result = PageResponse(
                    items=[
                        UploadSessionListItem.model_validate(_session_snapshot(item))
                        for item in uploads
                    ],
                    meta=PageMeta(
                        limit=params.limit,
                        offset=params.offset,
                        total=total,
                        count=len(uploads),
                    ),
                )
            if result is None:
                raise _empty_result_error(operation)
            return result
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось отобразить список сеансов загрузки.",
            ) from exc

    async def get_upload_parts(
        self,
        upload_session_id: UUID,
        *,
        user_id: UUID,
    ) -> list[UploadPartRead]:
        """Возвращает части upload-сессии пользователя.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            user_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Список частей upload-сессии.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            ServiceError: Если сессия не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_upload_parts"
        result: list[UploadPartRead] | None = None
        try:
            async with self.uow_factory() as uow:
                await self._get_owned_session(
                    uow,
                    upload_session_id=upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )
                parts = await uow.upload_parts.get_session_parts(
                    upload_session_id,
                    limit=REPOSITORY_PAGE_LIMIT,
                )
                result = [UploadPartRead.model_validate(part) for part in parts]
            if result is None:
                raise _empty_result_error(operation)
            return result
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить загружаемые части.",
            ) from exc

    async def create_part_urls(
        self,
        upload_session_id: UUID,
        *,
        user_id: UUID,
        part_numbers: Sequence[int] | None = None,
    ) -> UploadPresignedUrlsResponse:
        """Создает новые URL для загрузки частей файла.

        Проверяет принадлежность upload-сессии пользователю, что сессия активна и не
        истекла, выбирает запрошенные части или все еще не загруженные части. Если
        сессия находится в статусе CREATED, переводит ее в UPLOADING.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            user_id: Идентификатор пользователя, выполняющего запрос.
            part_numbers: Номера частей, для которых нужно создать URL. Если None,
                URL создаются для всех частей, которые еще не загружены.

        Returns:
            Ответ с предварительно подписанными URL для выбранных частей.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            UploadServiceError: Если сессия не может принимать части или истекла.
            ValidationServiceError: Если запрошен неизвестный номер части.
            StorageError: Если не удалось создать URL в хранилище.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_part_urls"
        result: UploadPresignedUrlsResponse | None = None
        try:
            async with self.uow_factory() as uow:
                upload_session = await self._get_owned_session(
                    uow,
                    upload_session_id=upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )
                _ensure_can_receive_parts(upload_session, operation=operation)
                parts = await uow.upload_parts.get_session_parts(
                    upload_session_id,
                    limit=REPOSITORY_PAGE_LIMIT,
                )
                selected_parts = _select_parts_for_urls(parts, part_numbers)
                if upload_session.status == UploadSessionStatus.CREATED:
                    upload_session = await uow.upload_sessions.mark_uploading(
                        upload_session.id,
                        flush=True,
                        refresh=True,
                    )
                urls = await self.storage_service.create_upload_part_urls(
                    bucket=upload_session.storage_bucket,
                    object_key=upload_session.storage_key,
                    upload_id=upload_session.upload_id,
                    part_numbers=[part.part_number for part in selected_parts],
                )
                response = _presigned_urls_response(
                    upload_session,
                    urls,
                    part_sizes=[part.size_bytes for part in selected_parts],
                )
                await uow.commit()
                result = response
            if result is None:
                raise _empty_result_error(operation)
            return result
        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать предварительно подписанные URL-адреса частей загрузки.",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось создать предварительно подписанные URL-адреса частей загрузки.",
            ) from exc

    async def confirm_part(
        self,
        upload_session_id: UUID,
        data: UploadPartCompleteRequest,
        *,
        user_id: UUID,
    ) -> UploadProgressRead:
        """Подтверждает успешную загрузку одной части.

        Проверяет принадлежность сессии пользователю, активность сессии, размер
        части и затем помечает часть как загруженную. При необходимости переводит
        сессию в UPLOADING и пересчитывает прогресс по частям.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            data: Данные загруженной части.
            user_id: Идентификатор пользователя, выполняющего подтверждение.

        Returns:
            Текущий прогресс upload-сессии.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            UploadServiceError: Если сессия не может принимать части или истекла.
            ValidationServiceError: Если размер части не совпадает с метаданными
                сессии.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "confirm_part"
        result: UploadProgressRead | None = None
        try:
            async with self.uow_factory() as uow:
                upload_session = await self._get_owned_session(
                    uow,
                    upload_session_id=upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )
                _ensure_can_receive_parts(upload_session, operation=operation)
                part = await uow.upload_parts.get_required_by_session_and_part_number(
                    upload_session_id,
                    data.part_number,
                )
                _ensure_part_size_matches(part, data, operation=operation)
                await uow.upload_parts.mark_part_uploaded(
                    upload_session_id,
                    data.part_number,
                    etag=data.etag,
                    checksum=data.checksum,
                    flush=True,
                    refresh=False,
                )
                if upload_session.status == UploadSessionStatus.CREATED:
                    await uow.upload_sessions.mark_uploading(
                        upload_session.id,
                        flush=True,
                        refresh=False,
                    )
                upload_session = (
                    await uow.upload_sessions.recalculate_progress_from_parts(
                        upload_session.id,
                        flush=True,
                        refresh=True,
                    )
                )
                snapshot = _session_snapshot(upload_session)
                await uow.commit()
                result = _upload_progress_read(snapshot)
            if result is None:
                raise _empty_result_error(operation)
            return result
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось подтвердить загруженную часть.",
            ) from exc

    async def complete_upload(
        self,
        data: UploadCompleteRequest,
        *,
        user_id: UUID,
    ) -> UploadCompleteResponse:
        """Завершает multipart upload и создает метаданные файла.

        Проверяет upload-сессию, подтверждает все части, завершает multipart upload
        в хранилище, создает файл вместе с узлом файловой системы, создает первую
        версию файла, помечает upload-сессию завершенной и обновляет счетчики квоты:
        объем хранилища, количество файлов и активные upload-сессии.

        Args:
            data: Данные завершения upload-сессии.
            user_id: Идентификатор пользователя, завершающего загрузку.

        Returns:
            Ответ с завершенной upload-сессией, идентификатором созданного файла,
            идентификатором узла и сообщением.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            UploadServiceError: Если сессия не может быть завершена или истекла.
            ValidationServiceError: Если список частей неполный, содержит дубликаты,
                неверные номера или несоответствие размеров.
            ConflictServiceError: Если в запросе завершения есть дубликат части.
            StorageError: Если не удалось завершить multipart upload в хранилище.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "complete_upload"
        session_snapshot: dict[str, Any] | None = None
        file_id: UUID | None = None
        node_id: UUID | None = None

        try:
            async with self.uow_factory() as uow:
                upload_session = await self._get_owned_session(
                    uow,
                    upload_session_id=data.upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )

                # Идемпотентность: повторный вызов (например, ретрай после
                # потерянного ответа) на уже завершённой сессии возвращает тот
                # же результат, а не ошибку «нельзя завершить». Иначе клиент
                # видел бы 4xx при успешной первой попытке, а двойное создание
                # файла/инкремент квоты было бы недопустимо.
                if upload_session.status == UploadSessionStatus.COMPLETED:
                    existing = await self._build_completed_idempotent_response(
                        uow, upload_session=upload_session
                    )
                    if existing is not None:
                        return existing

                _ensure_can_complete(upload_session, operation=operation)
                parts_by_number = await self._confirm_completion_parts(
                    uow,
                    upload_session=upload_session,
                    parts=data.parts,
                    operation=operation,
                )

                await self.storage_service.complete_multipart_upload(
                    bucket=upload_session.storage_bucket,
                    object_key=upload_session.storage_key,
                    upload_id=upload_session.upload_id,
                    parts=[
                        {"part_number": part.part_number, "etag": part.etag}
                        for part in parts_by_number
                    ],
                )

                extension = _filename_extension(upload_session.file_name)
                _needs_preview = preview_required(upload_session.mime_type)
                file = await uow.files.create_file_with_node(
                    owner_id=upload_session.user_id,
                    parent_id=upload_session.parent_node_id,
                    name=upload_session.file_name,
                    storage_bucket=upload_session.storage_bucket,
                    storage_key=upload_session.storage_key,
                    size_bytes=upload_session.file_size_bytes,
                    mime_type=upload_session.mime_type,
                    extension=extension,
                    checksum=data.checksum or upload_session.checksum,
                    checksum_algorithm=upload_session.checksum_algorithm,
                    storage_status=StorageObjectStatus.AVAILABLE,
                    processing_status=FileProcessingStatus.READY,
                    preview_status=(
                        FilePreviewStatus.PENDING
                        if _needs_preview
                        else FilePreviewStatus.NOT_REQUIRED
                    ),
                    created_by=user_id,
                    check_owner_exists=False,
                    check_conflict=True,
                    flush=True,
                    refresh=True,
                )
                if _needs_preview:
                    preview_task = await uow.tasks.create_task(
                        task_type=BackgroundTaskType.GENERATE_FILE_PREVIEW,
                        created_by=user_id,
                        related_entity_type="file",
                        related_entity_id=file.id,
                        status=BackgroundTaskStatus.PENDING,
                        flush=True,
                        refresh=False,
                    )
                    preview_task.payload = {"file_id": str(file.id)}

                upload_session = await uow.upload_sessions.mark_completed(
                    upload_session.id,
                    require_all_parts=True,
                    flush=True,
                    refresh=True,
                )
                await uow.quotas.increase_used_space(
                    user_id=upload_session.user_id,
                    size_bytes=upload_session.file_size_bytes,
                    flush=True,
                    refresh=False,
                )
                await uow.quotas.increase_files_used(
                    user_id=upload_session.user_id,
                    count=1,
                    flush=True,
                    refresh=False,
                )
                await uow.quotas.decrease_active_upload_sessions_used(
                    user_id=upload_session.user_id,
                    count=1,
                    flush=True,
                    refresh=False,
                )
                session_snapshot = _session_snapshot(upload_session)
                file_id = file.id
                node_id = file.node_id
                await uow.commit()

            if session_snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_upload_event(
                user_id=user_id,
                action=AuditAction.UPLOAD_SESSION_COMPLETED,
                snapshot=session_snapshot,
                message="Сеанс загрузки нескольких частей завершен.",
                metadata={"file_id": _jsonable(file_id), "node_id": _jsonable(node_id)},
            )
            await self._safe_log_upload_event(
                user_id=user_id,
                action=AuditAction.FILE_UPLOADED,
                snapshot=session_snapshot,
                resource_type=AuditResourceType.FILE,
                entity_id=file_id,
                message="Файл был загружен через multipart-загрузку.",
                metadata={"node_id": _jsonable(node_id)},
            )
            return UploadCompleteResponse(
                upload_session=UploadSessionRead.model_validate(session_snapshot),
                file_id=file_id,
                node_id=node_id,
                message="Загрузка завершена успешно.",
            )
        except StorageError as exc:
            await self._mark_failed_safely(
                data.upload_session_id,
                reason=str(exc),
                user_id=user_id,
            )
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось завершить составную загрузку в хранилище объектов.",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось завершить загрузку нескольких частей.",
            ) from exc

    async def abort_upload(
        self,
        data: UploadAbortRequest,
        *,
        user_id: UUID,
    ) -> UploadSessionRead:
        """Отменяет активную multipart-загрузку.

        Если сессия уже находится в терминальном статусе, возвращает ее текущее
        состояние. Иначе отменяет multipart upload в хранилище, помечает сессию
        как ABORTED, уменьшает счетчик активных upload-сессий и записывает событие
        аудита.

        Args:
            data: Данные отмены upload-сессии.
            user_id: Идентификатор пользователя, выполняющего отмену.

        Returns:
            Данные upload-сессии после отмены.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            StorageError: Если не удалось отменить multipart upload в хранилище.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "abort_upload"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                upload_session = await self._get_owned_session(
                    uow,
                    upload_session_id=data.upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )
                if upload_session.status in TERMINAL_UPLOAD_STATUSES:
                    snapshot = _session_snapshot(upload_session)
                else:
                    await self.storage_service.abort_multipart_upload(
                        bucket=upload_session.storage_bucket,
                        object_key=upload_session.storage_key,
                        upload_id=upload_session.upload_id,
                        missing_ok=True,
                    )
                    upload_session = await uow.upload_sessions.mark_aborted(
                        upload_session.id,
                        flush=True,
                        refresh=True,
                    )
                    await uow.quotas.decrease_active_upload_sessions_used(
                        user_id=upload_session.user_id,
                        count=1,
                        flush=True,
                        refresh=False,
                    )
                    snapshot = _session_snapshot(upload_session)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_upload_event(
                user_id=user_id,
                action=AuditAction.UPLOAD_SESSION_ABORTED,
                snapshot=snapshot,
                message=data.reason or "Сеанс загрузки нескольких частей был прерван.",
            )
            return UploadSessionRead.model_validate(snapshot)
        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось прервать загрузку нескольких частей в хранилище объектов.",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось прервать сеанс загрузки.",
            ) from exc

    async def get_progress(
        self,
        upload_session_id: UUID,
        *,
        user_id: UUID,
    ) -> UploadProgressRead:
        """Возвращает прогресс upload-сессии.

        Используется polling-клиентами для отслеживания количества загруженных
        частей, байтов и статуса сессии.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            user_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Текущий прогресс upload-сессии.

        Raises:
            PermissionServiceError: Если upload-сессия принадлежит другому
                пользователю.
            ServiceError: Если сессия не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_progress"
        result: UploadProgressRead | None = None
        try:
            async with self.uow_factory() as uow:
                upload_session = await self._get_owned_session(
                    uow,
                    upload_session_id=upload_session_id,
                    user_id=user_id,
                    operation=operation,
                )
                result = _upload_progress_read(_session_snapshot(upload_session))
            if result is None:
                raise _empty_result_error(operation)
            return result
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось загрузить ход загрузки.",
            ) from exc

    async def _build_completed_idempotent_response(
        self,
        uow: Any,
        *,
        upload_session: UploadSession,
    ) -> UploadCompleteResponse | None:
        """Формирует ответ для повторного завершения уже завершённой сессии.

        Находит файл, ранее созданный для этой сессии (по bucket/key объекта),
        и возвращает тот же ответ, что и при первом успешном завершении —
        ничего не создавая и не меняя квоту. Если файл найти не удалось
        (например, он был удалён), возвращает ``None`` — вызывающий код пойдёт
        обычным путём проверки статуса.

        Args:
            uow: Активный Unit of Work.
            upload_session: Уже завершённая upload-сессия.

        Returns:
            Идемпотентный ответ завершения или ``None``, если исходный файл
            не найден.
        """

        file = await uow.files.get_by_storage_key(
            storage_bucket=upload_session.storage_bucket,
            storage_key=upload_session.storage_key,
        )
        if file is None:
            return None

        snapshot = _session_snapshot(upload_session)
        return UploadCompleteResponse(
            upload_session=UploadSessionRead.model_validate(snapshot),
            file_id=file.id,
            node_id=file.node_id,
            message="Загрузка уже была завершена.",
        )

    async def _get_owned_session(
        self,
        uow: Any,
        *,
        upload_session_id: UUID,
        user_id: UUID,
        operation: str,
    ) -> UploadSession:
        """Возвращает upload-сессию, принадлежащую пользователю.

        Args:
            uow: Unit of Work с репозиторием upload-сессий.
            upload_session_id: Идентификатор upload-сессии.
            user_id: Идентификатор пользователя, которому должна принадлежать
                сессия.
            operation: Название операции для контекста ошибок.

        Returns:
            ORM-модель upload-сессии.

        Raises:
            PermissionServiceError: Если сессия принадлежит другому пользователю.
        """

        upload_session = await uow.upload_sessions.get_required_session_by_id(
            upload_session_id
        )
        if upload_session.user_id == user_id:
            return upload_session
        raise PermissionServiceError(
            "Сеанс загрузки принадлежит другому пользователю.",
            user_id=user_id,
            resource_type="upload_session",
            resource_id=upload_session_id,
            action=PermissionAction.READ,
            reason="not_owner",
            details={"service": SERVICE_NAME, "operation": operation},
        )

    async def _confirm_completion_parts(
        self,
        uow: Any,
        *,
        upload_session: UploadSession,
        parts: Sequence[UploadPartCompleteRequest],
        operation: str,
    ) -> list[UploadPart]:
        """Подтверждает все части перед завершением upload-сессии.

        Проверяет, что запрос содержит все части, что номера частей не повторяются,
        что каждая часть существует и имеет ожидаемый размер. Если часть еще не
        помечена как загруженная или ее ETag отличается, обновляет запись части.
        После обработки пересчитывает прогресс сессии.

        Args:
            uow: Unit of Work с репозиторием upload-частей.
            upload_session: Upload-сессия, которую нужно завершить.
            parts: Части, переданные в запросе завершения.
            operation: Название операции для контекста ошибок.

        Returns:
            Список подтвержденных частей, отсортированный по номеру.

        Raises:
            ValidationServiceError: Если количество частей неверное, номера частей
                неполные или выходят за ожидаемый диапазон, либо размер части не
                совпадает с метаданными.
            ConflictServiceError: Если номер части повторяется в запросе.
        """

        if len(parts) != upload_session.parts_count:
            raise ValidationServiceError(
                "Запрос на завершение должен включать все загружаемые части.",
                field="parts",
                value=len(parts),
                reason="invalid_parts_count",
                details={
                    "service": SERVICE_NAME,
                    "operation": operation,
                    "expected_parts_count": upload_session.parts_count,
                },
            )

        # Заранее загружаем все части сессии (постранично, ≤1000 за запрос),
        # чтобы не делать отдельный SELECT на каждую часть (N+1) при завершении.
        parts_by_number: dict[int, UploadPart] = {}
        offset = 0
        while True:
            chunk = await uow.upload_parts.get_session_parts(
                upload_session.id, offset=offset, limit=REPOSITORY_PAGE_LIMIT
            )
            for existing in chunk:
                parts_by_number[existing.part_number] = existing
            if len(chunk) < REPOSITORY_PAGE_LIMIT:
                break
            offset += REPOSITORY_PAGE_LIMIT

        seen: set[int] = set()
        completed_parts: list[UploadPart] = []
        for item in sorted(parts, key=lambda part: part.part_number):
            if item.part_number in seen:
                raise ConflictServiceError(
                    "В запросе завершения загрузки указана дублирующаяся часть.",
                    entity_name="UploadPart",
                    entity_id=upload_session.id,
                    field="part_number",
                    value=item.part_number,
                    reason="duplicate_part_number",
                    details={"service": SERVICE_NAME, "operation": operation},
                )
            seen.add(item.part_number)
            part = parts_by_number.get(item.part_number)
            if part is None:
                # Защитный фолбэк: части не оказалось в предзагрузке.
                part = await uow.upload_parts.get_required_by_session_and_part_number(
                    upload_session.id,
                    item.part_number,
                )
            _ensure_part_size_matches(part, item, operation=operation)
            if part.status != UploadPartStatus.UPLOADED or part.etag != item.etag:
                part = await uow.upload_parts.mark_part_uploaded(
                    upload_session.id,
                    item.part_number,
                    etag=item.etag,
                    checksum=item.checksum,
                    flush=True,
                    refresh=True,
                )
            completed_parts.append(part)

        expected_numbers = set(range(1, upload_session.parts_count + 1))
        if seen != expected_numbers:
            raise ValidationServiceError(
                "В запросе на завершение отсутствуют номера деталей или они находятся за пределами допустимого диапазона.",
                field="parts",
                value=sorted(seen),
                reason="invalid_part_numbers",
                details={
                    "service": SERVICE_NAME,
                    "operation": operation,
                    "expected_part_numbers": sorted(expected_numbers),
                },
            )
        await uow.upload_sessions.recalculate_progress_from_parts(
            upload_session.id,
            flush=True,
            refresh=True,
        )
        return completed_parts

    async def _abort_storage_upload_safely(self, multipart_upload: Any | None) -> None:
        """Безопасно отменяет orphaned multipart upload в хранилище.

        Используется при ошибках создания upload-сессии после инициализации
        multipart upload. Ошибки отмены не пробрасываются выше и только логируются.

        Args:
            multipart_upload: Объект multipart upload из StorageService или None.
        """

        if multipart_upload is None:
            return
        try:
            await self.storage_service.abort_multipart_upload(
                bucket=multipart_upload.bucket,
                object_key=multipart_upload.object_key,
                upload_id=multipart_upload.upload_id,
                missing_ok=True,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось прервать потерянную многопользовательскую загрузку.",
                extra={
                    "service": SERVICE_NAME,
                    "bucket": getattr(multipart_upload, "bucket", None),
                    "object_key": getattr(multipart_upload, "object_key", None),
                    "upload_id": getattr(multipart_upload, "upload_id", None),
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )

    async def _mark_failed_safely(
        self,
        upload_session_id: UUID,
        *,
        reason: str,
        user_id: UUID,
    ) -> None:
        """Безопасно помечает upload-сессию как failed.

        Используется при ошибках завершения multipart upload. Если сессия отсутствует
        или уже находится в терминальном статусе, метод ничего не делает. Ошибки
        обновления статуса не пробрасываются выше и только логируются.

        Args:
            upload_session_id: Идентификатор upload-сессии.
            reason: Причина перевода сессии в failed.
            user_id: Идентификатор пользователя для события аудита.
        """

        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                upload_session = await uow.upload_sessions.get_session_by_id(
                    upload_session_id
                )
                if (
                    upload_session is None
                    or upload_session.status in TERMINAL_UPLOAD_STATUSES
                ):
                    return
                upload_session = await uow.upload_sessions.mark_failed(
                    upload_session_id,
                    reason=reason,
                    flush=True,
                    refresh=True,
                )
                await uow.quotas.decrease_active_upload_sessions_used(
                    user_id=upload_session.user_id,
                    count=1,
                    flush=True,
                    refresh=False,
                )
                snapshot = _session_snapshot(upload_session)
                await uow.commit()
            if snapshot is None:
                return
            await self._safe_log_upload_event(
                user_id=user_id,
                action=AuditAction.UPLOAD_SESSION_FAILED,
                snapshot=snapshot,
                message=reason,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось пометить сеанс загрузки как неудачный.",
                extra={
                    "service": SERVICE_NAME,
                    "operation": "mark_failed_safely",
                    "upload_session_id": str(upload_session_id),
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )

    async def _safe_log_upload_event(
        self,
        *,
        user_id: UUID | None,
        action: AuditAction,
        snapshot: Mapping[str, Any],
        message: str,
        resource_type: AuditResourceType = AuditResourceType.UPLOAD_SESSION,
        entity_id: UUID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие upload-сессии в аудит.

        Ошибки аудита не пробрасываются выше, чтобы не ломать основную upload-
        операцию. В metadata добавляются данные upload-сессии и дополнительные
        поля, если они переданы.

        Args:
            user_id: Идентификатор пользователя, связанного с событием.
            action: Действие аудита.
            snapshot: Снимок upload-сессии.
            message: Сообщение события аудита.
            resource_type: Тип ресурса аудита.
            entity_id: Идентификатор сущности для аудита. Если None, используется
                id upload-сессии из snapshot.
            metadata: Дополнительные метаданные события.
        """

        try:
            await self.audit_service.log_success(
                action=action,
                user_id=user_id,
                entity_type=resource_type.value,
                entity_id=entity_id or _optional_uuid(snapshot.get("id")),
                resource_type=resource_type,
                message=message,
                metadata={
                    "upload_session": _audit_upload(snapshot),
                    **(dict(metadata) if metadata else {}),
                },
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита для службы загрузки.",
                extra={
                    "service": SERVICE_NAME,
                    "action": action.value,
                    "upload_session_id": str(snapshot.get("id")),
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )

    def _database_error(self, exc: DatabaseError, *, operation: str) -> ServiceError:
        """Преобразует ошибку базы данных в ошибку сервиса загрузок.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции, во время которой возникла ошибка.

        Returns:
            Ошибка сервисного уровня с контекстом сервиса загрузок.
        """

        return service_error_from_database(
            exc,
            service=SERVICE_NAME,
            operation=operation,
            message="Сбой работы с базой данных в службе загрузки.",
        )

    def _unexpected_error(
        self,
        exc: Exception,
        *,
        operation: str,
        message: str,
    ) -> ServiceError:
        """Преобразует непредвиденное исключение в ошибку сервиса.

        Args:
            exc: Исходное исключение.
            operation: Название операции, во время которой возникла ошибка.
            message: Сообщение для создаваемой ошибки сервиса.

        Returns:
            Ошибка сервисного уровня с контекстом исходного исключения.
        """

        return service_error_from_exception(
            exc,
            service=SERVICE_NAME,
            operation=operation,
            message=message,
        )


async def _ensure_upload_quota(
    uow: Any,
    *,
    user_id: UUID,
    data: UploadSessionCreateRequest,
) -> None:
    """Проверяет квоты перед созданием upload-сессии.

    Проверяет, можно ли сохранить файл указанного размера с учетом увеличения
    количества файлов, а также можно ли создать еще одну активную upload-сессию.

    Args:
        uow: Unit of Work с репозиторием квот.
        user_id: Идентификатор пользователя.
        data: Данные создаваемой upload-сессии.

    Raises:
        UploadServiceError: Если файл превышает лимиты квоты или превышен лимит
            активных upload-сессий.
    """

    allowed = await uow.quotas.can_store_file(
        user_id,
        file_size_bytes=data.file_size_bytes,
        additional_files_count=1,
        use_stored_files_counter=True,
    )
    if not allowed:
        raise UploadServiceError(
            "Загрузка файлов превышает лимиты пользовательской квоты.",
            user_id=user_id,
            operation="initiate_upload",
            details={
                "service": SERVICE_NAME,
                "operation": "initiate_upload",
                "user_id": str(user_id),
                "file_size_bytes": data.file_size_bytes,
            },
        )
    # Указывает на ФАКТИЧЕСКОЕ количество сеансов, не связанных с терминалом, а не на кэшированный
    # Счетчик `active_upload_sessions_used`. Кэшированный счетчик может увеличиваться
    # из-за некоторых переходов терминала (в частности, истечения срока действия работником по очистке).
    # не уменьшайте его, иначе это привело бы к постоянной блокировке пользователя.
    can_create_session = await uow.quotas.check_active_upload_sessions_limit_allowed(
        user_id,
        additional_sessions_count=1,
        use_stored_counter=False,
        exclude_time_expired=True,
    )
    if not can_create_session:
        raise UploadServiceError(
            "Превышена квота активного сеанса загрузки.",
            user_id=user_id,
            operation="initiate_upload",
            details={
                "service": SERVICE_NAME,
                "operation": "initiate_upload",
                "user_id": str(user_id),
            },
        )


def _build_part_sizes(
    *,
    file_size_bytes: int,
    part_size_bytes: int | None,
    parts_count: int,
    default_part_size_bytes: int,
) -> list[int]:
    """Рассчитывает размеры частей multipart-загрузки.

    Проверяет положительный размер файла и количество частей. Если размер части
    не передан, выбирает максимум из дефолтного размера части и размера,
    рассчитанного по количеству частей. Затем проверяет, что итоговое количество
    частей совпадает с ожидаемым.

    Args:
        file_size_bytes: Размер файла в байтах.
        part_size_bytes: Желаемый размер одной части. Если None, размер
            рассчитывается автоматически.
        parts_count: Ожидаемое количество частей.
        default_part_size_bytes: Размер части по умолчанию из StorageService.

    Returns:
        Список размеров частей в байтах.

    Raises:
        ValidationServiceError: Если размер файла, количество частей или
            соотношение размера файла и размера части некорректны.
    """

    if file_size_bytes <= 0:
        raise ValidationServiceError(
            "Размер файла должен быть положительным.",
            field="file_size_bytes",
            value=file_size_bytes,
            reason="not_positive",
            details={"service": SERVICE_NAME},
        )
    if parts_count <= 0:
        raise ValidationServiceError(
            "Количество частей должно быть положительным.",
            field="parts_count",
            value=parts_count,
            reason="not_positive",
            details={"service": SERVICE_NAME},
        )
    resolved_part_size = part_size_bytes or max(
        default_part_size_bytes,
        math.ceil(file_size_bytes / parts_count),
    )
    calculated_parts_count = math.ceil(file_size_bytes / resolved_part_size)
    if calculated_parts_count != parts_count:
        raise ValidationServiceError(
            "Количество частей не соответствует размеру файла и размеру части.",
            field="parts_count",
            value=parts_count,
            reason="parts_count_mismatch",
            details={
                "service": SERVICE_NAME,
                "file_size_bytes": file_size_bytes,
                "part_size_bytes": resolved_part_size,
                "expected_parts_count": calculated_parts_count,
            },
        )

    sizes: list[int] = []
    remaining = file_size_bytes
    for _ in range(parts_count):
        current_size = min(resolved_part_size, remaining)
        sizes.append(current_size)
        remaining -= current_size
    return sizes


def _ensure_folder_node(node: FileSystemNode, *, operation: str) -> None:
    """Проверяет, что родительский узел является папкой.

    Args:
        node: Узел файловой системы для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если узел не является папкой.
    """

    if node.node_type == NodeType.FOLDER:
        return
    raise ValidationServiceError(
        "Родительский узел - это не папка.",
        field="parent_node_id",
        value=node.id,
        reason="not_folder",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "node_type": _jsonable(node.node_type),
        },
    )


def _ensure_can_receive_parts(upload_session: UploadSession, *, operation: str) -> None:
    """Проверяет, что upload-сессия может принимать части.

    Сессия должна находиться в активном статусе и не должна быть просроченной.

    Args:
        upload_session: Upload-сессия для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        UploadServiceError: Если сессия находится в неподходящем статусе или
            истекла.
    """

    now = datetime.now(UTC)
    if upload_session.status not in ACTIVE_UPLOAD_STATUSES:
        raise UploadServiceError(
            "Сеанс загрузки не может принимать части в текущем состоянии.",
            upload_session_id=upload_session.id,
            operation=operation,
            details={
                "service": SERVICE_NAME,
                "operation": operation,
                "status": upload_session.status.value,
            },
        )
    if upload_session.expires_at <= now:
        raise UploadServiceError(
            "Сеанс загрузки истек.",
            upload_session_id=upload_session.id,
            operation=operation,
            details={"service": SERVICE_NAME, "operation": operation},
        )


def _ensure_can_complete(upload_session: UploadSession, *, operation: str) -> None:
    """Проверяет, что upload-сессию можно завершить.

    Сейчас использует те же условия, что и прием частей: активный статус и
    неистекший срок действия.

    Args:
        upload_session: Upload-сессия для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        UploadServiceError: Если сессию нельзя завершить.
    """

    _ensure_can_receive_parts(upload_session, operation=operation)


def _ensure_part_size_matches(
    part: UploadPart,
    data: UploadPartCompleteRequest,
    *,
    operation: str,
) -> None:
    """Проверяет соответствие размера загруженной части.

    Args:
        part: Ожидаемая часть upload-сессии из базы данных.
        data: Данные части, переданные клиентом.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если размер загруженной части не совпадает
            с ожидаемым размером.
    """

    if part.size_bytes == data.size_bytes:
        return
    raise ValidationServiceError(
        "Размер загруженной части не соответствует метаданным инициированного сеанса.",
        field="size_bytes",
        value=data.size_bytes,
        reason="part_size_mismatch",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "part_number": part.part_number,
            "expected_size_bytes": part.size_bytes,
        },
    )


def _select_parts_for_urls(
    parts: Sequence[UploadPart],
    part_numbers: Sequence[int] | None,
) -> list[UploadPart]:
    """Выбирает части, для которых нужно создать URL.

    Если part_numbers не переданы, выбирает все части, которые еще не имеют
    статус UPLOADED. Если part_numbers переданы, проверяет, что все номера
    существуют в сессии.

    Args:
        parts: Все части upload-сессии.
        part_numbers: Запрошенные номера частей или None.

    Returns:
        Список выбранных частей.

    Raises:
        ValidationServiceError: Если запрошен неизвестный номер части.
    """

    if part_numbers is None:
        return [part for part in parts if part.status != UploadPartStatus.UPLOADED]
    requested = set(part_numbers)
    known = {part.part_number for part in parts}
    missing = requested - known
    if missing:
        raise ValidationServiceError(
            "Запрошенная часть для загрузки не существует.",
            field="part_numbers",
            value=sorted(missing),
            reason="unknown_part_number",
            details={"service": SERVICE_NAME},
        )
    return [part for part in parts if part.part_number in requested]


def _presigned_urls_response(
    upload_session: UploadSession,
    urls: Sequence[StoragePresignedUploadPartUrl],
    *,
    part_sizes: Sequence[int],
) -> UploadPresignedUrlsResponse:
    """Формирует ответ с URL для загрузки частей.

    Сопоставляет каждый URL с размером соответствующей части и переносит
    параметры HTTP-метода, срока действия и заголовков.

    Args:
        upload_session: Upload-сессия.
        urls: Предварительно подписанные URL для частей.
        part_sizes: Размеры частей в том же порядке, что и urls.

    Returns:
        Ответ с URL для загрузки частей.
    """

    size_by_part = {
        part_number: size
        for part_number, size in zip(
            [url.part_number for url in urls],
            part_sizes,
            strict=True,
        )
    }
    return UploadPresignedUrlsResponse(
        upload_session_id=upload_session.id,
        status=upload_session.status,
        expires_at=upload_session.expires_at,
        parts=[
            UploadPartPresignedUrlRead(
                part_number=item.part_number,
                url=item.url.url,
                method=item.url.method.value,
                expires_at=item.url.expires_at or upload_session.expires_at,
                headers=item.url.headers,
                size_bytes=size_by_part.get(item.part_number),
            )
            for item in urls
        ],
    )


async def _count_uploads(
    uow: Any,
    *,
    params: UploadQueryParams,
    user_id: UUID,
) -> int:
    """Возвращает количество upload-сессий пользователя по фильтрам.

    Args:
        uow: Unit of Work с репозиторием upload-сессий.
        params: Параметры фильтрации upload-сессий.
        user_id: Идентификатор пользователя.

    Returns:
        Количество upload-сессий, соответствующих фильтрам.
    """

    return await uow.upload_sessions.count_user_sessions_filtered(
        user_id=user_id,
        parent_node_id=params.parent_node_id,
        status=params.status,
        include_terminal=params.include_terminal,
        filename_query=params.filename,
        created_from=params.created_from,
        created_to=params.created_to,
        expires_before=params.expires_before,
    )


async def _select_uploads(
    uow: Any,
    *,
    params: UploadQueryParams,
    user_id: UUID,
) -> list[UploadSession]:
    """Выбирает upload-сессии пользователя по фильтрам.

    Проверяет поле сортировки и загружает страницу upload-сессий из репозитория.

    Args:
        uow: Unit of Work с репозиторием upload-сессий.
        params: Параметры фильтрации, сортировки и пагинации.
        user_id: Идентификатор пользователя.

    Returns:
        Список upload-сессий текущей страницы.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
    """

    _validate_upload_sort_field(params.sort_by)
    return await uow.upload_sessions.search_user_sessions(
        user_id=user_id,
        parent_node_id=params.parent_node_id,
        status=params.status,
        include_terminal=params.include_terminal,
        filename_query=params.filename,
        created_from=params.created_from,
        created_to=params.created_to,
        expires_before=params.expires_before,
        sort_by=params.sort_by,
        sort_desc=params.sort_desc,
        offset=params.offset,
        limit=params.limit,
    )


def _validate_upload_sort_field(sort_by: str) -> None:
    """Проверяет поле сортировки upload-сессий.

    Args:
        sort_by: Исходное поле сортировки.

    Raises:
        ValidationServiceError: Если поле сортировки не поддерживается.
    """

    normalized = sort_by.strip().lower()
    if normalized not in ALLOWED_UPLOAD_SORT_FIELDS:
        raise ValidationServiceError(
            "Поле сортировки upload-сессий не поддерживается.",
            field="sort_by",
            value=sort_by,
            reason="unsupported_sort_field",
            details={
                "service": SERVICE_NAME,
                "allowed_values": sorted(ALLOWED_UPLOAD_SORT_FIELDS),
            },
        )


def _session_snapshot(upload_session: UploadSession) -> dict[str, Any]:
    """Создает снимок upload-сессии.

    Args:
        upload_session: ORM-модель upload-сессии.

    Returns:
        Словарь с идентификаторами, именем и размером файла, параметрами частей,
        MIME-типом, checksum, статусом, прогрессом, датами завершения, отмены,
        ошибки, данными клиента и временем создания.
    """

    return {
        "id": upload_session.id,
        "user_id": upload_session.user_id,
        "parent_node_id": upload_session.parent_node_id,
        "file_name": upload_session.file_name,
        "file_size_bytes": upload_session.file_size_bytes,
        "part_size_bytes": upload_session.part_size_bytes,
        "mime_type": upload_session.mime_type,
        "checksum": upload_session.checksum,
        "checksum_algorithm": upload_session.checksum_algorithm,
        "status": upload_session.status,
        "parts_count": upload_session.parts_count,
        "uploaded_parts_count": upload_session.uploaded_parts_count,
        "uploaded_bytes": upload_session.uploaded_bytes,
        "expires_at": upload_session.expires_at,
        "completed_at": upload_session.completed_at,
        "aborted_at": upload_session.aborted_at,
        "failed_at": upload_session.failed_at,
        "failure_reason": upload_session.failure_reason,
        "client_ip": upload_session.client_ip,
        "user_agent": upload_session.user_agent,
        "created_at": upload_session.created_at,
    }


def _upload_progress_read(snapshot: Mapping[str, Any]) -> UploadProgressRead:
    """Преобразует снимок upload-сессии в DTO прогресса.

    Args:
        snapshot: Снимок upload-сессии.

    Returns:
        DTO прогресса загрузки с идентификатором сессии и вычисленным процентом
        завершения.
    """

    payload = dict(snapshot)
    payload["upload_session_id"] = snapshot.get("id")
    payload["progress_percent"] = _calculate_progress_percent(snapshot)
    return UploadProgressRead.model_validate(payload)


def _calculate_progress_percent(snapshot: Mapping[str, Any]) -> int:
    """Вычисляет процент прогресса upload-сессии.

    Args:
        snapshot: Снимок upload-сессии с `file_size_bytes` и `uploaded_bytes`.

    Returns:
        Целое значение прогресса от 0 до 100. Если размер файла или количество
        загруженных байтов отсутствуют либо некорректны, возвращает 0.
    """

    file_size_bytes = snapshot.get("file_size_bytes")
    uploaded_bytes = snapshot.get("uploaded_bytes")

    if not isinstance(file_size_bytes, int) or file_size_bytes <= 0:
        return 0
    if not isinstance(uploaded_bytes, int) or uploaded_bytes <= 0:
        return 0

    return max(0, min(100, int((uploaded_bytes * 100) / file_size_bytes)))


def _audit_upload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует метаданные upload-сессии для аудита.

    Args:
        snapshot: Снимок upload-сессии.

    Returns:
        Словарь с JSON-совместимыми метаданными upload-сессии.
    """

    return {
        "id": _jsonable(snapshot.get("id")),
        "user_id": _jsonable(snapshot.get("user_id")),
        "parent_node_id": _jsonable(snapshot.get("parent_node_id")),
        "file_name": snapshot.get("file_name"),
        "file_size_bytes": snapshot.get("file_size_bytes"),
        "parts_count": snapshot.get("parts_count"),
        "uploaded_parts_count": snapshot.get("uploaded_parts_count"),
        "uploaded_bytes": snapshot.get("uploaded_bytes"),
        "status": _jsonable(snapshot.get("status")),
        "expires_at": _jsonable(snapshot.get("expires_at")),
    }


def _filename_extension(filename: str) -> str | None:
    """Извлекает расширение имени файла.

    Args:
        filename: Имя файла.

    Returns:
        Расширение файла в нижнем регистре без точки или None, если расширение
        отсутствует.
    """

    suffix = PurePath(filename).suffix.strip(".").lower()
    return suffix or None


def _normalize_optional_text(value: str | None) -> str | None:
    """Нормализует опциональный текст.

    Args:
        value: Исходное текстовое значение.

    Returns:
        Обрезанная по краям строка или None, если значение отсутствует либо
        стало пустым после обрезки.
    """

    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_pagination(*, limit: int, offset: int) -> None:
    """Проверяет параметры пагинации upload-сессий.

    Args:
        limit: Размер страницы.
        offset: Смещение страницы.

    Raises:
        ValidationServiceError: Если limit находится вне диапазона от 1 до
            REPOSITORY_PAGE_LIMIT или offset отрицательный.
    """

    if limit < 1 or limit > REPOSITORY_PAGE_LIMIT:
        raise ValidationServiceError(
            "Недопустимое ограничение на разбивку на страницы.",
            field="limit",
            value=limit,
            reason="out_of_range",
            details={"service": SERVICE_NAME, "max_limit": REPOSITORY_PAGE_LIMIT},
        )
    if offset < 0:
        raise ValidationServiceError(
            "Недопустимое смещение разбивки на страницы.",
            field="offset",
            value=offset,
            reason="negative_offset",
            details={"service": SERVICE_NAME},
        )


def _optional_uuid(value: Any) -> UUID | None:
    """Возвращает UUID-значение или None.

    Args:
        value: Проверяемое значение.

    Returns:
        value, если оно является UUID, иначе None.
    """

    return value if isinstance(value, UUID) else None


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-совместимый формат.

    Поддерживает примитивы, UUID, datetime, Enum, Mapping и Iterable. Для
    остальных объектов возвращает строковое представление.

    Args:
        value: Значение для преобразования.

    Returns:
        JSON-совместимое представление значения.
    """

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [_jsonable(item) for item in value]
    return str(value)


def _empty_result_error(operation: str) -> ServiceError:
    """Создает ошибку пустого результата сервисной операции.

    Args:
        operation: Название операции, завершившейся без результата.

    Returns:
        Ошибка сервиса с описанием отсутствующего результата.
    """

    return ServiceError(
        "Сервисная операция завершена безрезультатно.",
        service=SERVICE_NAME,
        operation=operation,
    )


# Глобальный singleton-экземпляр сервиса загрузок.
_uploads_service: UploadsService | None = None


def get_uploads_service(
    *,
    settings: Settings | None = None,
    uow_factory: UnitOfWorkFactory | None = None,
    storage_service: StorageService | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
) -> UploadsService:
    """Возвращает экземпляр сервиса загрузок.

    Если передана хотя бы одна зависимость, создает новый экземпляр сервиса с
    указанными зависимостями. Если зависимости не переданы, возвращает
    глобальный singleton-экземпляр, создавая его при первом обращении.

    Args:
        settings: Настройки приложения для нового экземпляра сервиса.
        uow_factory: Фабрика Unit of Work для нового экземпляра сервиса.
        storage_service: Сервис хранилища для нового экземпляра сервиса.
        access_service: Сервис доступа для нового экземпляра сервиса.
        audit_service: Сервис аудита для нового экземпляра сервиса.

    Returns:
        Экземпляр UploadsService.
    """

    global _uploads_service
    if any(
        dependency is not None
        for dependency in (
            settings,
            uow_factory,
            storage_service,
            access_service,
            audit_service,
        )
    ):
        return UploadsService(
            settings=settings,
            uow_factory=uow_factory,
            storage_service=storage_service,
            access_service=access_service,
            audit_service=audit_service,
        )
    if _uploads_service is None:
        _uploads_service = UploadsService()
    return _uploads_service

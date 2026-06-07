from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, cast
from uuid import UUID

from core.config import Settings, get_settings
from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    BackgroundTaskStatus,
    BackgroundTaskType,
    FileVersionStatus,
    NodeType,
    StorageObjectStatus,
)
from database.models.filesystem import File, FileSystemNode, FileVersion, Folder
from database.models.tasks import BackgroundTask
from schemas.files import FileDownloadRequest, FileDownloadResponse
from schemas.folders import (
    BulkArchiveRequest,
    FolderArchiveRequest,
    FolderArchiveResponse,
)
from security.permissions import PermissionAction
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    DownloadServiceError,
    PermissionServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
    service_error_from_storage,
)
from storage import StorageError, StorageService, get_storage_service

logger = get_logger("services.downloads")

SERVICE_NAME = "downloads"
ZIP_MIME_TYPE = "application/zip"

# mimetypes.guess_type полагается на реестр ОС и не распознаёт некоторые форматы
# в Windows, в частности .mkv, .m4v, .flac, .opus, .m4a. При наличии
# X-Content-Type-Options: nosniff Chrome строго проверяет объявленный Content-Type
# и откажется воспроизводить всё, что объявлено как application/octet-stream.
# Эти переопределения применяются только в крайнем случае, когда не сработали
# ни значение из БД, ни mimetypes.
_MIME_FALLBACKS: dict[str, str] = {
    "mkv": "video/x-matroska",
    "m4v": "video/mp4",
    "flv": "video/x-flv",
    "wmv": "video/x-ms-wmv",
    "avi": "video/x-msvideo",
    "3gp": "video/3gpp",
    "3g2": "video/3gpp2",
    "ts": "video/mp2t",
    "m2ts": "video/mp2t",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "opus": "audio/ogg",
    "wma": "audio/x-ms-wma",
    "aif": "audio/aiff",
    "aiff": "audio/aiff",
}


class DownloadsService:
    """Сервис бизнес-логики для скачивания файлов и архивов.

    Создает предварительно подписанные URL для скачивания отдельных файлов,
    конкретных версий файлов и готовых ZIP-архивов папок. Также ставит задачи
    на создание архивов папок и записывает успешные операции в аудит.

    Attributes:
        settings: Настройки приложения.
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        storage_service: Сервис хранилища для создания ссылок на объекты.
        access_service: Сервис проверки прав доступа к узлам файловой системы.
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
        """Инициализирует сервис скачиваний.

        Если зависимости не переданы явно, создает их через стандартные
        фабрики и функции получения сервисов.

        Args:
            settings: Настройки приложения. Если не переданы, используются
                настройки по умолчанию.
            uow_factory: Фабрика Unit of Work. Если не передана, создается
                стандартная фабрика.
            storage_service: Сервис хранилища. Если не передан, создается
                стандартный сервис хранилища.
            access_service: Сервис проверки доступа. Если не передан,
                создается стандартный сервис доступа.
            audit_service: Сервис аудита. Если не передан, создается
                стандартный сервис аудита.
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

    async def create_thumbnail_url(
        self,
        *,
        node_id: UUID,
        user_id: UUID,
    ) -> FileDownloadResponse:
        """Создает предварительно подписанный URL для thumbnail узла.

        Если у файла есть готовый preview (preview_status=READY и
        preview_storage_key), возвращает ссылку на preview-объект.
        Иначе — ссылку на полный файл без заголовка Content-Disposition,
        чтобы браузер отображал изображение inline.

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя, запрашивающего thumbnail.

        Returns:
            Ответ с предварительно подписанным URL для thumbnail или полного файла.

        Raises:
            DownloadServiceError: Если файл недоступен.
            PermissionServiceError: Если у пользователя нет права на чтение.
            ServiceError: Если произошла ошибка базы данных, хранилища или
                непредвиденная ошибка сервиса.
        """

        operation = "create_thumbnail_url"
        file_snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                file = await uow.files.get_required_by_node_id(node_id)
                node = _require_file_node(file, operation=operation)
                await self.access_service.require_access(
                    node_id=node.id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    uow=uow,
                )
                file_snapshot = _thumbnail_snapshot(file)

            if file_snapshot is None:
                raise _empty_result_error(operation)

            return await self._build_thumbnail_response(file_snapshot)

        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать URL-адрес миниатюры с предварительной подписью",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось создать URL-адрес миниатюры.",
            ) from exc

    async def create_thumbnail_urls_batch(
        self,
        *,
        node_ids: list[UUID],
        user_id: UUID,
    ) -> dict[str, str | None]:
        """Возвращает presigned URL thumbnail для каждого из запрошенных узлов.

        Запускает получение URL параллельно. Для узлов, к которым нет доступа
        или которые не являются изображениями, возвращает None.

        Args:
            node_ids: Список идентификаторов узлов.
            user_id: Идентификатор текущего пользователя.

        Returns:
            Словарь node_id (строка) → presigned URL или None.
        """

        tasks = [
            self.create_thumbnail_url(node_id=nid, user_id=user_id) for nid in node_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            str(nid): (r.presigned_url if not isinstance(r, BaseException) else None)
            for nid, r in zip(node_ids, results)
        }

    async def stream_file(
        self,
        *,
        node_id: UUID,
        user_id: UUID,
        offset: int = 0,
        length: int = 0,
    ) -> tuple[Any, str, str, int]:
        """Проверяет доступ и возвращает поток файла из хранилища.

        Возвращает кортеж (stream, mime_type, filename, size_bytes).
        Вызывающий код обязан закрыть stream через close() и release_conn().

        Args:
            node_id: Идентификатор узла файловой системы.
            user_id: Идентификатор пользователя.
            offset: Смещение в байтах для Range-запроса.
            length: Количество байт для Range-запроса (0 — до конца).

        Returns:
            Кортеж (stream, mime_type, filename, total_size_bytes).
        """

        operation = "stream_file"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                file = await uow.files.get_required_by_node_id(node_id)
                node = _require_file_node(file, operation=operation)
                await self.access_service.require_access(
                    node_id=node.id,
                    user_id=user_id,
                    action=PermissionAction.READ,
                    uow=uow,
                )
                _ensure_file_downloadable(file, operation=operation)
                snapshot = _file_snapshot(file)

            if snapshot is None:
                raise _empty_result_error(operation)

            filename: str = snapshot.get("name") or "file"
            _ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            mime_type: str = (
                snapshot.get("mime_type")
                or mimetypes.guess_type(filename)[0]
                or _MIME_FALLBACKS.get(_ext)
                or "application/octet-stream"
            )
            size_bytes: int = snapshot.get("size_bytes") or 0
            bucket: str = snapshot["storage_bucket"]
            object_key: str = snapshot["storage_key"]

            stream = await self.storage_service.get_file_object_stream(
                bucket=bucket,
                object_key=object_key,
                offset=offset,
                length=length,
            )
            return stream, mime_type, filename, size_bytes

        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось открыть файловый поток.",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось передать файл в потоковом режиме.",
            ) from exc

    async def create_file_download_url(
        self,
        data: FileDownloadRequest,
        *,
        user_id: UUID,
    ) -> FileDownloadResponse:
        """Создает предварительно подписанный URL для скачивания файла.

        Проверяет существование файла, права пользователя на скачивание,
        доступность объекта в хранилище и, если указана версия, корректность
        выбранной версии файла. После создания URL записывает событие аудита.

        Args:
            data: Данные запроса на скачивание файла.
            user_id: Идентификатор пользователя, запрашивающего скачивание.

        Returns:
            Ответ с предварительно подписанным URL, сроком действия, HTTP-методом,
            заголовками, метаданными файла и выбранной версии.

        Raises:
            DownloadServiceError: Если файл недоступен для скачивания, не связан
                с корректным файловым узлом или выбранная версия неактивна.
            PermissionServiceError: Если у пользователя нет права на скачивание.
            ValidationServiceError: Если указанная версия не принадлежит файлу.
            ServiceError: Если произошла ошибка базы данных, хранилища или
                непредвиденная ошибка сервиса.
        """

        operation = "create_file_download_url"
        file_snapshot: dict[str, Any] | None = None
        version_snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                file = await uow.files.get_required_by_id(data.file_id)
                node = _require_file_node(file, operation=operation)
                await self.access_service.require_access(
                    node_id=node.id,
                    user_id=user_id,
                    action=PermissionAction.DOWNLOAD,
                    uow=uow,
                )
                _ensure_file_downloadable(file, operation=operation)
                version = await _resolve_download_version(
                    uow,
                    file=file,
                    version_id=data.version_id,
                    operation=operation,
                )
                file_snapshot = _file_snapshot(file)
                version_snapshot = (
                    _version_snapshot(version) if version is not None else None
                )

            if file_snapshot is None:
                raise _empty_result_error(operation)

            response = await self._build_file_download_response(
                data,
                file_snapshot=file_snapshot,
                version_snapshot=version_snapshot,
            )
            await self._safe_log_download_event(
                user_id=user_id,
                action=AuditAction.FILE_DOWNLOADED,
                entity_id=cast(UUID, file_snapshot["id"]),
                resource_type=AuditResourceType.FILE,
                message="Был создан URL-адрес для загрузки файла.",
                metadata={
                    "file": _audit_file(file_snapshot),
                    "version": _jsonable(version_snapshot),
                    "expires_at": response.expires_at.isoformat(),
                },
            )
            return response

        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать предварительно подписанный URL-адрес для загрузки файла.",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось создать URL-адрес для загрузки файла.",
            ) from exc

    def _archive_result_data(
        self,
        *,
        user_id: UUID,
        task_id: UUID,
        archive_name: str,
    ) -> dict[str, Any]:
        """Базовые поля result_data архивной задачи (общие для всех архивов).

        Ключ архива детерминирован по (user_id, task_id), поэтому совпадает с
        тем, что вычислит воркер при выгрузке.
        """

        return {
            "archive_name": archive_name,
            "storage_bucket": self.storage_service.default_archives_bucket,
            "storage_key": self.storage_service.build_archive_key(
                user_id=user_id,
                task_id=task_id,
                extension="zip",
            ),
            "content_type": ZIP_MIME_TYPE,
        }

    async def request_folder_archive(
        self,
        data: FolderArchiveRequest,
        *,
        user_id: UUID,
    ) -> FolderArchiveResponse:
        """Ставит фоновую задачу на создание ZIP-архива папки.

        Проверяет доступ пользователя к папке, создает пользовательскую фоновую
        задачу, сохраняет параметры архивации в payload и ожидаемые данные
        результата в result_data. После создания задачи записывает событие аудита.

        Args:
            data: Данные запроса на создание архива папки.
            user_id: Идентификатор пользователя, запрашивающего архив.

        Returns:
            Ответ с идентификатором созданной фоновой задачи и ее статусом.

        Raises:
            ValidationServiceError: Если указанный узел файловой системы не
                является папкой.
            PermissionServiceError: Если у пользователя нет доступа к папке.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "request_folder_archive"
        task_snapshot: dict[str, Any] | None = None
        folder_snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=data.folder_id,
                    user_id=user_id,
                    action=PermissionAction.DOWNLOAD,
                    allow_deleted=data.include_deleted,
                    uow=uow,
                )
                _ensure_folder_node(node, operation=operation)
                folder = await uow.folders.get_required_by_node_id(
                    node.id,
                    include_deleted=data.include_deleted,
                )
                task = await uow.tasks.create_user_task(
                    task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
                    created_by=user_id,
                    related_entity_type="folder",
                    related_entity_id=folder.node_id,
                    flush=True,
                    refresh=True,
                )
                archive_name = _archive_filename(data.archive_name or node.name)
                payload = {
                    "folder_id": str(folder.node_id),
                    "include_deleted": data.include_deleted,
                    "archive_name": archive_name,
                    "password": data.password,
                }
                result_data = {
                    **self._archive_result_data(
                        user_id=user_id, task_id=task.id, archive_name=archive_name
                    ),
                    "folder_id": str(folder.node_id),
                    "password_protected": data.password is not None,
                }
                task = await uow.tasks.update(
                    task,
                    {"payload": payload, "result_data": result_data},
                    flush=True,
                    refresh=True,
                    allowed_fields={"payload", "result_data"},
                )
                task_snapshot = _task_snapshot(task)
                folder_snapshot = _folder_snapshot(folder)
                await uow.commit()

            if task_snapshot is None or folder_snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_download_event(
                user_id=user_id,
                action=AuditAction.FOLDER_ARCHIVE_REQUESTED,
                entity_id=cast(UUID, folder_snapshot["node_id"]),
                resource_type=AuditResourceType.FOLDER,
                message="Задача архивирования папок была поставлена в очередь.",
                metadata={
                    "task": _audit_task(task_snapshot),
                    "folder": _audit_folder(folder_snapshot),
                },
            )
            return FolderArchiveResponse(
                task_id=cast(UUID, task_snapshot["id"]),
                status=cast(BackgroundTaskStatus, task_snapshot["status"]),
            )

        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось запросить архив папки.",
            ) from exc

    async def request_bulk_archive(
        self,
        data: BulkArchiveRequest,
        *,
        user_id: UUID,
    ) -> FolderArchiveResponse:
        """Ставит фоновую задачу на создание ZIP-архива из набора узлов.

        Проверяет право DOWNLOAD на каждый выбранный узел, затем создаёт задачу
        типа CREATE_FOLDER_ARCHIVE (переиспользуется как универсальный тип
        «создать архив») с payload, содержащим список node_ids. Так как архив не
        привязан к одному узлу, related_entity_id не задаётся.

        Args:
            data: Данные запроса с идентификаторами узлов и именем архива.
            user_id: Идентификатор пользователя, запрашивающего архив.

        Returns:
            Ответ с идентификатором созданной фоновой задачи и её статусом.

        Raises:
            PermissionServiceError: Если у пользователя нет доступа к узлу.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "request_bulk_archive"
        task_snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                for node_id in data.node_ids:
                    await self.access_service.require_access(
                        node_id=node_id,
                        user_id=user_id,
                        action=PermissionAction.DOWNLOAD,
                        uow=uow,
                    )

                archive_name = _archive_filename(data.archive_name or "archive")
                task = await uow.tasks.create_user_task(
                    task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
                    created_by=user_id,
                    flush=True,
                    refresh=True,
                )
                payload = {
                    "node_ids": [str(nid) for nid in data.node_ids],
                    "archive_name": archive_name,
                    "requested_by": str(user_id),
                }
                result_data = self._archive_result_data(
                    user_id=user_id, task_id=task.id, archive_name=archive_name
                )
                task = await uow.tasks.update(
                    task,
                    {"payload": payload, "result_data": result_data},
                    flush=True,
                    refresh=True,
                    allowed_fields={"payload", "result_data"},
                )
                task_snapshot = _task_snapshot(task)
                await uow.commit()

            if task_snapshot is None:
                raise _empty_result_error(operation)

            return FolderArchiveResponse(
                task_id=cast(UUID, task_snapshot["id"]),
                status=cast(BackgroundTaskStatus, task_snapshot["status"]),
                message="Задача создания архива поставлена в очередь.",
            )

        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось запросить массовый архив.",
            ) from exc

    async def create_archive_download_url(
        self,
        *,
        task_id: UUID,
        user_id: UUID,
        force_download: bool = True,
        filename: str | None = None,
    ) -> FileDownloadResponse:
        """Создает предварительно подписанный URL для скачивания готового архива.

        Проверяет, что задача является задачей создания архива папки, принадлежит
        указанному пользователю и завершена успешно. Если задача связана с узлом
        файловой системы, дополнительно проверяет право пользователя на скачивание.
        После создания URL записывает событие аудита.

        Args:
            task_id: Идентификатор фоновой задачи создания архива.
            user_id: Идентификатор пользователя, запрашивающего скачивание.
            force_download: Нужно ли принудительно скачивать файл как вложение.
                Если False, браузер может попытаться открыть архив inline.
            filename: Имя файла архива для заголовка скачивания. Если не указано,
                используется имя из результата задачи или имя по умолчанию.

        Returns:
            Ответ с предварительно подписанным URL, сроком действия, HTTP-методом,
            заголовками и метаданными ZIP-архива.

        Raises:
            ValidationServiceError: Если задача не является задачей создания
                архива папки.
            PermissionServiceError: Если задача принадлежит другому пользователю
                или у пользователя нет доступа к связанной папке.
            DownloadServiceError: Если архив еще не готов или данные результата
                задачи некорректны.
            ServiceError: Если произошла ошибка базы данных, хранилища или
                непредвиденная ошибка сервиса.
        """

        operation = "create_archive_download_url"
        task_snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                task = await uow.tasks.get_required_by_id(task_id)
                _ensure_archive_task_downloadable(
                    task,
                    user_id=user_id,
                    operation=operation,
                )
                if task.related_entity_id is not None:
                    await self.access_service.require_access(
                        node_id=task.related_entity_id,
                        user_id=user_id,
                        action=PermissionAction.DOWNLOAD,
                        uow=uow,
                    )
                task_snapshot = _task_snapshot(task)

            if task_snapshot is None:
                raise _empty_result_error(operation)

            response = await self._build_archive_download_response(
                task_snapshot,
                force_download=force_download,
                filename=filename,
            )
            await self._safe_log_download_event(
                user_id=user_id,
                action=AuditAction.FOLDER_ARCHIVE_CREATED,
                entity_id=task_id,
                resource_type=AuditResourceType.BACKGROUND_TASK,
                message="Был создан URL-адрес для загрузки архива.",
                metadata={
                    "task": _audit_task(task_snapshot),
                    "expires_at": response.expires_at.isoformat(),
                },
            )
            return response

        except StorageError as exc:
            raise service_error_from_storage(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать предварительно подписанный URL-адрес для загрузки архива.",
            ) from exc
        except DatabaseError as exc:
            raise self._database_error(exc, operation=operation) from exc
        except ServiceError:
            raise
        except Exception as exc:
            raise self._unexpected_error(
                exc,
                operation=operation,
                message="Не удалось создать URL-адрес для загрузки архива.",
            ) from exc

    async def _build_file_download_response(
        self,
        data: FileDownloadRequest,
        *,
        file_snapshot: Mapping[str, Any],
        version_snapshot: Mapping[str, Any] | None,
    ) -> FileDownloadResponse:
        """Формирует ответ со ссылкой на скачивание файла.

        Выбирает объект хранилища из снимка файла или снимка версии, подготавливает
        HTTP-заголовки для скачивания и запрашивает у сервиса хранилища
        предварительно подписанный URL.

        Args:
            data: Исходные параметры запроса на скачивание.
            file_snapshot: Снимок метаданных файла.
            version_snapshot: Снимок метаданных версии файла. Если None,
                используется текущий объект файла.

        Returns:
            Ответ со ссылкой на скачивание файла или выбранной версии.

        Raises:
            StorageError: Если сервис хранилища не смог создать URL.
        """

        filename = data.filename or cast(str, file_snapshot["name"])
        object_bucket = cast(str, file_snapshot["storage_bucket"])
        object_key = cast(str, file_snapshot["storage_key"])
        size_bytes = cast(int, file_snapshot["size_bytes"])
        mime_type = cast(str | None, file_snapshot["mime_type"])
        version_id: UUID | None = None

        if version_snapshot is not None:
            version_id = cast(UUID, version_snapshot["id"])
            object_bucket = cast(str, version_snapshot["storage_bucket"])
            object_key = cast(str, version_snapshot["storage_key"])
            size_bytes = cast(int, version_snapshot["size_bytes"])
            mime_type = cast(str | None, version_snapshot["mime_type"]) or mime_type

        presigned = await self.storage_service.create_download_url(
            bucket=object_bucket,
            object_key=object_key,
            response_headers=_download_response_headers(
                filename=filename,
                mime_type=mime_type,
                force_download=data.force_download,
            ),
        )
        expires_at = _presigned_expires_at(
            presigned.expires_at,
            expires_in_seconds=presigned.expires_in_seconds,
        )
        return FileDownloadResponse(
            presigned_url=presigned.url,
            expires_at=expires_at,
            method=presigned.method.value,
            headers=presigned.headers,
            file_id=cast(UUID, file_snapshot["id"]),
            version_id=version_id,
            filename=filename,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )

    async def _build_thumbnail_response(
        self,
        file_snapshot: dict[str, Any],
    ) -> FileDownloadResponse:
        """Формирует ответ со ссылкой на thumbnail файла.

        Если у файла есть preview-объект, использует его. Иначе — основной
        объект файла. Content-Disposition не задаётся, чтобы браузер показывал
        изображение inline.

        Args:
            file_snapshot: Снимок метаданных файла с preview-полями.

        Returns:
            Ответ со ссылкой на thumbnail или полный файл.

        Raises:
            StorageError: Если сервис хранилища не смог создать URL.
        """

        use_preview = (
            file_snapshot.get("preview_storage_key") is not None
            and file_snapshot.get("preview_ready") is True
        )
        bucket = cast(str, file_snapshot["storage_bucket"])
        object_key = (
            cast(str, file_snapshot["preview_storage_key"])
            if use_preview
            else cast(str, file_snapshot["storage_key"])
        )
        mime_type = cast(str | None, file_snapshot.get("mime_type"))

        response_headers: dict[str, str] = {}
        if mime_type:
            response_headers["response-content-type"] = mime_type

        presigned = await self.storage_service.create_download_url(
            bucket=bucket,
            object_key=object_key,
            response_headers=response_headers or None,
        )
        expires_at = _presigned_expires_at(
            presigned.expires_at,
            expires_in_seconds=presigned.expires_in_seconds,
        )
        return FileDownloadResponse(
            presigned_url=presigned.url,
            expires_at=expires_at,
            method=presigned.method.value,
            headers=presigned.headers,
            file_id=cast(UUID, file_snapshot["id"]),
            filename=None,
            size_bytes=cast(int, file_snapshot["size_bytes"]),
            mime_type=mime_type,
        )

    async def _build_archive_download_response(
        self,
        task_snapshot: Mapping[str, Any],
        *,
        force_download: bool,
        filename: str | None,
    ) -> FileDownloadResponse:
        """Формирует ответ со ссылкой на скачивание ZIP-архива.

        Извлекает из снимка задачи bucket, storage key, имя архива и размер.
        Если часть данных отсутствует, использует значения по умолчанию и
        стандартный путь архива в хранилище.

        Args:
            task_snapshot: Снимок фоновой задачи создания архива.
            force_download: Нужно ли принудительно скачивать файл как вложение.
            filename: Пользовательское имя файла архива. Если None, имя берется
                из result_data задачи или формируется по идентификатору задачи.

        Returns:
            Ответ со ссылкой на скачивание ZIP-архива.

        Raises:
            StorageError: Если сервис хранилища не смог создать URL.
        """

        result_data = _mapping_or_empty(task_snapshot.get("result_data"))
        task_id = cast(UUID, task_snapshot["id"])
        user_id = cast(UUID, task_snapshot["created_by"])
        resolved_filename = _archive_filename(
            filename
            or _optional_str(result_data.get("archive_name"))
            or f"archive-{task_id}.zip"
        )
        storage_bucket = (
            _optional_str(result_data.get("storage_bucket"))
            or self.storage_service.default_archives_bucket
        )
        storage_key = _optional_str(result_data.get("storage_key")) or (
            self.storage_service.build_archive_key(
                user_id=user_id,
                task_id=task_id,
                extension="zip",
            )
        )
        size_bytes = _optional_int(result_data.get("size_bytes"))
        presigned = await self.storage_service.create_download_url(
            bucket=storage_bucket,
            object_key=storage_key,
            response_headers=_download_response_headers(
                filename=resolved_filename,
                mime_type=ZIP_MIME_TYPE,
                force_download=force_download,
            ),
        )
        expires_at = _presigned_expires_at(
            presigned.expires_at,
            expires_in_seconds=presigned.expires_in_seconds,
        )
        return FileDownloadResponse(
            presigned_url=presigned.url,
            expires_at=expires_at,
            method=presigned.method.value,
            headers=presigned.headers,
            file_id=None,
            version_id=None,
            filename=resolved_filename,
            size_bytes=size_bytes,
            mime_type=ZIP_MIME_TYPE,
        )

    async def _safe_log_download_event(
        self,
        *,
        user_id: UUID | None,
        action: AuditAction,
        entity_id: UUID | None,
        resource_type: AuditResourceType,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие скачивания в аудит.

        Ошибки записи аудита не пробрасываются выше, чтобы не ломать основную
        операцию скачивания. При ошибке пишет предупреждение в лог.

        Args:
            user_id: Идентификатор пользователя, связанного с событием.
            action: Действие аудита.
            entity_id: Идентификатор сущности, к которой относится событие.
            resource_type: Тип ресурса аудита.
            message: Текстовое описание события.
            metadata: Дополнительные JSON-совместимые метаданные события.
        """

        try:
            await self.audit_service.log_success(
                action=action,
                user_id=user_id,
                entity_type=resource_type.value,
                entity_id=entity_id,
                resource_type=resource_type,
                message=message,
                metadata=dict(metadata) if metadata else None,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита для службы загрузок.",
                extra={
                    "service": SERVICE_NAME,
                    "action": action.value,
                    "entity_id": str(entity_id) if entity_id is not None else None,
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )

    def _database_error(self, exc: DatabaseError, *, operation: str) -> ServiceError:
        """Преобразует ошибку базы данных в ошибку сервиса скачиваний.

        Args:
            exc: Исходная ошибка базы данных.
            operation: Название операции, во время которой возникла ошибка.

        Returns:
            Ошибка сервисного уровня с контекстом сервиса скачиваний.
        """

        return service_error_from_database(
            exc,
            service=SERVICE_NAME,
            operation=operation,
            message="Сбой в работе базы данных произошел в службе загрузки.",
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


async def _resolve_download_version(
    uow: Any,
    *,
    file: File,
    version_id: UUID | None,
    operation: str,
) -> FileVersion | None:
    """Возвращает версию файла для скачивания, если она указана.

    Если идентификатор версии отсутствует, возвращает None. Если версия указана,
    проверяет, что она принадлежит переданному файлу и находится в активном
    статусе.

    Args:
        uow: Unit of Work с репозиторием версий файлов.
        file: Файл, для которого запрашивается скачивание.
        version_id: Идентификатор версии файла. Если None, версия не выбирается.
        operation: Название операции для контекста ошибок.

    Returns:
        Активная версия файла или None, если версия не запрошена.

    Raises:
        ValidationServiceError: Если версия не принадлежит указанному файлу.
        DownloadServiceError: Если версия не находится в активном статусе.
    """

    if version_id is None:
        return None
    version = await uow.versions.get_required_by_id(version_id)
    if version.file_id != file.id:
        raise ValidationServiceError(
            "Запрошенная версия не принадлежит запрошенному файлу.",
            field="version_id",
            value=version_id,
            reason="file_version_mismatch",
            details={
                "service": SERVICE_NAME,
                "operation": operation,
                "file_id": str(file.id),
                "version_file_id": str(version.file_id),
            },
        )
    if version.status != FileVersionStatus.ACTIVE:
        raise DownloadServiceError(
            "Запрошенная версия файла не активна.",
            file_id=file.id,
            version_id=version_id,
            operation=operation,
            details={"version_status": version.status.value},
        )
    return version


def _require_file_node(file: File, *, operation: str) -> FileSystemNode:
    """Возвращает файловый узел, связанный с файлом.

    Проверяет, что у файла есть связанный узел файловой системы и что этот узел
    имеет тип файла.

    Args:
        file: Файл, для которого требуется получить узел.
        operation: Название операции для контекста ошибок.

    Returns:
        Узел файловой системы с типом FILE.

    Raises:
        DownloadServiceError: Если файл не связан с корректным файловым узлом.
    """

    if file.node is not None and file.node.node_type == NodeType.FILE:
        return file.node
    raise DownloadServiceError(
        "Метаданные файла не связаны с активным файловым узлом.",
        file_id=file.id,
        node_id=file.node_id,
        operation=operation,
    )


def _ensure_file_downloadable(file: File, *, operation: str) -> None:
    """Проверяет, что файл можно скачать.

    Файл считается доступным для скачивания, если его объект доступен в хранилище
    и связанный узел не помечен как удаленный.

    Args:
        file: Файл для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        DownloadServiceError: Если объект файла недоступен в хранилище или файл
            удален.
    """

    if file.storage_status != StorageObjectStatus.AVAILABLE:
        raise DownloadServiceError(
            "Файловый объект недоступен в хранилище.",
            file_id=file.id,
            node_id=file.node_id,
            operation=operation,
            details={"storage_status": file.storage_status.value},
        )
    if file.node is not None and file.node.is_deleted:
        raise DownloadServiceError(
            "Удаленный файл не может быть загружен.",
            file_id=file.id,
            node_id=file.node_id,
            operation=operation,
        )


def _ensure_folder_node(node: FileSystemNode, *, operation: str) -> None:
    """Проверяет, что узел файловой системы является папкой.

    Args:
        node: Узел файловой системы для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если узел не является папкой.
    """

    if node.node_type == NodeType.FOLDER:
        return
    raise ValidationServiceError(
        "Узел файловой системы - это не папка.",
        field="folder_id",
        value=node.id,
        reason="not_folder",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "node_type": node.node_type.value,
        },
    )


def _ensure_archive_task_downloadable(
    task: BackgroundTask,
    *,
    user_id: UUID,
    operation: str,
) -> None:
    """Проверяет, что архивная задача доступна для скачивания.

    Валидирует тип задачи, владельца задачи, статус завершения и формат данных
    результата.

    Args:
        task: Фоновая задача создания архива.
        user_id: Идентификатор пользователя, запрашивающего скачивание.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если задача не является задачей создания архива.
        PermissionServiceError: Если задача принадлежит другому пользователю.
        DownloadServiceError: Если задача еще не завершена или содержит
            некорректные данные результата.
    """

    if task.task_type != BackgroundTaskType.CREATE_FOLDER_ARCHIVE:
        raise ValidationServiceError(
            "Задача - это не задача архивирования папок",
            field="task_id",
            value=task.id,
            reason="invalid_task_type",
            details={
                "service": SERVICE_NAME,
                "operation": operation,
                "task_type": task.task_type.value,
            },
        )
    if task.created_by != user_id:
        raise PermissionServiceError(
            "Задача архивирования принадлежит другому пользователю.",
            user_id=user_id,
            resource_type="background_task",
            resource_id=task.id,
            action=PermissionAction.DOWNLOAD,
            reason="not_owner",
            details={"service": SERVICE_NAME, "operation": operation},
        )
    if task.status != BackgroundTaskStatus.COMPLETED:
        raise DownloadServiceError(
            "Архив не готов к загрузке.",
            node_id=task.related_entity_id,
            user_id=user_id,
            operation=operation,
            details={
                "task_id": str(task.id),
                "task_status": task.status.value,
                "error_message": task.error_message,
            },
        )
    result_data = task.result_data or {}
    if not isinstance(result_data, Mapping):
        raise DownloadServiceError(
            "Данные о результатах архивирования задания неверны.",
            node_id=task.related_entity_id,
            user_id=user_id,
            operation=operation,
            details={"task_id": str(task.id)},
        )


def _download_response_headers(
    *,
    filename: str,
    mime_type: str | None,
    force_download: bool,
) -> dict[str, str]:
    """Формирует response-заголовки для предварительно подписанного URL.

    Создает заголовок Content-Disposition для скачивания или inline-открытия
    файла. При наличии MIME-типа добавляет заголовок Content-Type.

    Args:
        filename: Имя файла, которое будет передано в Content-Disposition.
        mime_type: MIME-тип файла. Если None, Content-Type не добавляется.
        force_download: Нужно ли использовать attachment вместо inline.

    Returns:
        Словарь response-заголовков для URL скачивания.
    """

    disposition_type = "attachment" if force_download else "inline"
    safe_filename = filename.replace('"', "'")
    headers = {
        "response-content-disposition": (
            f'{disposition_type}; filename="{safe_filename}"'
        )
    }
    resolved_mime = mime_type or mimetypes.guess_type(filename)[0]
    if resolved_mime:
        headers["response-content-type"] = resolved_mime
    return headers


def _presigned_expires_at(
    expires_at: datetime | None,
    *,
    expires_in_seconds: int,
) -> datetime:
    """Определяет дату и время истечения предварительно подписанного URL.

    Если точное время истечения передано сервисом хранилища, нормализует его в
    UTC. Иначе вычисляет время истечения от текущего момента.

    Args:
        expires_at: Явное время истечения URL. Может быть None.
        expires_in_seconds: Срок действия URL в секундах.

    Returns:
        Дата и время истечения URL в UTC.
    """

    if expires_at is not None:
        return _normalize_datetime(expires_at)
    return datetime.now(UTC) + timedelta(seconds=expires_in_seconds)


def _archive_filename(value: str) -> str:
    """Нормализует имя ZIP-архива.

    Удаляет пробелы по краям, подставляет имя по умолчанию для пустого значения
    и добавляет расширение .zip, если оно отсутствует.

    Args:
        value: Исходное имя архива.

    Returns:
        Нормализованное имя ZIP-файла.
    """

    normalized = value.strip()
    if not normalized:
        normalized = "archive"
    if not normalized.lower().endswith(".zip"):
        normalized = f"{normalized}.zip"
    return normalized


def _file_snapshot(file: File) -> dict[str, Any]:
    """Создает снимок метаданных файла.

    Снимок используется после выхода из Unit of Work, чтобы не зависеть от
    состояния ORM-объекта и связанных отношений.

    Args:
        file: ORM-модель файла.

    Returns:
        Словарь с идентификаторами, данными узла, параметрами хранилища,
        размером, MIME-типом, контрольной суммой и временными метками файла.
    """

    node = file.node
    return {
        "id": file.id,
        "node_id": file.node_id,
        "name": node.name if node is not None else None,
        "path": node.path if node is not None else None,
        "owner_id": node.owner_id if node is not None else None,
        "storage_bucket": file.storage_bucket,
        "storage_key": file.storage_key,
        "storage_status": file.storage_status,
        "size_bytes": file.size_bytes,
        "mime_type": file.mime_type,
        "extension": file.extension,
        "checksum": file.checksum,
        "checksum_algorithm": file.checksum_algorithm,
        "current_version_id": file.current_version_id,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
    }


def _thumbnail_snapshot(file: File) -> dict[str, Any]:
    """Создает снимок метаданных файла для thumbnail.

    Включает поля preview, необходимые для выбора между preview-объектом
    и основным файлом при генерации presigned URL.

    Args:
        file: ORM-модель файла.

    Returns:
        Словарь с идентификаторами, storage-ключами, статусами preview и
        MIME-типом файла.
    """

    return {
        "id": file.id,
        "node_id": file.node_id,
        "storage_bucket": file.storage_bucket,
        "storage_key": file.storage_key,
        "storage_status": file.storage_status,
        "size_bytes": file.size_bytes,
        "mime_type": file.mime_type,
        "preview_ready": file.preview_available,
        "preview_storage_key": file.preview_storage_key,
    }


def _version_snapshot(version: FileVersion) -> dict[str, Any]:
    """Создает снимок метаданных версии файла.

    Args:
        version: ORM-модель версии файла.

    Returns:
        Словарь с идентификаторами версии и файла, номером версии, статусом,
        параметрами хранилища, размером, MIME-типом, контрольной суммой,
        автором создания и признаком текущей версии.
    """

    return {
        "id": version.id,
        "file_id": version.file_id,
        "version_number": version.version_number,
        "status": version.status,
        "storage_bucket": version.storage_bucket,
        "storage_key": version.storage_key,
        "size_bytes": version.size_bytes,
        "checksum": version.checksum,
        "checksum_algorithm": version.checksum_algorithm,
        "mime_type": version.mime_type,
        "created_at": version.created_at,
        "created_by": version.created_by,
        "change_comment": version.change_comment,
        "is_current": version.is_current,
    }


def _folder_snapshot(folder: Folder) -> dict[str, Any]:
    """Создает снимок метаданных папки.

    Args:
        folder: ORM-модель папки.

    Returns:
        Словарь с идентификаторами папки и узла, названием, путем, владельцем,
        описанием, цветом и временными метками.
    """

    node = folder.node
    return {
        "id": folder.id,
        "node_id": folder.node_id,
        "name": node.name if node is not None else None,
        "path": node.path if node is not None else None,
        "owner_id": node.owner_id if node is not None else None,
        "description": folder.description,
        "color": folder.color,
        "created_at": folder.created_at,
        "updated_at": folder.updated_at,
    }


def _task_snapshot(task: BackgroundTask) -> dict[str, Any]:
    """Создает снимок метаданных фоновой задачи.

    Args:
        task: ORM-модель фоновой задачи.

    Returns:
        Словарь с идентификатором, типом, статусом, владельцем, связанной
        сущностью, прогрессом, payload, result_data, ошибками и временными
        метками задачи.
    """

    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "created_by": task.created_by,
        "related_entity_type": task.related_entity_type,
        "related_entity_id": task.related_entity_id,
        "progress_percent": task.progress_percent,
        "payload": task.payload,
        "result_data": task.result_data,
        "error_message": task.error_message,
        "error_code": task.error_code,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _audit_file(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует JSON-совместимые данные файла для аудита.

    Args:
        snapshot: Снимок метаданных файла.

    Returns:
        Словарь с основными данными файла, приведенными к JSON-совместимым
        значениям.
    """

    return {
        "id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "name": snapshot.get("name"),
        "path": snapshot.get("path"),
        "size_bytes": snapshot.get("size_bytes"),
        "mime_type": snapshot.get("mime_type"),
        "storage_status": _jsonable(snapshot.get("storage_status")),
    }


def _audit_folder(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует JSON-совместимые данные папки для аудита.

    Args:
        snapshot: Снимок метаданных папки.

    Returns:
        Словарь с основными данными папки, приведенными к JSON-совместимым
        значениям.
    """

    return {
        "id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "name": snapshot.get("name"),
        "path": snapshot.get("path"),
        "owner_id": _jsonable(snapshot.get("owner_id")),
    }


def _audit_task(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует JSON-совместимые данные фоновой задачи для аудита.

    Args:
        snapshot: Снимок метаданных фоновой задачи.

    Returns:
        Словарь с основными данными задачи, приведенными к JSON-совместимым
        значениям.
    """

    return {
        "id": _jsonable(snapshot.get("id")),
        "task_type": _jsonable(snapshot.get("task_type")),
        "status": _jsonable(snapshot.get("status")),
        "created_by": _jsonable(snapshot.get("created_by")),
        "related_entity_id": _jsonable(snapshot.get("related_entity_id")),
        "progress_percent": snapshot.get("progress_percent"),
    }


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    """Возвращает mapping-значение или пустой словарь.

    Args:
        value: Проверяемое значение.

    Returns:
        Исходное значение, если оно является Mapping, иначе пустой словарь.
    """

    return value if isinstance(value, Mapping) else {}


def _optional_str(value: Any) -> str | None:
    """Возвращает непустую строку или None.

    Args:
        value: Проверяемое значение.

    Returns:
        Обрезанная по краям строка, если значение является непустой строкой.
        Иначе None.
    """

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_int(value: Any) -> int | None:
    """Возвращает целое число или None.

    Значения bool не считаются допустимыми, несмотря на то что bool является
    подклассом int.

    Args:
        value: Проверяемое значение.

    Returns:
        Целое число, если значение является int и не является bool. Иначе None.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _normalize_datetime(value: datetime) -> datetime:
    """Нормализует дату и время к UTC.

    Если значение не содержит timezone, считает его временем UTC. Если timezone
    указан, переводит значение в UTC.

    Args:
        value: Дата и время для нормализации.

    Returns:
        Дата и время с timezone UTC.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    """Преобразует значение в JSON-совместимый формат.

    Поддерживает примитивы, UUID, datetime, Enum, Mapping и Iterable. Для
    неподдерживаемых объектов возвращает строковое представление.

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


# Глобальный singleton-экземпляр сервиса скачиваний.
_downloads_service: DownloadsService | None = None


def get_downloads_service(
    *,
    settings: Settings | None = None,
    uow_factory: UnitOfWorkFactory | None = None,
    storage_service: StorageService | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
) -> DownloadsService:
    """Возвращает экземпляр сервиса скачиваний.

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
        Экземпляр DownloadsService.
    """

    global _downloads_service
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
        return DownloadsService(
            settings=settings,
            uow_factory=uow_factory,
            storage_service=storage_service,
            access_service=access_service,
            audit_service=audit_service,
        )
    if _downloads_service is None:
        _downloads_service = DownloadsService()
    return _downloads_service

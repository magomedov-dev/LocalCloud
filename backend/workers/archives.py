from __future__ import annotations

import asyncio
import os
import posixpath
import shutil
import tempfile
import zipfile
from inspect import isawaitable
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from core.config import get_settings
from database.exceptions import DatabaseConnectionError
from database.models.enums import NodeType, StorageObjectStatus
from services.exceptions import ServiceError
from storage.exceptions import StorageConnectionError, StorageError
from workers.exceptions import WorkerTaskHandlerError
from workers.tasks import (
    failure_result,
    optional_payload_value,
    retry_result,
    success_result,
)
from workers.types import WorkerTaskExecutionContext, WorkerTaskExecutionResult


async def create_folder_archive_handler(
    context: WorkerTaskExecutionContext,
) -> WorkerTaskExecutionResult:
    """Создаёт ZIP-архив папки в фоновом режиме.

    Обработчик поддерживает два режима работы: архивацию одной папки и
    bulk-архивацию произвольного набора узлов, если в payload передан список
    `node_ids`. Для одиночной папки обработчик проверяет права пользователя,
    собирает список файлов, создаёт ZIP-архив и сохраняет его в bucket архивов.

    Args:
        context: Контекст выполнения фоновой задачи.

    Returns:
        Результат выполнения задачи с данными созданного архива или
        информацией об ошибке.
    """

    folder_node_snapshot: dict[str, Any] | None = None
    file_nodes_by_id: dict[UUID, dict[str, Any]] = {}
    file_rows: list[dict[str, Any]] = []
    task_meta: dict[str, Any] | None = None
    try:
        payload = context.payload
        async with context.uow_factory() as uow:
            task_row = await uow.tasks.get_required_by_id(context.task_id)
            task_meta = {
                "id": getattr(task_row, "id", None),
                "related_entity_id": getattr(task_row, "related_entity_id", None),
                "created_by": getattr(task_row, "created_by", None),
            }

        # Массовый архив: полезная нагрузка содержит явный список идентификаторов узлов (набор
        # файлов и папок), а не одну папку.
        if hasattr(payload, "get") and payload.get("node_ids"):
            return await _run_bulk_archive(context, payload, task_meta=task_meta)

        folder_node_id = _resolve_folder_node_id(payload, task_meta=task_meta)
        requested_by = _resolve_requested_by(payload, task_meta=task_meta)
        archive_name = optional_payload_value(
            payload,
            "archive_name",
            expected_type=str,
            default=None,
        )

        ready_result = await _try_service_archive(
            context, folder_node_id, requested_by, archive_name
        )
        if ready_result is not None:
            return ready_result

        async with context.uow_factory() as uow:
            folder_node = await uow.nodes.get_required_by_id(folder_node_id)
            descendants = await uow.nodes.get_descendants(
                node_id=folder_node_id,
                include_self=False,
                include_deleted=False,
            )
            file_nodes = [
                node for node in descendants if node.node_type == NodeType.FILE
            ]
            file_node_ids = [node.id for node in file_nodes]
            files = await uow.files.list_by_node_ids(
                file_node_ids,
                include_deleted_nodes=False,
            )
            folder_node_snapshot = {
                "id": getattr(folder_node, "id", None),
                "node_type": getattr(folder_node, "node_type", None),
                "path": str(getattr(folder_node, "path", "") or ""),
            }
            file_nodes_by_id = {
                node.id: {
                    "id": getattr(node, "id", None),
                    "path": str(getattr(node, "path", "") or ""),
                    "name": str(getattr(node, "name", "") or ""),
                }
                for node in file_nodes
            }
            file_rows = [
                {
                    "id": getattr(file_row, "id", None),
                    "node_id": getattr(file_row, "node_id", None),
                    "storage_status": getattr(file_row, "storage_status", None),
                    "storage_bucket": getattr(file_row, "storage_bucket", None),
                    "storage_key": getattr(file_row, "storage_key", None),
                    "size_bytes": getattr(file_row, "size_bytes", None),
                }
                for file_row in files
            ]

        if folder_node_snapshot is None:
            return failure_result(
                error_message="Указанная папка не найдена.",
                error_code="folder_not_found",
                result_data={"folder_node_id": str(folder_node_id)},
                retry=False,
                progress_percent=0,
            )

        if folder_node_snapshot.get("node_type") != NodeType.FOLDER:
            return failure_result(
                error_message="Указанный узел не является папкой.",
                error_code="node_is_not_folder",
                result_data={"folder_node_id": str(folder_node_id)},
                retry=False,
                progress_percent=0,
            )

        can_read = await context.services.access.can_read_node(
            node_id=folder_node_id,
            user_id=requested_by,
        )
        can_download = await context.services.access.can_download_node(
            node_id=folder_node_id,
            user_id=requested_by,
        )
        if not (can_read and can_download):
            return failure_result(
                error_message="Недостаточно прав для архивации папки.",
                error_code="permission_denied",
                result_data={
                    "folder_node_id": str(folder_node_id),
                    "requested_by": str(requested_by),
                },
                retry=False,
                progress_percent=0,
            )

        folder_root_path = str(folder_node_snapshot.get("path", "") or "")
        entries: list[tuple[str, dict[str, Any]]] = []
        for file_row in file_rows:
            node_id = file_row.get("node_id")
            if not isinstance(node_id, UUID):
                continue
            file_node = file_nodes_by_id.get(node_id)
            if file_node is None:
                continue
            member = _safe_archive_member_path(
                folder_root_path=folder_root_path,
                file_node_path=str(file_node.get("path", "") or ""),
                fallback_name=str(file_node.get("name", "") or file_row.get("id")),
            )
            entries.append((member, file_row))

        result_data = await _build_zip_and_store(
            context,
            entries,
            requested_by=requested_by,
            archive_name=archive_name,
            extra_metadata={"folder_node_id": str(folder_node_id)},
        )
        result_data["folder_node_id"] = str(folder_node_id)
        return success_result(result_data=result_data, progress_percent=100)

    except (StorageConnectionError, DatabaseConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка при создании архива папки.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except ArchiveLimitExceededError as exc:
        return failure_result(
            error_message=str(exc),
            error_code=exc.error_code,
            result_data={"reason": str(exc), **exc.details},
            retry=False,
            progress_percent=0,
        )
    except (ServiceError, StorageError) as exc:
        return failure_result(
            error_message="Ошибка создания архива папки.",
            error_code="create_folder_archive_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка создания архива папки.",
            error_code="unexpected_create_folder_archive_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


async def _run_bulk_archive(
    context: WorkerTaskExecutionContext,
    payload: Any,
    *,
    task_meta: dict[str, Any] | None,
) -> WorkerTaskExecutionResult:
    """Создаёт ZIP-архив из произвольного набора узлов.

    Файлы добавляются в корень архива под своим именем. Папки добавляются со
    всем содержимым с сохранением относительной структуры под именем папки.

    Args:
        context: Контекст выполнения фоновой задачи.
        payload: Payload задачи со списком `node_ids` и опциональным именем
            архива.
        task_meta: Метаданные задачи, используемые как fallback для
            определения пользователя.

    Returns:
        Результат выполнения задачи с данными созданного архива или
        информацией об ошибке.
    """

    try:
        requested_by = _resolve_requested_by(payload, task_meta=task_meta)
        archive_name = optional_payload_value(
            payload, "archive_name", expected_type=str, default=None
        )

        raw_node_ids = payload.get("node_ids") or []
        node_ids: list[UUID] = []
        for raw in raw_node_ids:
            if isinstance(raw, UUID):
                node_ids.append(raw)
            elif isinstance(raw, str) and raw.strip():
                try:
                    node_ids.append(UUID(raw.strip()))
                except ValueError:
                    continue

        if not node_ids:
            return failure_result(
                error_message="В payload отсутствуют корректные node_ids.",
                error_code="missing_node_ids",
                result_data={},
                retry=False,
                progress_percent=0,
            )

        # Собирать записи (zip_member_path, file_row) по всем выбранным узлам.
        entries: list[tuple[str, dict[str, Any]]] = []

        async with context.uow_factory() as uow:
            # 1 запрос для всех выбранных узлов (был один get_required_by_id для каждого узла).
            selected_nodes = await uow.nodes.get_nodes_by_ids(
                node_ids, include_deleted=False
            )

            # файл-идентификатор узла -> путь к нему внутри архива. setdefault сохраняет присвоение
            # first, поэтому непосредственно выбранный файл остается в корневом каталоге, даже если
            # если он также находится в другой выбранной папке; порядок вставки следующий.
            # сохранено (сначала прямые файлы, затем потомки папок).
            member_by_file_node_id: dict[UUID, str] = {}

            for node in selected_nodes:
                if node.node_type == NodeType.FILE:
                    member_by_file_node_id.setdefault(
                        node.id, str(getattr(node, "name", "") or str(node.id))
                    )

            # Потомкам по-прежнему требуется один запрос на папку (API пакетных потомков отсутствует).
            for node in selected_nodes:
                if node.node_type != NodeType.FOLDER:
                    continue
                folder_root_path = str(getattr(node, "path", "") or "")
                folder_name = str(getattr(node, "name", "") or str(node.id))
                descendants = await uow.nodes.get_descendants(
                    node_id=node.id, include_self=False, include_deleted=False
                )
                for child in descendants:
                    if child.node_type != NodeType.FILE:
                        continue
                    if child.id in member_by_file_node_id:
                        continue
                    relative = _safe_archive_member_path(
                        folder_root_path=folder_root_path,
                        file_node_path=str(getattr(child, "path", "") or ""),
                        fallback_name=str(getattr(child, "name", "") or ""),
                    )
                    member_by_file_node_id[child.id] = f"{folder_name}/{relative}"

            # 1 запрос для ВСЕХ строк файла (прямой выбор + потомки папок).
            file_node_ids = list(member_by_file_node_id.keys())
            file_rows = await uow.files.list_by_node_ids(
                file_node_ids, include_deleted_nodes=False
            )
            file_row_by_node_id = {getattr(f, "node_id", None): f for f in file_rows}

            for nid in file_node_ids:
                file_row = file_row_by_node_id.get(nid)
                if file_row is None:
                    continue
                entries.append((member_by_file_node_id[nid], _file_row_dict(file_row)))

        result_data = await _build_zip_and_store(
            context,
            entries,
            requested_by=requested_by,
            archive_name=archive_name,
        )
        return success_result(result_data=result_data, progress_percent=100)

    except (StorageConnectionError, DatabaseConnectionError) as exc:
        return retry_result(
            error_message="Временная ошибка при создании архива.",
            error_code="temporary_unavailable",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
        )
    except ArchiveLimitExceededError as exc:
        return failure_result(
            error_message=str(exc),
            error_code=exc.error_code,
            result_data={"reason": str(exc), **exc.details},
            retry=False,
            progress_percent=0,
        )
    except (ServiceError, StorageError) as exc:
        return failure_result(
            error_message="Ошибка создания архива.",
            error_code="create_bulk_archive_failed",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )
    except Exception as exc:
        return failure_result(
            error_message="Непредвиденная ошибка создания архива.",
            error_code="unexpected_create_bulk_archive_error",
            result_data={"reason": str(exc), "error_type": exc.__class__.__name__},
            retry=False,
            progress_percent=0,
        )


def _file_row_dict(file_row: Any) -> dict[str, Any]:
    """Создаёт снимок storage-полей файла для использования вне Unit of Work.

    Args:
        file_row: ORM-объект или другой объект файла со storage-полями.

    Returns:
        Словарь с идентификатором node и данными storage-объекта.
    """

    return {
        "node_id": getattr(file_row, "node_id", None),
        "storage_status": getattr(file_row, "storage_status", None),
        "storage_bucket": getattr(file_row, "storage_bucket", None),
        "storage_key": getattr(file_row, "storage_key", None),
        "size_bytes": getattr(file_row, "size_bytes", None),
    }


def _dedupe_member(member_path: str, seen: set[str]) -> str:
    """Гарантирует уникальность пути внутри ZIP.

    Если путь уже был добавлен в архив, функция добавляет к имени файла
    числовой суффикс вида `(N)`.

    Args:
        member_path: Исходный путь файла внутри ZIP.
        seen: Множество уже использованных путей внутри ZIP.

    Returns:
        Уникальный путь файла внутри ZIP.
    """

    if member_path not in seen:
        seen.add(member_path)
        return member_path

    base, dot, ext = member_path.rpartition(".")
    counter = 1
    while True:
        if dot:
            candidate = f"{base} ({counter}).{ext}"
        else:
            candidate = f"{member_path} ({counter})"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
        counter += 1


# Параметры архива читаются из единой конфигурации (core.config): дефолты-литералы
# лежат в core.constants.ArchiveConstants и подобраны под маленький хост, а через
# .env (см. .env.example, секция «Archives») их можно переопределить под более
# мощный сервер. Лимиты нужны, чтобы сборка ZIP не выела диск под временный файл и
# не загрузила в память слишком большой список записей.
_archive_settings = get_settings().archives

# Размер фрагмента потоковой передачи объекта в ZIP. Максимальный объём памяти на
# файл — примерно один фрагмент + буфер, а не весь объект целиком.
_ARCHIVE_STREAM_CHUNK = _archive_settings.stream_chunk_bytes
_ARCHIVE_MAX_FILES = _archive_settings.max_files
_ARCHIVE_MAX_TOTAL_BYTES = _archive_settings.max_total_bytes
# Свободного места на диске должно быть с запасом: ZIP_DEFLATED обычно ≤ суммы
# источников, но для уже сжатых данных размер примерно равен исходному.
_ARCHIVE_DISK_SAFETY_FACTOR = _archive_settings.disk_safety_factor


class ArchiveLimitExceededError(Exception):
    """Архив превышает лимиты (число файлов, общий размер или место на диске)."""

    def __init__(
        self, message: str, *, error_code: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


async def _stream_object_into_zip(
    context: WorkerTaskExecutionContext,
    zip_handle: zipfile.ZipFile,
    *,
    bucket: str,
    object_key: str,
    member_path: str,
) -> None:
    """Стримит storage-объект в ZIP-запись без полной буферизации.

    Чтение из storage и запись в ZIP являются блокирующими операциями, поэтому
    выполняются в отдельном потоке. Файлы архивируются последовательно, и
    `zip_handle` в каждый момент используется только одним потоком.

    Args:
        context: Контекст выполнения фоновой задачи.
        zip_handle: Открытый ZIP-файл для записи.
        bucket: Имя bucket, из которого нужно прочитать объект.
        object_key: Ключ объекта в storage.
        member_path: Путь записи внутри ZIP-архива.
    """

    response = await context.storage_service.objects.get_object_stream(
        bucket=bucket,
        object_key=object_key,
    )
    try:
        await asyncio.to_thread(_write_stream_to_zip, zip_handle, response, member_path)
    finally:
        await asyncio.to_thread(_safe_close_response, response)


def _write_stream_to_zip(
    zip_handle: zipfile.ZipFile, response: Any, member_path: str
) -> None:
    """Копирует поток ответа storage в ZIP-запись по частям.

    Args:
        zip_handle: Открытый ZIP-файл для записи.
        response: Потоковый ответ storage-клиента с методом `read`.
        member_path: Путь записи внутри ZIP-архива.
    """

    with zip_handle.open(member_path, mode="w") as entry:
        while True:
            chunk = response.read(_ARCHIVE_STREAM_CHUNK)
            if not chunk:
                break
            entry.write(chunk)


def _safe_close_response(response: Any) -> None:
    """Закрывает storage-ответ и возвращает соединение в пул.

    Ошибки закрытия намеренно подавляются, чтобы не перекрывать исходную
    ошибку чтения или записи архива.

    Args:
        response: Потоковый ответ storage-клиента.
    """

    for method_name in ("close", "release_conn"):
        method = getattr(response, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass


def _enforce_archive_limits(entries: list[tuple[str, dict[str, Any]]]) -> None:
    """Проверяет лимиты архива до начала сборки.

    Защищает от заполнения диска временным ZIP и от загрузки в память слишком
    большого списка записей. Размер ZIP оценивается сверху суммой исходных
    файлов (ZIP_DEFLATED обычно ≤ исходного).

    Args:
        entries: Отфильтрованные доступные записи `(путь_в_архиве, снимок_файла)`.

    Raises:
        ArchiveLimitExceededError: Если превышен лимит файлов/размера или не
            хватает места на диске.
    """

    file_count = len(entries)
    if file_count > _ARCHIVE_MAX_FILES:
        raise ArchiveLimitExceededError(
            f"Слишком много файлов для архивации: {file_count} > {_ARCHIVE_MAX_FILES}.",
            error_code="archive_too_many_files",
            details={"file_count": file_count, "max_files": _ARCHIVE_MAX_FILES},
        )

    total_source_bytes = sum(int(fr.get("size_bytes") or 0) for _, fr in entries)
    if total_source_bytes > _ARCHIVE_MAX_TOTAL_BYTES:
        raise ArchiveLimitExceededError(
            "Суммарный размер файлов превышает лимит архива.",
            error_code="archive_too_large",
            details={
                "total_source_bytes": total_source_bytes,
                "max_total_bytes": _ARCHIVE_MAX_TOTAL_BYTES,
            },
        )

    needed = int(total_source_bytes * _ARCHIVE_DISK_SAFETY_FACTOR)
    try:
        free = shutil.disk_usage(tempfile.gettempdir()).free
    except OSError:
        free = None
    if free is not None and free < needed:
        raise ArchiveLimitExceededError(
            "Недостаточно места на диске для создания архива.",
            error_code="archive_insufficient_disk",
            details={"needed_bytes": needed, "free_bytes": free},
        )


async def _build_zip_and_store(
    context: WorkerTaskExecutionContext,
    entries: list[tuple[str, dict[str, Any]]],
    *,
    requested_by: UUID,
    archive_name: str | None,
    extra_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Собирает ZIP-архив и сохраняет его в bucket архивов.

    Недоступные storage-объекты пропускаются. Дублирующиеся пути внутри архива
    получают числовой суффикс. Каждый объект стримится в ZIP без загрузки всего
    файла в память. Временный ZIP-файл удаляется после завершения операции.

    Args:
        context: Контекст выполнения фоновой задачи.
        entries: Список пар `(путь_в_архиве, снимок_файла)`.
        requested_by: Идентификатор пользователя, запросившего архив.
        archive_name: Пользовательское имя архива.
        extra_metadata: Дополнительные metadata-поля для storage-объекта
            архива.

    Returns:
        Данные созданного архива: bucket, ключ объекта, размер архива и
        количество добавленных файлов.
    """

    temp_zip_path: str | None = None
    try:
        archive_bucket = context.storage_service.default_archives_bucket
        archive_key = context.storage_service.build_archive_key(
            user_id=requested_by,
            task_id=context.task_id,
            extension="zip",
        )

        # Отбираем только реально доступные объекты и заранее проверяем лимиты —
        # до создания временного файла, чтобы не начинать тяжёлую работу впустую.
        available_entries = [
            (member_path, file_row)
            for member_path, file_row in entries
            if file_row.get("storage_status") == StorageObjectStatus.AVAILABLE
            and file_row.get("storage_bucket")
            and file_row.get("storage_key")
        ]
        _enforce_archive_limits(available_entries)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            temp_zip_path = tmp_file.name

        files_count = 0
        seen_members: set[str] = set()
        with zipfile.ZipFile(
            temp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zip_handle:
            for member_path, file_row in available_entries:
                unique_member = _dedupe_member(member_path, seen_members)
                await _stream_object_into_zip(
                    context,
                    zip_handle,
                    bucket=str(file_row["storage_bucket"]),
                    object_key=str(file_row["storage_key"]),
                    member_path=unique_member,
                )
                files_count += 1

        archive_size_bytes = os.path.getsize(temp_zip_path)
        metadata: dict[str, str] = {
            "task_id": str(context.task_id),
            "requested_by": str(requested_by),
            "archive_name": str(archive_name).strip()
            if isinstance(archive_name, str)
            else "",
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        # put_object получает файловый дескриптор и отдаёт его MinIO SDK как
        # есть: загрузка идёт частями (~part_size), а не чтением всего архива в
        # RAM. Пик памяти на этом шаге ограничен размером части, а не размером
        # архива.
        with open(temp_zip_path, "rb") as archive_stream:
            await context.storage_service.objects.put_object(
                bucket=archive_bucket,
                object_key=archive_key,
                data=archive_stream,
                length=archive_size_bytes,
                content_type="application/zip",
                metadata=metadata,
            )

        return {
            "archive_bucket": archive_bucket,
            "archive_key": archive_key,
            "archive_size_bytes": int(archive_size_bytes),
            "files_count": int(files_count),
        }
    finally:
        if temp_zip_path and os.path.exists(temp_zip_path):
            try:
                os.remove(temp_zip_path)
            except OSError:
                pass


async def _try_service_archive(
    context: WorkerTaskExecutionContext,
    folder_node_id: UUID,
    requested_by: UUID,
    archive_name: str | None,
) -> WorkerTaskExecutionResult | None:
    """Пытается создать архив через сервис downloads.

    Проверяет наличие совместимого метода в `context.services.downloads`.
    Если сервис недоступен или не поддерживает подходящий метод, возвращает
    `None`, чтобы вызывающий код выполнил локальную сборку архива.

    Args:
        context: Контекст выполнения фоновой задачи.
        folder_node_id: Идентификатор папки для архивации.
        requested_by: Идентификатор пользователя, запросившего архив.
        archive_name: Пользовательское имя архива.

    Returns:
        Успешный результат выполнения задачи, если архив был создан сервисом,
        иначе `None`.
    """

    downloads_service = getattr(context.services, "downloads", None)
    if downloads_service is None:
        return None

    candidate_methods = (
        "create_folder_archive",
        "build_folder_archive",
        "generate_folder_archive",
    )
    for method_name in candidate_methods:
        method = getattr(downloads_service, method_name, None)
        if not callable(method):
            continue
        try:
            maybe_result = method(
                folder_node_id=folder_node_id,
                requested_by=requested_by,
                task_id=context.task_id,
                archive_name=archive_name,
            )
            result = await maybe_result if isawaitable(maybe_result) else maybe_result
            if isinstance(result, dict):
                return success_result(
                    result_data={
                        "archive_bucket": result.get("archive_bucket"),
                        "archive_key": result.get("archive_key"),
                        "archive_size_bytes": result.get("archive_size_bytes"),
                        "files_count": result.get("files_count"),
                        "folder_node_id": str(folder_node_id),
                    },
                    progress_percent=100,
                )
        except TypeError:
            continue
    return None


def _safe_archive_member_path(
    *,
    folder_root_path: str,
    file_node_path: str,
    fallback_name: str,
) -> str:
    """Формирует безопасный относительный путь файла внутри ZIP.

    Путь нормализуется, приводится к POSIX-формату и проверяется на попытки
    path traversal или использование абсолютного пути.

    Args:
        folder_root_path: Путь корневой папки архивации.
        file_node_path: Полный путь файлового узла.
        fallback_name: Имя файла, используемое если относительный путь нельзя
            получить из `file_node_path`.

    Returns:
        Безопасный относительный путь файла внутри ZIP.

    Raises:
        ValueError: Если сформированный путь небезопасен.
    """

    root = _normalize_fs_path(folder_root_path)
    file_path = _normalize_fs_path(file_node_path)

    if root and file_path.startswith(f"{root}/"):
        relative = file_path[len(root) + 1 :]
    elif file_path == root:
        relative = fallback_name
    else:
        relative = file_path.rsplit("/", maxsplit=1)[-1] or fallback_name

    normalized = posixpath.normpath(relative.replace("\\", "/").strip("/"))
    if (
        normalized in {"", ".", ".."}
        or normalized.startswith("../")
        or "/../" in normalized
    ):
        raise ValueError(
            "Обнаружена попытка path traversal при формировании ZIP-архива."
        )

    if PurePosixPath(normalized).is_absolute():
        raise ValueError("Путь внутри ZIP должен быть относительным.")

    return normalized


def _normalize_fs_path(value: str) -> str:
    """Нормализует путь файлового узла к POSIX-представлению.

    Args:
        value: Исходный путь файлового узла.

    Returns:
        Нормализованный путь без завершающего слеша.
    """

    normalized = value.replace("\\", "/").strip()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.rstrip("/")


def _payload_uuid_alias(payload: Any, *keys: str) -> UUID:
    """Извлекает UUID из первого найденного ключа payload.

    Args:
        payload: Payload задачи с методом `get`.
        *keys: Имена ключей, по которым нужно искать UUID.

    Returns:
        Найденный UUID.

    Raises:
        WorkerTaskHandlerError: Если payload не поддерживает доступ по ключу,
            значение UUID некорректно или ни один из ключей не содержит UUID.
    """

    if not hasattr(payload, "get"):
        raise WorkerTaskHandlerError(
            "Payload задачи должен поддерживать доступ по ключу.",
            operation="require_payload_value",
        )

    for key in keys:
        value = payload.get(key)
        if isinstance(value, UUID):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return UUID(value.strip())
            except ValueError as exc:
                raise WorkerTaskHandlerError(
                    "Payload содержит некорректный UUID.",
                    operation="require_payload_value",
                    details={"key": key, "value": value},
                    cause=exc,
                ) from exc

    raise WorkerTaskHandlerError(
        "В payload отсутствует обязательный UUID.",
        operation="require_payload_value",
        details={"keys": list(keys)},
    )


def _resolve_folder_node_id(payload: Any, *, task_meta: dict[str, Any] | None) -> UUID:
    """Определяет UUID папки из payload или связи задачи.

    Args:
        payload: Payload задачи.
        task_meta: Метаданные задачи с возможным `related_entity_id`.

    Returns:
        UUID папки для архивации.

    Raises:
        WorkerTaskHandlerError: Если UUID папки не найден.
    """

    try:
        return _payload_uuid_alias(payload, "folder_node_id", "folder_id")
    except WorkerTaskHandlerError:
        related_entity_id = (
            None if task_meta is None else task_meta.get("related_entity_id")
        )
        if isinstance(related_entity_id, UUID):
            return related_entity_id
        raise


def _resolve_requested_by(payload: Any, *, task_meta: dict[str, Any] | None) -> UUID:
    """Определяет пользователя, запросившего создание архива.

    Сначала пытается получить пользователя из payload по ключам `requested_by`
    или `user_id`. Если значение отсутствует, использует `created_by` из
    метаданных задачи.

    Args:
        payload: Payload задачи.
        task_meta: Метаданные задачи с возможным `created_by`.

    Returns:
        UUID пользователя, запросившего архив.

    Raises:
        WorkerTaskHandlerError: Если пользователя не удалось определить или
            payload содержит некорректный UUID пользователя.
    """

    if hasattr(payload, "get"):
        raw_value = payload.get("requested_by") or payload.get("user_id")
        if isinstance(raw_value, UUID):
            return raw_value
        if isinstance(raw_value, str) and raw_value.strip():
            try:
                return UUID(raw_value.strip())
            except ValueError as exc:
                raise WorkerTaskHandlerError(
                    "Payload содержит некорректный идентификатор пользователя.",
                    operation="require_payload_value",
                    details={"key": "requested_by", "value": raw_value},
                    cause=exc,
                ) from exc

    created_by = None if task_meta is None else task_meta.get("created_by")
    if isinstance(created_by, UUID):
        return created_by

    raise WorkerTaskHandlerError(
        "Не удалось определить пользователя, запросившего архив.",
        operation="require_payload_value",
        details={"task_id": str("" if task_meta is None else task_meta.get("id", ""))},
    )

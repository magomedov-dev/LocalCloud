from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Literal, cast
from uuid import UUID

from core.config import Settings, get_settings
from core.logging import get_logger
from database import DatabaseError, UnitOfWorkFactory, create_unit_of_work_factory
from database.models.enums import (
    AuditAction,
    AuditResourceType,
    AuditResult,
    BackgroundTaskStatus,
    BackgroundTaskType,
    NodeType,
    PublicLinkStatus,
    StorageObjectStatus,
)
from database.models.filesystem import File, FileSystemNode
from database.models.links import PublicLink
from schemas.common import PageMeta, PageResponse
from schemas.public_links import (
    PublicLinkAccessRequest,
    PublicLinkAccessResponse,
    PublicLinkCreateRequest,
    PublicLinkDownloadResponse,
    PublicLinkFolderArchiveResponse,
    PublicLinkListItem,
    PublicLinkPublicRead,
    PublicLinkQueryParams,
    PublicLinkRead,
    PublicLinkRevokeRequest,
    PublicLinkUpdateRequest,
)
from core.preview_mime import preview_content_type
from security.password import hash_password, verify_password
from security.permissions import PermissionAction
from services.access import AccessService, get_access_service
from services.audit import AuditService, get_audit_service
from services.exceptions import (
    NotFoundServiceError,
    PermissionServiceError,
    PublicLinkServiceError,
    ServiceError,
    ValidationServiceError,
    service_error_from_database,
    service_error_from_exception,
    service_error_from_storage,
)
from storage import (
    StorageError,
    StoragePresignedUrl,
    StorageService,
    get_storage_service,
)

logger = get_logger("services.public_links")

SERVICE_NAME = "public_links"
MAX_PAGE_LIMIT = 200
DEFAULT_TOKEN_BYTES = 18

PublicLinkSortField = Literal[
    "created_at",
    "expires_at",
    "last_accessed_at",
    "last_downloaded_at",
    "last_uploaded_at",
    "download_count",
    "view_count",
    "upload_count",
    "status",
]


class PublicLinksService:
    """Сервис бизнес-логики для публичных ссылок.

    Управляет публичными ссылками на файлы и папки: создает, читает, обновляет,
    отзывает, проверяет доступ и создает ссылки для публичного скачивания.
    Для операций владельца проверяет права через AccessService, для скачивания
    использует StorageService, а значимые события записывает через AuditService.

    Attributes:
        settings: Настройки приложения.
        uow_factory: Фабрика Unit of Work для работы с базой данных.
        access_service: Сервис проверки доступа к узлам файловой системы.
        audit_service: Сервис записи событий аудита.
        storage_service: Сервис хранилища для создания ссылок скачивания.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        uow_factory: UnitOfWorkFactory | None = None,
        access_service: AccessService | None = None,
        audit_service: AuditService | None = None,
        storage_service: StorageService | None = None,
    ) -> None:
        """Инициализирует сервис публичных ссылок.

        Если зависимости не переданы явно, создает их через стандартные фабрики
        и функции получения сервисов.

        Args:
            settings: Настройки приложения. Если None, используются стандартные
                настройки.
            uow_factory: Фабрика Unit of Work. Если None, создается стандартная
                фабрика.
            access_service: Сервис проверки доступа. Если None, создается
                стандартный сервис доступа.
            audit_service: Сервис аудита. Если None, создается стандартный сервис
                аудита.
            storage_service: Сервис хранилища. Если None, создается стандартный
                сервис хранилища.
        """

        self.settings = settings or get_settings()
        self.uow_factory = uow_factory or create_unit_of_work_factory()
        self.access_service = access_service or get_access_service(
            uow_factory=self.uow_factory
        )
        self.audit_service = audit_service or get_audit_service(
            uow_factory=self.uow_factory
        )
        self.storage_service = storage_service or get_storage_service(
            settings=self.settings.storage
        )

    async def create_link(
        self,
        data: PublicLinkCreateRequest,
        *,
        actor_id: UUID,
    ) -> PublicLinkRead:
        """Создает публичную ссылку на файл или папку.

        Проверяет, что actor_id имеет право делиться указанным узлом, что тип узла
        поддерживается, генерирует уникальный токен и при необходимости хеширует
        пароль. После создания ссылки записывает событие аудита.

        Args:
            data: Данные для создания публичной ссылки.
            actor_id: Идентификатор пользователя, создающего ссылку.

        Returns:
            Данные созданной публичной ссылки.

        Raises:
            PermissionServiceError: Если пользователь не имеет права делиться узлом.
            ValidationServiceError: Если тип узла не поддерживает публичные ссылки.
            PublicLinkServiceError: Если не удалось сгенерировать уникальный токен.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_link"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                node = await self.access_service.get_accessible_node(
                    node_id=data.node_id,
                    user_id=actor_id,
                    action=PermissionAction.SHARE,
                    allow_deleted=False,
                    allow_public=False,
                    uow=uow,
                )
                _ensure_supported_node_type(node, operation=operation)

                token = await self._generate_unique_token(uow)
                password_hash: str | None = None
                if data.password is not None:
                    password_hash = hash_password(data.password)

                link = await uow.links.create_link(
                    node_id=node.id,
                    token=token,
                    created_by=actor_id,
                    password_hash=password_hash,
                    permission_type=data.permission_type,
                    status=PublicLinkStatus.ACTIVE,
                    expires_at=data.expires_at,
                    max_downloads=data.max_downloads,
                    description=data.description,
                    is_active=True,
                    flush=True,
                    refresh=True,
                    check_duplicate_token=True,
                )
                snapshot = _link_snapshot(link)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_event(
                action=AuditAction.PUBLIC_LINK_CREATED,
                actor_id=actor_id,
                link_snapshot=snapshot,
                message="Создана общедоступная ссылка.",
            )
            return PublicLinkRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать общедоступную ссылку.",
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc,
                service=SERVICE_NAME,
                operation=operation,
                message="Не удалось создать общедоступную ссылку.",
            ) from exc

    async def get_link(self, link_id: UUID, *, actor_id: UUID) -> PublicLinkRead:
        """Возвращает публичную ссылку по идентификатору.

        Загружает ссылку и проверяет, что actor_id имеет право управлять доступом
        к связанному узлу.

        Args:
            link_id: Идентификатор публичной ссылки.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Данные найденной публичной ссылки.

        Raises:
            PermissionServiceError: Если пользователь не имеет права делиться
                связанным узлом.
            ServiceError: Если ссылка не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "get_link"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_by_id(link_id)
                await self._require_owner_access(
                    uow=uow,
                    link=link,
                    actor_id=actor_id,
                    operation=operation,
                )
                snapshot = _link_snapshot(link)
            if snapshot is None:
                raise _empty_result_error(operation)
            return PublicLinkRead.model_validate(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def list_links(
        self,
        params: PublicLinkQueryParams,
        *,
        actor_id: UUID,
    ) -> PageResponse[PublicLinkListItem]:
        """Возвращает список публичных ссылок.

        Если в параметрах указан node_id, проверяет право actor_id управлять
        доступом к этому узлу и возвращает ссылки узла. Если node_id не указан,
        возвращает ссылки, созданные actor_id. Дополнительно фильтрует результат
        по наличию пароля.

        Args:
            params: Параметры поиска, фильтрации, сортировки и пагинации публичных
                ссылок.
            actor_id: Идентификатор пользователя, выполняющего запрос.

        Returns:
            Страница публичных ссылок и метаданные пагинации.

        Raises:
            PermissionServiceError: Если пользователь не имеет права делиться
                указанным узлом.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "list_links"
        limit = _limit(params.limit)
        offset = max(0, params.offset)
        sort_by = _normalize_sort_by(params.sort_by)
        direction: Literal["asc", "desc"] = "desc" if params.sort_desc else "asc"
        snapshots: list[dict[str, Any]] = []
        total = 0

        try:
            async with self.uow_factory() as uow:
                if params.node_id is not None:
                    await self.access_service.require_access(
                        node_id=params.node_id,
                        user_id=actor_id,
                        action=PermissionAction.SHARE,
                        allow_deleted=True,
                        allow_public=False,
                        uow=uow,
                    )
                    items = await uow.links.list_node_links(
                        node_id=params.node_id,
                        active_only=bool(params.is_active),
                        available_only=False,
                        permission_type=params.permission_type,
                        status=params.status,
                        offset=offset,
                        limit=limit,
                        sort_by=sort_by,
                        sort_direction=direction,
                    )
                    total = await uow.links.count_node_links(
                        node_id=params.node_id,
                        active_only=bool(params.is_active),
                    )
                else:
                    items = await uow.links.search_links(
                        query=params.query,
                        created_by=actor_id,
                        node_id=None,
                        permission_type=params.permission_type,
                        status=params.status,
                        active_only=bool(params.is_active),
                        available_only=False,
                        offset=offset,
                        limit=limit,
                        sort_by=sort_by,
                        sort_direction=direction,
                    )
                    total = await uow.links.count_user_links(
                        created_by=actor_id,
                        active_only=bool(params.is_active),
                    )
                snapshots = [_link_snapshot(item) for item in items]

            dto_items = [
                PublicLinkListItem.model_validate(snapshot)
                for snapshot in snapshots
                if _include_snapshot_by_password_filter(snapshot, params.has_password)
            ]
            return PageResponse(
                items=dto_items,
                meta=PageMeta(
                    total=total,
                    offset=offset,
                    limit=limit,
                    count=len(dto_items),
                ),
            )

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def update_link(
        self,
        link_id: UUID,
        data: PublicLinkUpdateRequest,
        *,
        actor_id: UUID,
    ) -> PublicLinkRead:
        """Обновляет публичную ссылку.

        Проверяет право actor_id управлять доступом к связанному узлу, затем
        обновляет тип разрешения, статус, срок действия, лимит скачиваний,
        описание, активность и пароль ссылки.

        Args:
            link_id: Идентификатор обновляемой публичной ссылки.
            data: Данные обновления публичной ссылки.
            actor_id: Идентификатор пользователя, выполняющего обновление.

        Returns:
            Данные обновленной публичной ссылки.

        Raises:
            PermissionServiceError: Если пользователь не имеет права делиться
                связанным узлом.
            ServiceError: Если ссылка не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "update_link"
        snapshot: dict[str, Any] | None = None

        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_by_id(link_id)
                await self._require_owner_access(
                    uow=uow,
                    link=link,
                    actor_id=actor_id,
                    operation=operation,
                )

                # В репозиторий передаём только реально изменяемые поля.
                # Неустановленные nullable-поля НЕ пробрасываем: у репозитория
                # свой sentinel _UNSET, и передача чужого sentinel ломала
                # частичное обновление (например, только пароль) в
                # _validate_max_downloads. Опуская такие поля, мы позволяем
                # репозиторию применить собственное значение «не изменять».
                update_kwargs: dict[str, Any] = {
                    "permission_type": data.permission_type,
                    "status": data.status,
                    "is_active": data.is_active,
                }

                if data.password is not None:
                    update_kwargs["password_hash"] = hash_password(data.password)
                elif data.clear_password:
                    update_kwargs["password_hash"] = None

                if "expires_at" in data.model_fields_set:
                    update_kwargs["expires_at"] = data.expires_at
                if "max_downloads" in data.model_fields_set:
                    update_kwargs["max_downloads"] = data.max_downloads
                if "description" in data.model_fields_set:
                    update_kwargs["description"] = data.description

                updated = await uow.links.update_link(
                    link,
                    flush=True,
                    refresh=True,
                    **update_kwargs,
                )
                snapshot = _link_snapshot(updated)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            return PublicLinkRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def revoke_link(
        self,
        link_id: UUID,
        data: PublicLinkRevokeRequest | None = None,
        *,
        actor_id: UUID,
    ) -> PublicLinkRead:
        """Отзывает публичную ссылку.

        Проверяет право actor_id управлять доступом к связанному узлу и переводит
        ссылку в отозванное состояние. Причина отзыва сохраняется, если передана.
        После успешного отзыва записывает событие аудита.

        Args:
            link_id: Идентификатор отзываемой публичной ссылки.
            data: Данные отзыва ссылки. Может быть None.
            actor_id: Идентификатор пользователя, выполняющего отзыв.

        Returns:
            Данные отозванной публичной ссылки.

        Raises:
            PermissionServiceError: Если пользователь не имеет права делиться
                связанным узлом.
            ServiceError: Если ссылка не найдена, произошла ошибка базы данных или
                непредвиденная ошибка сервиса.
        """

        operation = "revoke_link"
        snapshot: dict[str, Any] | None = None
        revoke_reason = data.revoke_reason if data is not None else None

        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_by_id(link_id)
                await self._require_owner_access(
                    uow=uow,
                    link=link,
                    actor_id=actor_id,
                    operation=operation,
                )
                revoked = await uow.links.revoke_link(
                    link,
                    revoked_by=actor_id,
                    reason=revoke_reason,
                    flush=True,
                    refresh=True,
                )
                snapshot = _link_snapshot(revoked)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)

            await self._safe_log_event(
                action=AuditAction.PUBLIC_LINK_REVOKED,
                actor_id=actor_id,
                link_snapshot=snapshot,
                message="Публичная ссылка была отменена.",
                metadata={"revoke_reason": revoke_reason},
            )
            return PublicLinkRead.model_validate(snapshot)

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def validate_access(
        self,
        data: PublicLinkAccessRequest,
    ) -> PublicLinkAccessResponse:
        """Проверяет доступ к публичной ссылке.

        Загружает доступную ссылку по токену, проверяет возможность просмотра и,
        если у ссылки есть пароль, валидирует переданный пароль. При успешной
        проверке регистрирует просмотр и записывает событие аудита.

        Args:
            data: Данные публичного доступа, включая токен и опциональный пароль.

        Returns:
            Результат проверки доступа. При необходимости содержит признак, что
            требуется пароль, или публичные данные ссылки.

        Raises:
            PublicLinkServiceError: Если ссылка недоступна для просмотра.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "validate_access"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_available_link_by_token(data.token)
                _ensure_public_access_allowed(link, operation=operation)

                if link.password_hash:
                    if data.password is None:
                        return PublicLinkAccessResponse(
                            allowed=False,
                            link=None,
                            requires_password=True,
                            message="Требуется пароль.",
                        )
                    if not verify_password(data.password, link.password_hash):
                        await self._safe_log_security_password_failed(
                            link=link, operation=operation
                        )
                        return PublicLinkAccessResponse(
                            allowed=False,
                            link=None,
                            requires_password=True,
                            message="Неверный пароль.",
                        )

                await uow.links.register_view(link, flush=True, refresh=True)
                snapshot = _link_snapshot(link)
                await uow.commit()

            if snapshot is None:
                raise _empty_result_error(operation)
            await self._safe_log_event(
                action=AuditAction.PUBLIC_LINK_OPENED,
                actor_id=None,
                link_snapshot=snapshot,
                message="Открыта общедоступная ссылка.",
            )
            return PublicLinkAccessResponse(
                allowed=True,
                link=PublicLinkPublicRead.model_validate(snapshot),
                requires_password=False,
                message=None,
            )

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def get_public_link(self, token: str) -> PublicLinkPublicRead:
        """Возвращает публичные данные ссылки по токену без проверки пароля.

        Метод используется для публичной карточки ссылки до ввода пароля.

        Args:
            token: Публичный токен ссылки.

        Returns:
            Публичные данные ссылки без внутренних полей.
        """

        operation = "get_public_link"
        snapshot: dict[str, Any] | None = None
        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_available_link_by_token(token)
                _ensure_public_access_allowed(link, operation=operation)
                snapshot = _link_snapshot(link)
            if snapshot is None:
                raise _empty_result_error(operation)
            return PublicLinkPublicRead.model_validate(snapshot)
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def create_public_download_url(
        self,
        data: PublicLinkAccessRequest,
    ) -> PublicLinkDownloadResponse:
        """Создает URL для публичного скачивания файла.

        Загружает доступную ссылку по токену, проверяет возможность скачивания,
        валидирует пароль, убеждается, что ссылка указывает на файл, проверяет
        доступность файлового объекта в хранилище и создает предварительно
        подписанный URL для скачивания.

        Args:
            data: Данные публичного доступа, включая токен и опциональный пароль.

        Returns:
            Ответ с предварительно подписанным URL, сроком действия, HTTP-методом,
            заголовками и метаданными файла.

        Raises:
            PublicLinkServiceError: Если ссылка недоступна для скачивания или файл
                недоступен в хранилище.
            PermissionServiceError: Если пароль отсутствует или неверен.
            ValidationServiceError: Если публичное скачивание запрошено для папки
                или другого неподдерживаемого типа узла.
            StorageError: Если сервис хранилища не смог создать URL.
            ServiceError: Если произошла ошибка базы данных или непредвиденная
                ошибка сервиса.
        """

        operation = "create_public_download_url"
        link_snapshot: dict[str, Any] | None = None
        node: FileSystemNode | None = None
        file: File | None = None
        presigned: StoragePresignedUrl | None = None

        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_available_link_by_token(data.token)
                _ensure_public_download_allowed(link, operation=operation)
                _validate_public_link_password(link, data.password, operation=operation)

                node = await uow.nodes.get_required_by_id(link.node_id)
                if node.node_type != NodeType.FILE:
                    raise ValidationServiceError(
                        "Публичная загрузка поддерживается только для файлов.",
                        field="node_type",
                        value=node.node_type.value,
                        reason="download_for_folder_not_supported",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                file = await uow.files.get_required_by_node_id(
                    node.id,
                    include_deleted_node=False,
                )
                _ensure_file_downloadable(file, operation=operation)

                presigned = await self.storage_service.create_download_url(
                    bucket=file.storage_bucket,
                    object_key=file.storage_key,
                    response_headers=_download_headers(
                        filename=node.name,
                        mime_type=file.mime_type,
                    ),
                )

                await uow.links.register_download(link, flush=True, refresh=True)
                link_snapshot = _link_snapshot(link)
                await uow.commit()

            if (
                link_snapshot is None
                or node is None
                or file is None
                or presigned is None
            ):
                raise _empty_result_error(operation)
            await self._safe_log_event(
                action=AuditAction.PUBLIC_LINK_DOWNLOADED,
                actor_id=None,
                link_snapshot=link_snapshot,
                message="Создан URL-адрес для загрузки общедоступной ссылки.",
                metadata={
                    "node_id": str(node.id),
                    "file_id": str(file.id),
                    "expires_at": _expires_at(
                        presigned.expires_at,
                        presigned.expires_in_seconds,
                    ).isoformat(),
                },
            )
            return PublicLinkDownloadResponse(
                presigned_url=presigned.url,
                expires_at=_expires_at(
                    presigned.expires_at,
                    presigned.expires_in_seconds,
                ),
                method=presigned.method.value,
                headers=presigned.headers,
                filename=node.name,
                size_bytes=file.size_bytes,
                mime_type=file.mime_type,
            )

        except StorageError as exc:
            raise service_error_from_storage(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def create_public_thumbnail_url(
        self,
        data: PublicLinkAccessRequest,
    ) -> PublicLinkDownloadResponse:
        """Создаёт presigned URL для preview-миниатюры файла публичной ссылки.

        В отличие от скачивания, требует лишь права просмотра ссылки и отдаёт
        сгенерированный preview-объект (webp для изображений/PDF/видео), а не
        исходный файл. Если у файла нет готового preview, возвращает ошибку
        «пустого результата», чтобы фронт показал иконку-заглушку.

        Args:
            data: Данные публичного доступа, включая токен и опциональный пароль.

        Returns:
            Ответ с presigned URL на preview-объект и его MIME-типом.

        Raises:
            PublicLinkServiceError: Если ссылка недоступна для просмотра.
            PermissionServiceError: Если пароль отсутствует или неверен.
            ValidationServiceError: Если ссылка указывает на папку.
            ServiceError: Если preview отсутствует, либо при ошибке БД/хранилища.
        """

        operation = "create_public_thumbnail_url"

        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_available_link_by_token(data.token)
                _ensure_public_access_allowed(link, operation=operation)
                _validate_public_link_password(link, data.password, operation=operation)

                node = await uow.nodes.get_required_by_id(link.node_id)
                if node.node_type != NodeType.FILE:
                    raise ValidationServiceError(
                        "Миниатюра доступна только для файлов.",
                        field="node_type",
                        value=node.node_type.value,
                        reason="thumbnail_for_folder_not_supported",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )
                file = await uow.files.get_required_by_node_id(
                    node.id,
                    include_deleted_node=False,
                )
                if not (file.preview_available and file.preview_storage_key):
                    raise NotFoundServiceError(
                        "Для файла нет готовой миниатюры.",
                        entity_name="file_preview",
                        entity_id=str(node.id),
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                mime_type = preview_content_type(file.mime_type)
                presigned = await self.storage_service.create_download_url(
                    bucket=file.storage_bucket,
                    object_key=file.preview_storage_key,
                    response_headers={"response-content-type": mime_type},
                )

            return PublicLinkDownloadResponse(
                presigned_url=presigned.url,
                expires_at=_expires_at(
                    presigned.expires_at,
                    presigned.expires_in_seconds,
                ),
                method=presigned.method.value,
                headers=presigned.headers,
                filename=None,
                size_bytes=None,
                mime_type=mime_type,
            )

        except StorageError as exc:
            raise service_error_from_storage(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def create_public_folder_archive(
        self,
        data: PublicLinkAccessRequest,
    ) -> PublicLinkFolderArchiveResponse:
        """Ставит фоновую задачу на создание ZIP-архива папки по публичной ссылке.

        Проверяет токен, пароль, тип узла и разрешение на скачивание. Создаёт
        задачу от имени владельца папки, поскольку у публичных пользователей нет
        учётной записи.

        Args:
            data: Токен и необязательный пароль публичной ссылки.

        Returns:
            Идентификатор задачи и её текущий статус.

        Raises:
            PublicLinkServiceError: Если ссылка недоступна или скачивание запрещено.
            PermissionServiceError: Если пароль неверен.
            ValidationServiceError: Если узел не является папкой.
            ServiceError: При ошибке базы данных или непредвиденной ошибке.
        """

        operation = "create_public_folder_archive"
        task_id: UUID | None = None
        task_status: BackgroundTaskStatus | None = None

        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_available_link_by_token(data.token)
                _ensure_public_download_allowed(link, operation=operation)
                _validate_public_link_password(link, data.password, operation=operation)

                node = await uow.nodes.get_required_by_id(link.node_id)
                if node.node_type != NodeType.FOLDER:
                    raise ValidationServiceError(
                        "Эта конечная точка предназначена только для загрузки в папки.",
                        field="node_type",
                        value=node.node_type.value,
                        reason="folder_archive_for_file_not_supported",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                owner_id = node.owner_id
                archive_name = f"{node.name}.zip"
                task = await uow.tasks.create_user_task(
                    task_type=BackgroundTaskType.CREATE_FOLDER_ARCHIVE,
                    created_by=owner_id,
                    related_entity_type="folder",
                    related_entity_id=node.id,
                    flush=True,
                    refresh=True,
                )
                payload = {
                    "folder_id": str(node.id),
                    "include_deleted": False,
                    "archive_name": archive_name,
                    "password": None,
                }
                result_data = {
                    "folder_id": str(node.id),
                    "archive_name": archive_name,
                    "storage_bucket": self.storage_service.default_archives_bucket,
                    "storage_key": self.storage_service.build_archive_key(
                        user_id=owner_id,
                        task_id=task.id,
                        extension="zip",
                    ),
                    "content_type": "application/zip",
                    "password_protected": False,
                }
                task = await uow.tasks.update(
                    task,
                    {"payload": payload, "result_data": result_data},
                    flush=True,
                    refresh=True,
                    allowed_fields={"payload", "result_data"},
                )
                task_id = task.id
                task_status = task.status
                await uow.commit()

            if task_id is None or task_status is None:
                raise _empty_result_error(operation)

            return PublicLinkFolderArchiveResponse(
                task_id=task_id,
                status=task_status,
            )

        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def get_public_folder_archive_status(
        self,
        token: str,
        task_id: UUID,
    ) -> PublicLinkFolderArchiveResponse:
        """Возвращает статус архивной задачи и, если готово, ссылку для скачивания.

        Загружает задачу и проверяет, что она относится к узлу данной публичной
        ссылки. Если задача завершена — строит presigned URL и возвращает его.

        Args:
            token: Публичный токен ссылки.
            task_id: Идентификатор фоновой задачи создания архива.

        Returns:
            Статус задачи и опциональная ссылка для скачивания.

        Raises:
            PublicLinkServiceError: Если ссылка недоступна.
            ValidationServiceError: Если задача не принадлежит узлу данной ссылки.
            ServiceError: При ошибке базы данных, хранилища или непредвиденной ошибке.
        """

        operation = "get_public_folder_archive_status"
        task_status: BackgroundTaskStatus | None = None
        result_data: dict[str, Any] = {}
        payload_data: dict[str, Any] = {}

        try:
            async with self.uow_factory() as uow:
                link = await uow.links.get_required_available_link_by_token(token)
                task = await uow.tasks.get_required_by_id(task_id)

                if task.related_entity_id != link.node_id:
                    raise ValidationServiceError(
                        "Задача архивирования не относится к этой общедоступной ссылке.",
                        field="task_id",
                        value=task_id,
                        reason="task_node_mismatch",
                        details={"service": SERVICE_NAME, "operation": operation},
                    )

                task_status = task.status
                result_data = task.result_data or {}
                payload_data = task.payload or {}

            if task_status is None:
                raise _empty_result_error(operation)

            if task_status != BackgroundTaskStatus.COMPLETED:
                return PublicLinkFolderArchiveResponse(
                    task_id=task_id,
                    status=task_status,
                )

            # Worker записывает archive_bucket/archive_key; исходные result_data содержали
            # storage_bucket/storage_key. Поддерживаю оба варианта, поскольку диспетчер заменяет result_data.
            # имя_архива хранится в полезной нагрузке (никогда не перезаписывается) — резервный вариант result_data для обеспечения безопасности.
            archive_name: str = (
                payload_data.get("archive_name")
                or result_data.get("archive_name")
                or f"archive-{task_id}.zip"
            )
            storage_bucket: str = (
                result_data.get("archive_bucket")
                or result_data.get("storage_bucket")
                or self.storage_service.default_archives_bucket
            )
            storage_key: str = (
                result_data.get("archive_key") or result_data.get("storage_key") or ""
            )
            size_bytes: int | None = result_data.get(
                "archive_size_bytes"
            ) or result_data.get("size_bytes")

            presigned = await self.storage_service.create_download_url(
                bucket=storage_bucket,
                object_key=storage_key,
                response_headers=_download_headers(
                    filename=archive_name,
                    mime_type="application/zip",
                ),
            )
            expires_at = _expires_at(presigned.expires_at, presigned.expires_in_seconds)

            return PublicLinkFolderArchiveResponse(
                task_id=task_id,
                status=task_status,
                presigned_url=presigned.url,
                expires_at=expires_at,
                filename=archive_name,
                size_bytes=size_bytes,
            )

        except StorageError as exc:
            raise service_error_from_storage(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except ServiceError:
            raise
        except DatabaseError as exc:
            raise service_error_from_database(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc
        except Exception as exc:
            raise service_error_from_exception(
                exc, service=SERVICE_NAME, operation=operation
            ) from exc

    async def _require_owner_access(
        self,
        *,
        uow: Any,
        link: PublicLink,
        actor_id: UUID,
        operation: str,
    ) -> None:
        """Проверяет право пользователя управлять публичной ссылкой.

        Право определяется через доступ SHARE к узлу, связанному с публичной
        ссылкой. Удаленные узлы разрешены, публичный доступ не учитывается.

        Args:
            uow: Unit of Work для выполнения проверки доступа.
            link: Публичная ссылка, к узлу которой проверяется доступ.
            actor_id: Идентификатор пользователя, выполняющего операцию.
            operation: Название операции для контекста ошибок.

        Raises:
            PermissionServiceError: Если пользователь не имеет права SHARE к узлу.
        """

        await self.access_service.require_access(
            node_id=link.node_id,
            user_id=actor_id,
            action=PermissionAction.SHARE,
            allow_deleted=True,
            allow_public=False,
            uow=uow,
        )

    async def _generate_unique_token(self, uow: Any) -> str:
        """Генерирует уникальный токен публичной ссылки.

        Делает ограниченное количество попыток сгенерировать URL-safe токен и
        проверяет его уникальность через репозиторий ссылок.

        Args:
            uow: Unit of Work с репозиторием публичных ссылок.

        Returns:
            Уникальный токен публичной ссылки.

        Raises:
            PublicLinkServiceError: Если не удалось получить уникальный токен за
                допустимое число попыток.
        """

        max_attempts = 10
        for _ in range(max_attempts):
            token = secrets.token_urlsafe(DEFAULT_TOKEN_BYTES)
            if not await uow.links.token_exists(token):
                return token
        raise PublicLinkServiceError(
            "Не удалось сгенерировать уникальный токен публичной ссылки.",
            reason="token_generation_failed",
            details={"service": SERVICE_NAME, "max_attempts": max_attempts},
        )

    async def _safe_log_event(
        self,
        *,
        action: AuditAction,
        actor_id: UUID | None,
        link_snapshot: Mapping[str, Any],
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Безопасно записывает событие публичной ссылки в аудит.

        Формирует audit payload из снимка ссылки, добавляет дополнительные
        метаданные и записывает событие успешной операции. Ошибки аудита не
        пробрасываются выше.

        Args:
            action: Действие аудита.
            actor_id: Идентификатор пользователя, связанного с событием. Может быть
                None для публичных действий без авторизации.
            link_snapshot: Снимок публичной ссылки.
            message: Сообщение события аудита.
            metadata: Дополнительные метаданные события.
        """

        try:
            payload = _audit_payload(link_snapshot)
            if metadata:
                payload.update({str(k): _jsonable(v) for k, v in metadata.items()})
            await self.audit_service.log_success(
                action=action,
                user_id=actor_id,
                entity_type=AuditResourceType.PUBLIC_LINK.value,
                entity_id=_snapshot_uuid(link_snapshot, "id"),
                resource_type=AuditResourceType.PUBLIC_LINK,
                message=message,
                metadata=payload,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось записать событие аудита общедоступных ссылок.",
                extra={
                    "action": action.value,
                    "error_type": exc.__class__.__name__,
                    "reason": str(exc),
                },
            )

    async def _safe_log_security_password_failed(
        self, *, link: PublicLink, operation: str
    ) -> None:
        """Безопасно записывает неуспешную проверку пароля публичной ссылки.

        Используется при неверном пароле в validate_access. Ошибки записи аудита
        не пробрасываются выше.

        Args:
            link: Публичная ссылка, для которой не прошла проверка пароля.
            operation: Название операции для метаданных аудита.
        """

        try:
            await self.audit_service.log_event(
                action=AuditAction.SECURITY_PUBLIC_LINK_PASSWORD_FAILED,
                result=AuditResult.FAILURE,
                user_id=None,
                entity_type=AuditResourceType.PUBLIC_LINK.value,
                entity_id=link.id,
                resource_type=AuditResourceType.PUBLIC_LINK,
                message="Не удалось подтвердить пароль по общедоступной ссылке.",
                metadata={
                    "service": SERVICE_NAME,
                    "operation": operation,
                    "token": link.token,
                    "node_id": str(link.node_id),
                },
            )
        except Exception:
            logger.warning(
                "Не удалось записать событие аудита безопасности для сбоя пароля по общедоступной ссылке.",
                exc_info=True,
            )


def _ensure_supported_node_type(node: FileSystemNode, *, operation: str) -> None:
    """Проверяет, что узел поддерживает публичные ссылки.

    Публичные ссылки разрешены только для файлов и папок.

    Args:
        node: Узел файловой системы для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        ValidationServiceError: Если тип узла не является файлом или папкой.
    """

    if node.node_type in {NodeType.FILE, NodeType.FOLDER}:
        return
    raise ValidationServiceError(
        "Общедоступные ссылки поддерживаются только для файлов и папок.",
        field="node_id",
        value=node.id,
        reason="unsupported_node_type",
        details={
            "service": SERVICE_NAME,
            "operation": operation,
            "node_type": node.node_type.value,
        },
    )


def _ensure_public_access_allowed(link: PublicLink, *, operation: str) -> None:
    """Проверяет, что публичная ссылка доступна для просмотра.

    Args:
        link: Публичная ссылка для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        PublicLinkServiceError: Если ссылка недоступна для просмотра в текущий
            момент.
    """

    now = datetime.now(UTC)
    if not link.can_view_at(now):
        raise PublicLinkServiceError(
            "Общедоступная ссылка недоступна для просмотра.",
            public_link_id=link.id,
            token=link.token,
            reason="not_available_for_view",
            details={"service": SERVICE_NAME, "operation": operation},
        )


def _ensure_public_download_allowed(link: PublicLink, *, operation: str) -> None:
    """Проверяет, что публичная ссылка доступна для скачивания.

    Args:
        link: Публичная ссылка для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        PublicLinkServiceError: Если ссылка недоступна для скачивания в текущий
            момент.
    """

    now = datetime.now(UTC)
    if not link.can_download_at(now):
        raise PublicLinkServiceError(
            "Общедоступная ссылка недоступна для скачивания.",
            public_link_id=link.id,
            token=link.token,
            reason="not_available_for_download",
            details={"service": SERVICE_NAME, "operation": operation},
        )


def _validate_public_link_password(
    link: PublicLink,
    password: str | None,
    *,
    operation: str,
) -> None:
    """Проверяет пароль публичной ссылки.

    Если ссылка не защищена паролем, проверка завершается успешно. Если пароль
    требуется, но не передан или неверен, выбрасывается ошибка доступа.

    Args:
        link: Публичная ссылка для проверки.
        password: Пароль, переданный пользователем.
        operation: Название операции для контекста ошибок.

    Raises:
        PermissionServiceError: Если пароль требуется, но отсутствует или
            указан неверно.
    """

    if not link.password_hash:
        return
    if password is None:
        raise PermissionServiceError(
            "Для этой общедоступной ссылки требуется пароль.",
            action="public_link_access",
            reason="missing_password",
            resource_type="public_link",
            resource_id=link.id,
            details={"service": SERVICE_NAME, "operation": operation},
        )
    if not verify_password(password, link.password_hash):
        raise PermissionServiceError(
            "Неверный пароль для публичной ссылки.",
            action="public_link_access",
            reason="invalid_password",
            resource_type="public_link",
            resource_id=link.id,
            details={"service": SERVICE_NAME, "operation": operation},
        )


def _ensure_file_downloadable(file: File, *, operation: str) -> None:
    """Проверяет, что файл можно скачать по публичной ссылке.

    Файл должен быть доступен в хранилище, а связанный узел не должен быть
    удален.

    Args:
        file: Файл для проверки.
        operation: Название операции для контекста ошибок.

    Raises:
        PublicLinkServiceError: Если объект файла недоступен в хранилище или
            связанный узел удален.
    """

    if file.storage_status != StorageObjectStatus.AVAILABLE:
        raise PublicLinkServiceError(
            "Файловый объект недоступен в хранилище.",
            public_link_id=None,
            node_id=file.node_id,
            reason="storage_object_unavailable",
            details={
                "service": SERVICE_NAME,
                "operation": operation,
                "file_id": str(file.id),
                "storage_status": file.storage_status.value,
            },
        )
    node = file.node
    if node is not None and node.is_deleted:
        raise PublicLinkServiceError(
            "Не удается загрузить удаленный файл по общедоступной ссылке.",
            public_link_id=None,
            node_id=file.node_id,
            reason="file_node_deleted",
            details={
                "service": SERVICE_NAME,
                "operation": operation,
                "file_id": str(file.id),
            },
        )


def _download_headers(*, filename: str, mime_type: str | None) -> dict[str, str]:
    """Формирует response-заголовки для скачивания файла.

    Создает Content-Disposition с безопасным именем файла и, если MIME-тип
    передан, добавляет Content-Type.

    Args:
        filename: Имя файла для заголовка Content-Disposition.
        mime_type: MIME-тип файла. Если None, Content-Type не добавляется.

    Returns:
        Словарь response-заголовков для предварительно подписанного URL.
    """

    safe = filename.replace('"', "'")
    headers = {"response-content-disposition": f'attachment; filename="{safe}"'}
    if mime_type:
        headers["response-content-type"] = mime_type
    return headers


def _link_snapshot(link: PublicLink) -> dict[str, Any]:
    """Создает снимок публичной ссылки.

    Args:
        link: ORM-модель публичной ссылки.

    Returns:
        Словарь с идентификаторами, токеном, типом разрешения, статусом,
        лимитами и счетчиками, датами доступа, описанием, признаками состояния,
        наличием пароля и краткими данными связанного узла.
    """

    node = link.node
    return {
        "id": link.id,
        "node_id": link.node_id,
        "created_by": link.created_by,
        "token": link.token,
        "permission_type": link.permission_type,
        "status": link.status,
        "expires_at": link.expires_at,
        "max_downloads": link.max_downloads,
        "download_count": link.download_count,
        "view_count": link.view_count,
        "upload_count": link.upload_count,
        "is_active": link.is_active,
        "revoked_at": link.revoked_at,
        "revoked_by": link.revoked_by,
        "revoke_reason": link.revoke_reason,
        "last_accessed_at": link.last_accessed_at,
        "last_downloaded_at": link.last_downloaded_at,
        "last_uploaded_at": link.last_uploaded_at,
        "description": link.description,
        "created_at": link.created_at,
        "has_password": bool(link.password_hash),
        "is_download_limit_reached": link.is_download_limit_reached,
        "is_revoked": link.is_revoked,
        "node": _node_list_item_payload(node) if node is not None else None,
    }


def _include_snapshot_by_password_filter(
    snapshot: Mapping[str, Any],
    has_password: bool | None,
) -> bool:
    """Проверяет соответствие снимка ссылки фильтру по наличию пароля.

    Args:
        snapshot: Снимок публичной ссылки.
        has_password: Ожидаемое наличие пароля. Если `None`, фильтр не
            применяется.

    Returns:
        `True`, если снимок соответствует фильтру по признаку парольной защиты.
    """

    if has_password is None:
        return True
    return bool(snapshot.get("has_password")) is has_password


def _loaded_file(node: FileSystemNode) -> File | None:
    """Возвращает связанный File узла, только если он уже загружен.

    Читает значение из ``__dict__`` экземпляра: eager-загруженное отношение
    лежит там как обычный атрибут, тогда как незагруженное доступно лишь через
    ленивый дескриптор. Так мы избегаем ленивой подгрузки в async-сессии
    (которая упала бы с ``MissingGreenlet``) и не зависим от типа объекта.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Загруженный ``File`` или ``None`` (папка либо отношение не загружено).
    """

    file = node.__dict__.get("file")
    return file if isinstance(file, File) else None


def _node_list_item_payload(node: FileSystemNode) -> dict[str, Any]:
    """Создает краткий payload узла для публичной ссылки.

    Args:
        node: ORM-модель узла файловой системы.

    Returns:
        Словарь с основными данными узла: идентификаторами, типом, именем,
        путем, глубиной, признаком удаления, видимостью, временными метками,
        а также MIME-типом и размером файла (если File загружен).
    """

    file = _loaded_file(node)
    return {
        "id": node.id,
        "owner_id": node.owner_id,
        "parent_id": node.parent_id,
        "node_type": node.node_type,
        "name": node.name,
        "path": node.path,
        "depth": node.depth,
        "is_deleted": bool(node.is_deleted),
        "visibility": node.visibility,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "file_size_bytes": file.size_bytes if file is not None else None,
        "file_mime_type": file.mime_type if file is not None else None,
    }


def _audit_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Формирует метаданные публичной ссылки для аудита.

    Args:
        snapshot: Снимок публичной ссылки.

    Returns:
        Словарь с JSON-совместимыми метаданными ссылки.
    """

    return {
        "link_id": _jsonable(snapshot.get("id")),
        "node_id": _jsonable(snapshot.get("node_id")),
        "permission_type": _jsonable(snapshot.get("permission_type")),
        "status": _jsonable(snapshot.get("status")),
        "is_active": _jsonable(snapshot.get("is_active")),
        "expires_at": _jsonable(snapshot.get("expires_at")),
        "max_downloads": _jsonable(snapshot.get("max_downloads")),
        "download_count": _jsonable(snapshot.get("download_count")),
        "view_count": _jsonable(snapshot.get("view_count")),
        "has_password": _jsonable(snapshot.get("has_password")),
    }


def _snapshot_uuid(snapshot: Mapping[str, Any], field: str) -> UUID | None:
    """Возвращает UUID из снимка по имени поля.

    Args:
        snapshot: Снимок данных.
        field: Имя поля, значение которого нужно получить.

    Returns:
        UUID-значение поля или None, если значение отсутствует либо не является
        UUID.
    """

    value = snapshot.get(field)
    return value if isinstance(value, UUID) else None


def _normalize_sort_by(value: str) -> PublicLinkSortField:
    """Нормализует поле сортировки публичных ссылок.

    Если значение поддерживается, возвращает его в нижнем регистре. Если поле
    сортировки неизвестно, возвращает значение по умолчанию created_at.

    Args:
        value: Исходное поле сортировки.

    Returns:
        Нормализованное поле сортировки публичных ссылок.
    """

    allowed: set[PublicLinkSortField] = {
        "created_at",
        "expires_at",
        "last_accessed_at",
        "last_downloaded_at",
        "last_uploaded_at",
        "download_count",
        "view_count",
        "upload_count",
        "status",
    }
    normalized = value.strip().lower()
    if normalized in allowed:
        return cast(PublicLinkSortField, normalized)
    return "created_at"


def _limit(value: int) -> int:
    """Нормализует размер страницы.

    Значения меньше 1 заменяются на 1, значения больше MAX_PAGE_LIMIT
    ограничиваются MAX_PAGE_LIMIT.

    Args:
        value: Запрошенный размер страницы.

    Returns:
        Нормализованный размер страницы.
    """

    if value < 1:
        return 1
    return min(value, MAX_PAGE_LIMIT)


def _include_by_password_filter(link: PublicLink, has_password: bool | None) -> bool:
    """Проверяет соответствие ссылки фильтру по наличию пароля.

    Args:
        link: Публичная ссылка для проверки.
        has_password: Ожидаемое наличие пароля. Если None, фильтр не
            применяется.

    Returns:
        True, если ссылка соответствует фильтру.
    """

    if has_password is None:
        return True
    return bool(link.password_hash) is has_password


def _expires_at(value: datetime | None, expires_in_seconds: int) -> datetime:
    """Определяет дату и время истечения предварительно подписанного URL.

    Если явное время истечения передано, нормализует его к UTC. Иначе вычисляет
    время истечения от текущего момента.

    Args:
        value: Явное время истечения URL. Может быть None.
        expires_in_seconds: Срок действия URL в секундах.

    Returns:
        Дата и время истечения URL в UTC.
    """

    if value is not None:
        return _normalize_datetime(value)
    return datetime.now(UTC) + timedelta(seconds=expires_in_seconds)


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
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, Iterable):
        return [_jsonable(v) for v in value]
    return str(value)


def _empty_result_error(operation: str) -> ServiceError:
    """Создает ошибку пустого результата сервисной операции.

    Args:
        operation: Название операции, завершившейся без результата.

    Returns:
        Ошибка сервиса с описанием отсутствующего результата.
    """

    return ServiceError(
        "Сервисная операция завершена без результата.",
        service=SERVICE_NAME,
        operation=operation,
    )


# Глобальный singleton-экземпляр сервиса публичных ссылок.
_public_links_service: PublicLinksService | None = None


def get_public_links_service(
    *,
    settings: Settings | None = None,
    uow_factory: UnitOfWorkFactory | None = None,
    access_service: AccessService | None = None,
    audit_service: AuditService | None = None,
    storage_service: StorageService | None = None,
) -> PublicLinksService:
    """Возвращает экземпляр сервиса публичных ссылок.

    Если передана хотя бы одна зависимость, создает новый экземпляр сервиса с
    указанными зависимостями. Если зависимости не переданы, возвращает
    глобальный singleton-экземпляр, создавая его при первом обращении.

    Args:
        settings: Настройки приложения для нового экземпляра сервиса.
        uow_factory: Фабрика Unit of Work для нового экземпляра сервиса.
        access_service: Сервис доступа для нового экземпляра сервиса.
        audit_service: Сервис аудита для нового экземпляра сервиса.
        storage_service: Сервис хранилища для нового экземпляра сервиса.

    Returns:
        Экземпляр PublicLinksService.
    """

    global _public_links_service

    if any(
        dep is not None
        for dep in (
            settings,
            uow_factory,
            access_service,
            audit_service,
            storage_service,
        )
    ):
        return PublicLinksService(
            settings=settings,
            uow_factory=uow_factory,
            access_service=access_service,
            audit_service=audit_service,
            storage_service=storage_service,
        )

    if _public_links_service is None:
        _public_links_service = PublicLinksService()
    return _public_links_service

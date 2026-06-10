from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    """Статус учётной записи пользователя.

    Описывает текущее состояние пользователя в системе: ожидание одобрения,
    активность, блокировку, отклонение или удаление.

    Attributes:
        PENDING: Пользователь ожидает одобрения или завершения регистрации.
        ACTIVE: Пользователь активен и может работать с системой.
        BLOCKED: Пользователь заблокирован администратором.
        REJECTED: Пользователь отклонён администратором.
        DELETED: Пользователь помечен как удалённый.
    """

    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    DELETED = "deleted"


class SystemRole(StrEnum):
    """Системная роль пользователя.

    Описывает встроенные роли, используемые для базового разграничения прав
    доступа в приложении.

    Attributes:
        ADMIN: Администратор системы.
        USER: Обычный пользователь системы.
    """

    ADMIN = "admin"
    USER = "user"


class RegistrationRequestStatus(StrEnum):
    """Статус запроса на регистрацию.

    Описывает жизненный цикл заявки пользователя на регистрацию.

    Attributes:
        PENDING: Запрос ожидает рассмотрения.
        APPROVED: Запрос одобрен.
        REJECTED: Запрос отклонён.
        CANCELLED: Запрос отменён.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TokenType(StrEnum):
    """Тип токена безопасности.

    Определяет назначение токена, используемого в механизмах аутентификации,
    регистрации и публичного доступа.

    Attributes:
        ACCESS: Access-токен для доступа к защищённым ресурсам.
        REFRESH: Refresh-токен для обновления access-токена.
        REGISTRATION_APPROVAL: Токен подтверждения или одобрения регистрации.
        PUBLIC_LINK: Токен публичной ссылки.
    """

    ACCESS = "access"
    REFRESH = "refresh"
    REGISTRATION_APPROVAL = "registration_approval"
    PUBLIC_LINK = "public_link"


class SessionStatus(StrEnum):
    """Статус пользовательской сессии.

    Описывает состояние сессии пользователя в системе.

    Attributes:
        ACTIVE: Сессия активна.
        REVOKED: Сессия отозвана.
        EXPIRED: Сессия истекла.
    """

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class NodeType(StrEnum):
    """Тип узла в файловой системе.

    Используется для различения файлов и папок в иерархии пользовательского
    хранилища.

    Attributes:
        FILE: Узел является файлом.
        FOLDER: Узел является папкой.
    """

    FILE = "file"
    FOLDER = "folder"


class NodeVisibility(StrEnum):
    """Уровень видимости файлового узла.

    Описывает режим доступности узла файловой системы для владельца,
    пользователей с правами доступа или публичных ссылок.

    Attributes:
        PRIVATE: Узел доступен только владельцу и явно разрешённым субъектам.
        SHARED: Узел имеет выданные права доступа.
        PUBLIC: Узел доступен через публичную ссылку.
    """

    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class FileProcessingStatus(StrEnum):
    """Статус обработки файла после загрузки.

    Описывает этап обработки файла после завершения его загрузки в систему.

    Attributes:
        PENDING: Обработка ожидает запуска.
        PROCESSING: Файл находится в процессе обработки.
        READY: Файл успешно обработан и готов к использованию.
        FAILED: Обработка файла завершилась ошибкой.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class FilePreviewStatus(StrEnum):
    """Статус генерации предпросмотра файла.

    Описывает состояние процесса создания preview-версии файла.

    Attributes:
        NOT_REQUIRED: Предпросмотр для файла не требуется.
        PENDING: Генерация предпросмотра ожидает запуска.
        GENERATING: Предпросмотр создаётся.
        READY: Предпросмотр успешно создан.
        FAILED: Генерация предпросмотра завершилась ошибкой.
    """

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class UploadSessionStatus(StrEnum):
    """Статус сессии многокомпонентной загрузки.

    Описывает состояние multipart-загрузки файла.

    Attributes:
        CREATED: Сессия загрузки создана.
        UPLOADING: Выполняется загрузка частей файла.
        COMPLETED: Загрузка успешно завершена.
        FAILED: Загрузка завершилась ошибкой.
        ABORTED: Загрузка отменена.
        EXPIRED: Сессия загрузки истекла.
    """

    CREATED = "created"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    EXPIRED = "expired"


class UploadPartStatus(StrEnum):
    """Статус части многокомпонентной загрузки файла.

    Описывает состояние отдельной части файла в рамках multipart-загрузки.

    Attributes:
        PENDING: Часть ожидает загрузки.
        UPLOADED: Часть успешно загружена.
        FAILED: Загрузка части завершилась ошибкой.
    """

    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class StorageObjectStatus(StrEnum):
    """Статус физического объекта в MinIO/S3.

    Описывает состояние объекта, размещённого в объектном хранилище.

    Attributes:
        PENDING: Объект ожидает создания или подтверждения.
        AVAILABLE: Объект доступен в хранилище.
        MISSING: Объект отсутствует в хранилище.
        CORRUPTED: Объект повреждён или не прошёл проверку целостности.
        DELETING: Объект находится в процессе удаления.
        DELETED: Объект удалён из хранилища.
    """

    PENDING = "pending"
    AVAILABLE = "available"
    MISSING = "missing"
    CORRUPTED = "corrupted"
    DELETING = "deleting"
    DELETED = "deleted"


class PermissionLevel(StrEnum):
    """Уровень доступа к ресурсу.

    Определяет набор прав, который может быть выдан пользователю, роли или
    другому субъекту доступа.

    Attributes:
        READ: Право просмотра ресурса.
        DOWNLOAD: Право скачивания ресурса.
        WRITE: Право изменения ресурса.
        DELETE: Право удаления ресурса.
        OWNER: Полные права владельца ресурса.
    """

    READ = "read"
    DOWNLOAD = "download"
    WRITE = "write"
    DELETE = "delete"
    OWNER = "owner"


class PermissionSubjectType(StrEnum):
    """Тип субъекта, которому выдано разрешение.

    Используется для определения сущности, получающей права доступа к ресурсу.

    Attributes:
        USER: Разрешение выдано пользователю.
        ROLE: Разрешение выдано роли.
        PUBLIC_LINK: Разрешение связано с публичной ссылкой.
    """

    USER = "user"
    ROLE = "role"
    PUBLIC_LINK = "public_link"


class PublicLinkPermissionType(StrEnum):
    """Тип доступа публичной ссылки.

    Определяет действия, доступные пользователю публичной ссылки.

    Attributes:
        VIEW: Доступ к просмотру ресурса.
        DOWNLOAD: Доступ к скачиванию ресурса.
        UPLOAD: Доступ к загрузке файлов через публичную ссылку.
    """

    VIEW = "view"
    DOWNLOAD = "download"
    UPLOAD = "upload"


class PublicLinkStatus(StrEnum):
    """Статус публичной ссылки.

    Описывает состояние публичной ссылки и возможность её использования.

    Attributes:
        ACTIVE: Публичная ссылка активна.
        DISABLED: Публичная ссылка отключена.
        EXPIRED: Срок действия публичной ссылки истёк.
        REVOKED: Публичная ссылка отозвана.
    """

    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"
    REVOKED = "revoked"


class TrashItemStatus(StrEnum):
    """Статус элемента корзины.

    Описывает состояние объекта, помещённого в корзину.

    Attributes:
        IN_TRASH: Элемент находится в корзине.
        RESTORED: Элемент восстановлен из корзины.
        PURGED: Элемент окончательно удалён.
    """

    IN_TRASH = "in_trash"
    RESTORED = "restored"
    PURGED = "purged"


class ArchiveStatus(StrEnum):
    """Статус подготовки ZIP-архива папки.

    Описывает состояние фонового процесса создания архива папки.

    Attributes:
        PENDING: Создание архива ожидает запуска.
        BUILDING: Архив создаётся.
        READY: Архив готов к скачиванию.
        FAILED: Создание архива завершилось ошибкой.
        EXPIRED: Срок доступности архива истёк.
        DELETED: Архив удалён.
    """

    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETED = "deleted"


class QuotaResourceType(StrEnum):
    """Тип ресурса, на который действует квота.

    Определяет метрику, ограничиваемую пользовательской или системной квотой.

    Attributes:
        STORAGE_BYTES: Квота на объём хранилища в байтах.
        FILE_COUNT: Квота на количество файлов.
        PUBLIC_LINK_COUNT: Квота на количество публичных ссылок.
        UPLOAD_SESSION_COUNT: Квота на количество upload-сессий.
    """

    STORAGE_BYTES = "storage_bytes"
    FILE_COUNT = "file_count"
    PUBLIC_LINK_COUNT = "public_link_count"
    UPLOAD_SESSION_COUNT = "upload_session_count"


class BackgroundTaskStatus(StrEnum):
    """Статус выполнения фоновой задачи.

    Описывает текущее состояние задачи, выполняемой в фоне.

    Attributes:
        PENDING: Задача ожидает запуска.
        RUNNING: Задача выполняется.
        COMPLETED: Задача успешно завершена.
        FAILED: Задача завершилась ошибкой.
        CANCELLED: Задача отменена.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundTaskType(StrEnum):
    """Тип фоновой задачи.

    Определяет назначение фоновой задачи: архивация, очистка, удаление объектов,
    проверка целостности, генерация preview или пересчёт квот.

    Attributes:
        CREATE_FOLDER_ARCHIVE: Создание ZIP-архива папки.
        CLEAN_TRASH: Очистка корзины.
        CLEAN_EXPIRED_UPLOADS: Очистка истёкших upload-сессий.
        CLEAN_EXPIRED_PUBLIC_LINKS: Очистка истёкших публичных ссылок.
        DELETE_OBJECT_FROM_STORAGE: Удаление объекта из хранилища.
        CHECK_STORAGE_INTEGRITY: Проверка целостности объектного хранилища.
        GENERATE_FILE_PREVIEW: Генерация предпросмотра файла.
        RECALCULATE_USER_QUOTA: Пересчёт пользовательской квоты.
    """

    CREATE_FOLDER_ARCHIVE = "create_folder_archive"
    CLEAN_TRASH = "clean_trash"
    CLEAN_EXPIRED_UPLOADS = "clean_expired_uploads"
    CLEAN_EXPIRED_PUBLIC_LINKS = "clean_expired_public_links"
    DELETE_OBJECT_FROM_STORAGE = "delete_object_from_storage"
    CHECK_STORAGE_INTEGRITY = "check_storage_integrity"
    GENERATE_FILE_PREVIEW = "generate_file_preview"
    RECALCULATE_USER_QUOTA = "recalculate_user_quota"


class TaskPriority(StrEnum):
    """Приоритет фоновой задачи.

    Определяет относительную важность фоновой задачи при планировании
    выполнения.

    Attributes:
        LOW: Низкий приоритет.
        NORMAL: Обычный приоритет.
        HIGH: Высокий приоритет.
        CRITICAL: Критический приоритет.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class HealthStatus(StrEnum):
    """Статус состояния компонента системы.

    Используется в health-check ответах для описания доступности компонентов
    приложения.

    Attributes:
        OK: Компонент работает штатно.
        DEGRADED: Компонент работает с ухудшением или частичными проблемами.
        UNAVAILABLE: Компонент недоступен.
    """

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AuditAction(StrEnum):
    """Тип действия в журнале аудита.

    Перечисляет действия пользователей, администраторов, фоновых задач
    и системных процессов, которые могут фиксироваться в журнале аудита.

    Attributes:
        USER_LOGIN: Успешный вход пользователя.
        USER_LOGOUT: Выход пользователя.
        USER_LOGIN_FAILED: Неуспешная попытка входа пользователя.
        USER_REFRESH_TOKEN_ROTATED: Ротация refresh-токена пользователя.
        USER_SESSION_REVOKED: Отзыв пользовательской сессии.
        USER_CREATED: Создание пользователя.
        USER_UPDATED: Обновление пользователя.
        USER_BLOCKED: Блокировка пользователя.
        USER_UNBLOCKED: Разблокировка пользователя.
        USER_DELETED: Удаление пользователя.
        USER_ROLE_ASSIGNED: Назначение роли пользователю.
        USER_ROLE_REMOVED: Удаление роли у пользователя.
        REGISTRATION_REQUEST_CREATED: Создание запроса на регистрацию.
        REGISTRATION_REQUEST_APPROVED: Одобрение запроса на регистрацию.
        REGISTRATION_REQUEST_REJECTED: Отклонение запроса на регистрацию.
        REGISTRATION_REQUEST_CANCELLED: Отмена запроса на регистрацию.
        FOLDER_CREATED: Создание папки.
        FOLDER_RENAMED: Переименование папки.
        FOLDER_MOVED: Перемещение папки.
        FOLDER_DELETED: Удаление папки.
        FOLDER_RESTORED: Восстановление папки.
        FOLDER_PURGED: Окончательное удаление папки.
        FOLDER_ARCHIVE_REQUESTED: Запрос на создание архива папки.
        FOLDER_ARCHIVE_CREATED: Создание архива папки.
        FILE_UPLOAD_STARTED: Начало загрузки файла.
        FILE_UPLOADED: Успешная загрузка файла.
        FILE_UPLOAD_FAILED: Ошибка загрузки файла.
        FILE_DOWNLOADED: Скачивание файла.
        FILE_RENAMED: Переименование файла.
        FILE_MOVED: Перемещение файла.
        FILE_UPDATED: Обновление файла.
        FILE_DELETED: Удаление файла.
        FILE_RESTORED: Восстановление файла.
        FILE_PURGED: Окончательное удаление файла.
        FILE_VERSION_CREATED: Создание версии файла.
        FILE_VERSION_RESTORED: Восстановление версии файла.
        FILE_PREVIEW_GENERATED: Генерация предпросмотра файла.
        NODE_CREATED: Создание узла файловой системы.
        NODE_RENAMED: Переименование узла файловой системы.
        NODE_MOVED: Перемещение узла файловой системы.
        NODE_UPDATED: Обновление узла файловой системы.
        NODE_DELETED: Удаление узла файловой системы.
        NODE_RESTORED: Восстановление узла файловой системы.
        NODE_PURGED: Окончательное удаление узла файловой системы.
        PERMISSION_GRANTED: Выдача разрешения.
        PERMISSION_UPDATED: Обновление разрешения.
        PERMISSION_REVOKED: Отзыв разрешения.
        PUBLIC_LINK_CREATED: Создание публичной ссылки.
        PUBLIC_LINK_OPENED: Открытие публичной ссылки.
        PUBLIC_LINK_DOWNLOADED: Скачивание через публичную ссылку.
        PUBLIC_LINK_REVOKED: Отзыв публичной ссылки.
        PUBLIC_LINK_EXPIRED: Истечение срока действия публичной ссылки.
        UPLOAD_SESSION_CREATED: Создание upload-сессии.
        UPLOAD_SESSION_COMPLETED: Завершение upload-сессии.
        UPLOAD_SESSION_FAILED: Ошибка upload-сессии.
        UPLOAD_SESSION_ABORTED: Отмена upload-сессии.
        UPLOAD_SESSION_EXPIRED: Истечение upload-сессии.
        QUOTA_CREATED: Создание квоты.
        QUOTA_UPDATED: Обновление квоты.
        QUOTA_EXCEEDED: Превышение квоты.
        QUOTA_RECALCULATED: Пересчёт квоты.
        BACKGROUND_TASK_CREATED: Создание фоновой задачи.
        BACKGROUND_TASK_STARTED: Запуск фоновой задачи.
        BACKGROUND_TASK_COMPLETED: Завершение фоновой задачи.
        BACKGROUND_TASK_FAILED: Ошибка фоновой задачи.
        BACKGROUND_TASK_CANCELLED: Отмена фоновой задачи.
        STORAGE_OBJECT_DELETED: Удаление объекта из хранилища.
        STORAGE_OBJECT_DELETE_FAILED: Ошибка удаления объекта из хранилища.
        STORAGE_INTEGRITY_CHECK_STARTED: Запуск проверки целостности хранилища.
        STORAGE_INTEGRITY_CHECK_COMPLETED: Завершение проверки целостности.
        STORAGE_INTEGRITY_PROBLEM_FOUND: Обнаружение проблемы целостности.
        SECURITY_PERMISSION_DENIED: Отказ в доступе.
        SECURITY_SUSPICIOUS_ACTIVITY: Подозрительная активность.
        SECURITY_PUBLIC_LINK_PASSWORD_FAILED: Ошибка ввода пароля публичной
            ссылки.
    """

    # Аутентификация
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_REFRESH_TOKEN_ROTATED = "user.refresh_token_rotated"
    USER_SESSION_REVOKED = "user.session_revoked"

    # Пользователи и администрирование
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_BLOCKED = "user.blocked"
    USER_UNBLOCKED = "user.unblocked"
    USER_DELETED = "user.deleted"
    USER_ROLE_ASSIGNED = "user.role_assigned"
    USER_ROLE_REMOVED = "user.role_removed"

    # Регистрация
    REGISTRATION_REQUEST_CREATED = "registration.request_created"
    REGISTRATION_REQUEST_APPROVED = "registration.request_approved"
    REGISTRATION_REQUEST_REJECTED = "registration.request_rejected"
    REGISTRATION_REQUEST_CANCELLED = "registration.request_cancelled"

    # Папки
    FOLDER_CREATED = "folder.created"
    FOLDER_RENAMED = "folder.renamed"
    FOLDER_MOVED = "folder.moved"
    FOLDER_DELETED = "folder.deleted"
    FOLDER_RESTORED = "folder.restored"
    FOLDER_PURGED = "folder.purged"
    FOLDER_ARCHIVE_REQUESTED = "folder.archive_requested"
    FOLDER_ARCHIVE_CREATED = "folder.archive_created"

    # Файлы
    FILE_UPLOAD_STARTED = "file.upload_started"
    FILE_UPLOADED = "file.uploaded"
    FILE_UPLOAD_FAILED = "file.upload_failed"
    FILE_DOWNLOADED = "file.downloaded"
    FILE_RENAMED = "file.renamed"
    FILE_MOVED = "file.moved"
    FILE_UPDATED = "file.updated"
    FILE_DELETED = "file.deleted"
    FILE_RESTORED = "file.restored"
    FILE_PURGED = "file.purged"
    FILE_VERSION_CREATED = "file.version_created"
    FILE_VERSION_RESTORED = "file.version_restored"
    FILE_PREVIEW_GENERATED = "file.preview_generated"

    # Общие узлы файловой системы
    NODE_CREATED = "node.created"
    NODE_RENAMED = "node.renamed"
    NODE_MOVED = "node.moved"
    NODE_UPDATED = "node.updated"
    NODE_DELETED = "node.deleted"
    NODE_RESTORED = "node.restored"
    NODE_PURGED = "node.purged"

    # Разрешения
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_UPDATED = "permission.updated"
    PERMISSION_REVOKED = "permission.revoked"

    # Публичные ссылки
    PUBLIC_LINK_CREATED = "public_link.created"
    PUBLIC_LINK_OPENED = "public_link.opened"
    PUBLIC_LINK_DOWNLOADED = "public_link.downloaded"
    PUBLIC_LINK_REVOKED = "public_link.revoked"
    PUBLIC_LINK_EXPIRED = "public_link.expired"

    # Сеансы загрузки
    UPLOAD_SESSION_CREATED = "upload_session.created"
    UPLOAD_SESSION_COMPLETED = "upload_session.completed"
    UPLOAD_SESSION_FAILED = "upload_session.failed"
    UPLOAD_SESSION_ABORTED = "upload_session.aborted"
    UPLOAD_SESSION_EXPIRED = "upload_session.expired"

    # Квоты
    QUOTA_CREATED = "quota.created"
    QUOTA_UPDATED = "quota.updated"
    QUOTA_EXCEEDED = "quota.exceeded"
    QUOTA_RECALCULATED = "quota.recalculated"

    # Фоновые задачи
    BACKGROUND_TASK_CREATED = "background_task.created"
    BACKGROUND_TASK_STARTED = "background_task.started"
    BACKGROUND_TASK_COMPLETED = "background_task.completed"
    BACKGROUND_TASK_FAILED = "background_task.failed"
    BACKGROUND_TASK_CANCELLED = "background_task.cancelled"

    # Хранение и целостность
    STORAGE_OBJECT_DELETED = "storage.object_deleted"
    STORAGE_OBJECT_DELETE_FAILED = "storage.object_delete_failed"
    STORAGE_INTEGRITY_CHECK_STARTED = "storage.integrity_check_started"
    STORAGE_INTEGRITY_CHECK_COMPLETED = "storage.integrity_check_completed"
    STORAGE_INTEGRITY_PROBLEM_FOUND = "storage.integrity_problem_found"

    # Безопасность
    SECURITY_PERMISSION_DENIED = "security.permission_denied"
    SECURITY_SUSPICIOUS_ACTIVITY = "security.suspicious_activity"
    SECURITY_PUBLIC_LINK_PASSWORD_FAILED = "security.public_link_password_failed"


class AuditResourceType(StrEnum):
    """Тип ресурса, к которому относится запись журнала аудита.

    Определяет доменную сущность или системный компонент, связанный
    с аудируемым действием.

    Attributes:
        USER: Пользователь.
        ROLE: Роль.
        REGISTRATION_REQUEST: Запрос на регистрацию.
        SESSION: Пользовательская сессия.
        FILE: Файл.
        FOLDER: Папка.
        NODE: Узел файловой системы.
        UPLOAD_SESSION: Upload-сессия.
        PUBLIC_LINK: Публичная ссылка.
        PERMISSION: Разрешение.
        QUOTA: Квота.
        BACKGROUND_TASK: Фоновая задача.
        STORAGE_OBJECT: Объект хранилища.
        SYSTEM: Системный ресурс или компонент.
    """

    USER = "user"
    ROLE = "role"
    REGISTRATION_REQUEST = "registration_request"
    SESSION = "session"
    FILE = "file"
    FOLDER = "folder"
    NODE = "node"
    UPLOAD_SESSION = "upload_session"
    PUBLIC_LINK = "public_link"
    PERMISSION = "permission"
    QUOTA = "quota"
    BACKGROUND_TASK = "background_task"
    STORAGE_OBJECT = "storage_object"
    SYSTEM = "system"


class AuditResult(StrEnum):
    """Результат действия, зафиксированного в журнале аудита.

    Описывает итог аудируемой операции.

    Attributes:
        SUCCESS: Операция успешно выполнена.
        FAILURE: Операция завершилась ошибкой.
        DENIED: Операция отклонена из-за отсутствия доступа.
        WARNING: Операция завершилась с предупреждением.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    WARNING = "warning"

from __future__ import annotations

from typing import Any


class DatabaseError(Exception):
    """Базовое исключение для ошибок базы данных.

    Используется как общий родитель для всех исключений, связанных с
    подключением к базе данных, выполнением операций, транзакциями,
    репозиториями и Unit of Work.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Операция с базой данных не удалась.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение базы данных.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        self.message = message
        self.details = details.copy() if details else {}
        self.cause = cause

        super().__init__(self.message)

        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Возвращает человекочитаемое описание ошибки.

        Если у ошибки есть дополнительные диагностические данные, они
        добавляются к основному сообщению.

        Returns:
            Строковое описание ошибки.
        """

        if not self.details:
            return self.message

        return f"{self.message} Details: {self.details}"

    def to_dict(self) -> dict[str, Any]:
        """Возвращает сериализуемое представление ошибки.

        Returns:
            Словарь с типом ошибки, сообщением, деталями и причиной.
        """

        payload: dict[str, Any] = {
            "error": self.__class__.__name__,
            "message": self.message,
        }

        if self.details:
            payload["details"] = self.details

        if self.cause is not None:
            payload["cause"] = self.cause.__class__.__name__

        return payload


class DatabaseConnectionError(DatabaseError):
    """Исключение при ошибке подключения к базе данных.

    Возникает, когда приложение не может установить соединение с базой данных
    или получить рабочее подключение из пула.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Может включать
            хост, порт и имя базы данных.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Не удалось подключиться к базе данных.",
        *,
        host: str | None = None,
        port: int | None = None,
        database: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение подключения к базе данных.

        Args:
            message: Человекочитаемое описание ошибки.
            host: Хост базы данных.
            port: Порт базы данных.
            database: Имя базы данных.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        merged_details = details.copy() if details else {}

        if host is not None:
            merged_details["host"] = host

        if port is not None:
            merged_details["port"] = port

        if database is not None:
            merged_details["database"] = database

        super().__init__(
            message,
            details=merged_details,
            cause=cause,
        )


class DatabaseTimeoutError(DatabaseError):
    """Исключение при превышении времени ожидания операции с базой данных.

    Возникает, когда операция подключения, запроса, транзакции или другая
    операция с базой данных не завершилась за отведённое время.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Может включать
            название операции и значение таймаута.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Время выполнения операции с базой данных истекло.",
        *,
        operation: str | None = None,
        timeout_seconds: float | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение таймаута операции с базой данных.

        Args:
            message: Человекочитаемое описание ошибки.
            operation: Название операции, для которой истекло время ожидания.
            timeout_seconds: Значение таймаута в секундах.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        merged_details = details.copy() if details else {}

        if operation is not None:
            merged_details["operation"] = operation

        if timeout_seconds is not None:
            merged_details["timeout_seconds"] = timeout_seconds

        super().__init__(
            message,
            details=merged_details,
            cause=cause,
        )


class TransactionError(DatabaseError):
    """Базовое исключение для ошибок транзакций.

    Используется для ошибок, возникающих при открытии, фиксации, откате или
    выполнении операций внутри транзакции.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Может включать
            название транзакционной операции.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Транзакция базы данных не удалась.",
        *,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение транзакции.

        Args:
            message: Человекочитаемое описание ошибки.
            operation: Название операции транзакции.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        merged_details = details.copy() if details else {}

        if operation is not None:
            merged_details["operation"] = operation

        super().__init__(
            message,
            details=merged_details,
            cause=cause,
        )


class TransactionCommitError(TransactionError):
    """Исключение при ошибке фиксации транзакции.

    Возникает, когда операция commit завершилась неуспешно.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Не удалось зафиксировать транзакцию.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение фиксации транзакции.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        super().__init__(
            message,
            operation="commit",
            details=details,
            cause=cause,
        )


class TransactionRollbackError(TransactionError):
    """Исключение при ошибке отката транзакции.

    Возникает, когда операция rollback завершилась неуспешно.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Не удалось откатить транзакцию.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение отката транзакции.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        super().__init__(
            message,
            operation="rollback",
            details=details,
            cause=cause,
        )


class RepositoryError(DatabaseError):
    """Базовое исключение для ошибок слоя репозитория.

    Используется, когда ошибка возникает внутри репозитория, но не подходит
    под более конкретный тип ошибки.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Может включать
            название репозитория и операции.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Операция репозитория не удалась.",
        *,
        repository: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение слоя репозитория.

        Args:
            message: Человекочитаемое описание ошибки.
            repository: Название репозитория, в котором возникла ошибка.
            operation: Название операции репозитория.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        merged_details = details.copy() if details else {}

        if repository is not None:
            merged_details["repository"] = repository

        if operation is not None:
            merged_details["operation"] = operation

        super().__init__(
            message,
            details=merged_details,
            cause=cause,
        )


class DuplicateEntityError(RepositoryError):
    """Исключение при нарушении уникальности сущности.

    Возникает, когда создаваемая сущность конфликтует с уже существующей
    записью.

    Примеры:
        - пользователь с таким email уже существует;
        - роль с таким названием уже существует;
        - файл или папка с таким именем уже существует в каталоге.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Содержит имя
            сущности и, при наличии, поле и значение, по которым найден дубль.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        entity_name: str,
        *,
        field: str | None = None,
        value: Any | None = None,
        repository: str | None = None,
        message: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение дублирования сущности.

        Args:
            entity_name: Название сущности.
            field: Название поля, по которому обнаружен дубль.
            value: Значение поля, по которому обнаружен дубль.
            repository: Название репозитория, в котором возникла ошибка.
            message: Пользовательское описание ошибки. Если не передано,
                формируется автоматически.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        details: dict[str, Any] = {
            "entity": entity_name,
        }

        if field is not None:
            details["field"] = field

        if value is not None:
            details["value"] = value

        if field is not None and value is not None:
            default_message = (
                f"Сущность '{entity_name}' с {field}='{value}' уже существует."
            )
        else:
            default_message = f"Сущность '{entity_name}' уже существует."

        super().__init__(
            message or default_message,
            repository=repository,
            operation="create",
            details=details,
            cause=cause,
        )


class ConstraintViolationError(RepositoryError):
    """Исключение при нарушении ограничения базы данных.

    Возникает при нарушении ограничений схемы базы данных или бизнес-правил,
    которые проверяются на уровне базы данных.

    Примеры:
        - нарушение внешнего ключа;
        - нарушение CHECK-ограничения;
        - нарушение NOT NULL;
        - недопустимая связь между сущностями.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Может включать
            имя ограничения, таблицу и колонку.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Нарушено ограничение базы данных.",
        *,
        constraint_name: str | None = None,
        table_name: str | None = None,
        column_name: str | None = None,
        repository: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение нарушения ограничения базы данных.

        Args:
            message: Человекочитаемое описание ошибки.
            constraint_name: Название нарушенного ограничения.
            table_name: Название таблицы, связанной с нарушением.
            column_name: Название колонки, связанной с нарушением.
            repository: Название репозитория, в котором возникла ошибка.
            operation: Название операции репозитория.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        merged_details = details.copy() if details else {}

        if constraint_name is not None:
            merged_details["constraint_name"] = constraint_name

        if table_name is not None:
            merged_details["table_name"] = table_name

        if column_name is not None:
            merged_details["column_name"] = column_name

        super().__init__(
            message,
            repository=repository,
            operation=operation,
            details=merged_details,
            cause=cause,
        )


class EntityNotFoundError(RepositoryError):
    """Исключение при отсутствии запрошенной сущности.

    Возникает, когда репозиторий не находит сущность по идентификатору или
    другим параметрам поиска.

    Примеры:
        - пользователь с указанным ID не существует;
        - роль не найдена;
        - файл или папка не найдены;
        - refresh token отсутствует;
        - публичная ссылка не существует.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Содержит имя
            сущности и параметры поиска.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        entity_name: str,
        *,
        entity_id: Any | None = None,
        lookup: dict[str, Any] | None = None,
        repository: str | None = None,
        message: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение отсутствующей сущности.

        Args:
            entity_name: Название сущности.
            entity_id: Идентификатор сущности.
            lookup: Параметры поиска сущности.
            repository: Название репозитория, в котором возникла ошибка.
            message: Пользовательское описание ошибки. Если не передано,
                формируется автоматически.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        details: dict[str, Any] = {
            "entity": entity_name,
        }

        if entity_id is not None:
            details["entity_id"] = entity_id

        if lookup is not None:
            details["lookup"] = lookup

        default_message = f"Сущность '{entity_name}' не найдена."

        super().__init__(
            message or default_message,
            repository=repository,
            operation="get",
            details=details,
            cause=cause,
        )


class InvalidQueryError(RepositoryError):
    """Исключение при недопустимых параметрах запроса.

    Возникает, когда репозиторий получает некорректные параметры фильтрации,
    сортировки, поиска или другой операции чтения данных.

    Примеры:
        - отрицательный offset;
        - limit больше допустимого значения;
        - неподдерживаемое поле сортировки;
        - неподдерживаемый фильтр.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Недопустимые параметры запроса к базе данных.",
        *,
        repository: str | None = None,
        operation: str | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение недопустимого запроса.

        Args:
            message: Человекочитаемое описание ошибки.
            repository: Название репозитория, в котором возникла ошибка.
            operation: Название операции репозитория.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        super().__init__(
            message,
            repository=repository,
            operation=operation,
            details=details,
            cause=cause,
        )


class InvalidPaginationError(InvalidQueryError):
    """Исключение при некорректных параметрах пагинации.

    Возникает, когда переданные параметры пагинации выходят за допустимые
    границы или противоречат правилам приложения.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки. Может включать
            limit, offset и максимально допустимый limit.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Недопустимые параметры пагинации.",
        *,
        limit: int | None = None,
        offset: int | None = None,
        max_limit: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Инициализирует исключение некорректной пагинации.

        Args:
            message: Человекочитаемое описание ошибки.
            limit: Запрошенное ограничение количества записей.
            offset: Смещение выборки.
            max_limit: Максимально допустимое значение `limit`.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        merged_details = details.copy() if details else {}

        if limit is not None:
            merged_details["limit"] = limit

        if offset is not None:
            merged_details["offset"] = offset

        if max_limit is not None:
            merged_details["max_limit"] = max_limit

        super().__init__(
            message,
            operation="paginate",
            details=merged_details,
        )


class DatabaseHealthCheckError(DatabaseError):
    """Исключение при неуспешной проверке работоспособности базы данных.

    Возникает, когда health-check базы данных не может подтвердить, что база
    доступна и готова обрабатывать запросы.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Проверка работоспособности базы данных не пройдена.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение health-check базы данных.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        super().__init__(
            message,
            details=details,
            cause=cause,
        )


class UnitOfWorkError(TransactionError):
    """Исключение при ошибке выполнения Unit of Work.

    Возникает, когда ошибка происходит в рамках паттерна Unit of Work:
    при выполнении группы операций, управлении транзакцией или согласованном
    завершении работы с репозиториями.

    Attributes:
        message: Человекочитаемое описание ошибки.
        details: Дополнительные диагностические данные ошибки.
        cause: Исходное исключение, ставшее причиной ошибки.
    """

    def __init__(
        self,
        message: str = "Ошибка выполнения Unit of Work.",
        *,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        """Инициализирует исключение Unit of Work.

        Args:
            message: Человекочитаемое описание ошибки.
            details: Дополнительные диагностические данные ошибки.
            cause: Исходное исключение, ставшее причиной ошибки.
        """

        super().__init__(
            message,
            operation="unit_of_work",
            details=details,
            cause=cause,
        )

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from database.models.enums import SystemRole
from schemas.common import BaseSchema


class RoleBase(BaseSchema):
    """Базовые поля роли.

    Используется как общий родитель для схем создания и чтения ролей.
    Содержит техническое имя, стабильный код, человекочитаемое имя и описание
    роли.

    Attributes:
        name: Уникальное техническое имя роли.
        code: Стабильный код роли для бизнес-логики.
        display_name: Человекочитаемое имя роли.
        description: Описание назначения роли.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Уникальное техническое имя роли.",
        examples=["user", "admin"],
    )
    code: str | SystemRole = Field(
        ...,
        description="Стабильный код роли для бизнес-логики.",
        examples=["user", "admin"],
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Человекочитаемое имя роли.",
        examples=["Пользователь", "Администратор"],
    )
    description: str | None = Field(
        default=None,
        max_length=512,
        description="Описание назначения роли.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Проверяет и нормализует техническое имя роли.

        Args:
            value: Исходное техническое имя роли.

        Returns:
            Техническое имя роли без пробелов по краям.

        Raises:
            ValueError: Если имя роли пустое после нормализации.
        """

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("name роли не должен быть пустым.")
        return normalized_value

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        """Нормализует стабильный код роли.

        Поддерживает значения ``SystemRole`` и строковые коды. Строковые коды
        приводятся к нижнему регистру.

        Args:
            value: Исходное значение кода роли.

        Returns:
            Нормализованный строковый код роли или исходное значение, если тип
            не обрабатывается этим валидатором.

        Raises:
            ValueError: Если строковый код пустой после нормализации.
            ValueError: Если строковый код длиннее 64 символов.
        """

        if isinstance(value, SystemRole):
            return value.value

        if isinstance(value, str):
            normalized_value = value.strip().lower()
            if not normalized_value:
                raise ValueError("code роли не должен быть пустым.")
            if len(normalized_value) > 64:
                raise ValueError("code роли не должен превышать 64 символа.")
            return normalized_value

        return value

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        """Проверяет и нормализует человекочитаемое имя роли.

        Args:
            value: Исходное человекочитаемое имя роли.

        Returns:
            Человекочитаемое имя роли без пробелов по краям.

        Raises:
            ValueError: Если имя роли пустое после нормализации.
        """

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("display_name роли не должен быть пустым.")
        return normalized_value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        """Нормализует описание роли.

        Args:
            value: Исходное описание роли.

        Returns:
            Описание без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class RoleCreate(RoleBase):
    """Запрос на создание роли.

    Используется для создания новой роли с техническим именем, стабильным
    кодом, отображаемым именем, описанием и признаками системности и
    активности.

    Attributes:
        name: Уникальное техническое имя роли.
        code: Стабильный код роли для бизнес-логики.
        display_name: Человекочитаемое имя роли.
        description: Описание назначения роли.
        is_system: Признак системной роли, которую нельзя удалить обычным
            способом.
        is_active: Признак активности роли.
    """

    is_system: bool = Field(
        default=False,
        description="Признак системной роли, которую нельзя удалить обычным способом.",
    )
    is_active: bool = Field(
        default=True,
        description="Признак активности роли.",
    )


class RoleUpdate(BaseSchema):
    """Запрос на обновление роли.

    Используется для частичного обновления роли: технического имени, кода,
    отображаемого имени, описания и признака активности.

    Attributes:
        name: Новое техническое имя роли.
        code: Новый стабильный код роли для бизнес-логики.
        display_name: Новое человекочитаемое имя роли.
        description: Новое описание назначения роли.
        is_active: Новый признак активности роли.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Новое техническое имя роли.",
    )
    code: str | SystemRole | None = Field(
        default=None,
        description="Новый стабильный код роли для бизнес-логики.",
    )
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Новое человекочитаемое имя роли.",
    )
    description: str | None = Field(
        default=None,
        max_length=512,
        description="Новое описание назначения роли.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Новый признак активности роли.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        """Проверяет и нормализует новое техническое имя роли.

        Args:
            value: Новое техническое имя роли или ``None``.

        Returns:
            Техническое имя роли без пробелов по краям или ``None``, если поле
            не передано.

        Raises:
            ValueError: Если имя роли пустое после нормализации.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("name роли не должен быть пустым.")
        return normalized_value

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        """Нормализует новый стабильный код роли.

        Args:
            value: Исходное значение кода роли, ``SystemRole`` или ``None``.

        Returns:
            Нормализованный строковый код роли, ``None`` или исходное значение,
            если тип не обрабатывается этим валидатором.

        Raises:
            ValueError: Если строковый код пустой после нормализации.
            ValueError: Если строковый код длиннее 64 символов.
        """

        if value is None:
            return None

        if isinstance(value, SystemRole):
            return value.value

        if isinstance(value, str):
            normalized_value = value.strip().lower()
            if not normalized_value:
                raise ValueError("code роли не должен быть пустым.")
            if len(normalized_value) > 64:
                raise ValueError("code роли не должен превышать 64 символа.")
            return normalized_value

        return value

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        """Проверяет и нормализует новое человекочитаемое имя роли.

        Args:
            value: Новое человекочитаемое имя роли или ``None``.

        Returns:
            Человекочитаемое имя роли без пробелов по краям или ``None``, если
            поле не передано.

        Raises:
            ValueError: Если имя роли пустое после нормализации.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("display_name роли не должен быть пустым.")
        return normalized_value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        """Нормализует новое описание роли.

        Args:
            value: Новое описание роли или ``None``.

        Returns:
            Описание без пробелов по краям или ``None``, если значение
            отсутствует либо содержит только пробельные символы.
        """

        if value is None:
            return None

        normalized_value = value.strip()
        return normalized_value or None


class RoleRead(RoleBase):
    """Полное представление роли.

    Используется для возврата всех публичных данных роли, включая её
    идентификатор, системность, активность и дату создания.

    Attributes:
        name: Уникальное техническое имя роли.
        code: Стабильный код роли для бизнес-логики.
        display_name: Человекочитаемое имя роли.
        description: Описание назначения роли.
        id: Уникальный идентификатор роли.
        is_system: Признак системной роли.
        is_active: Признак активности роли.
        created_at: Дата и время создания роли.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор роли.",
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Стабильный код роли для бизнес-логики.",
        examples=["user", "admin"],
    )
    is_system: bool = Field(
        ...,
        description="Признак системной роли.",
    )
    is_active: bool = Field(
        ...,
        description="Признак активности роли.",
    )
    created_at: datetime = Field(
        ...,
        description="Дата и время создания роли.",
    )


class RoleListItem(BaseSchema):
    """Краткое представление роли для списков и вложенных ответов.

    Используется там, где нужно показать основные данные роли без описания и
    дополнительных служебных полей.

    Attributes:
        id: Уникальный идентификатор роли.
        name: Уникальное техническое имя роли.
        code: Стабильный код роли для бизнес-логики.
        display_name: Человекочитаемое имя роли.
        is_system: Признак системной роли.
        is_active: Признак активности роли.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID = Field(
        ...,
        description="Уникальный идентификатор роли.",
    )
    name: str = Field(
        ...,
        description="Уникальное техническое имя роли.",
    )
    code: str = Field(
        ...,
        description="Стабильный код роли для бизнес-логики.",
    )
    display_name: str = Field(
        ...,
        description="Человекочитаемое имя роли.",
    )
    is_system: bool = Field(
        ...,
        description="Признак системной роли.",
    )
    is_active: bool = Field(
        ...,
        description="Признак активности роли.",
    )


class RoleAssignRequest(BaseSchema):
    """Запрос на назначение роли пользователю.

    Роль можно указать через ``role_id`` или через ``role_code``. При передаче
    ``role_code`` значение нормализуется к нижнему регистру.

    Attributes:
        user_id: Идентификатор пользователя, которому назначается роль.
        role_id: Идентификатор назначаемой роли.
        role_code: Код назначаемой роли. Используется, если ``role_id`` не
            передан.
        assigned_by: Идентификатор администратора или системного пользователя,
            назначившего роль.
    """

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, которому назначается роль.",
    )
    role_id: UUID | None = Field(
        default=None,
        description="Идентификатор назначаемой роли.",
    )
    role_code: str | SystemRole | None = Field(
        default=None,
        description="Код назначаемой роли. Используется, если role_id не передан.",
        examples=["user", "admin"],
    )
    assigned_by: UUID | None = Field(
        default=None,
        description="Идентификатор администратора или системного пользователя, назначившего роль.",
    )

    @field_validator("role_code", mode="before")
    @classmethod
    def normalize_role_code(cls, value: object) -> object:
        """Нормализует код назначаемой роли.

        Args:
            value: Исходный код роли, ``SystemRole`` или ``None``.

        Returns:
            Нормализованный строковый код роли, ``None`` или исходное значение,
            если тип не обрабатывается этим валидатором.

        Raises:
            ValueError: Если строковый код роли пустой после нормализации.
            ValueError: Если строковый код роли длиннее 64 символов.
        """

        if value is None:
            return None

        if isinstance(value, SystemRole):
            return value.value

        if isinstance(value, str):
            normalized_value = value.strip().lower()
            if not normalized_value:
                raise ValueError("role_code не должен быть пустым.")
            if len(normalized_value) > 64:
                raise ValueError("role_code не должен превышать 64 символа.")
            return normalized_value

        return value

    @field_validator("role_code")
    @classmethod
    def validate_role_identifier(
        cls,
        value: str | SystemRole | None,
        info: object,
    ) -> str | SystemRole | None:
        """Проверяет, что назначаемая роль идентифицируема.

        Args:
            value: Код роли после предварительной нормализации.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Код роли или ``None``, если передан ``role_id``.

        Raises:
            ValueError: Если не передан ни ``role_id``, ни ``role_code``.
        """

        data = getattr(info, "data", {})
        role_id = data.get("role_id")

        if role_id is None and value is None:
            raise ValueError("Нужно передать role_id или role_code.")

        return value


class RoleRemoveRequest(BaseSchema):
    """Запрос на снятие роли с пользователя.

    Роль можно указать через ``role_id`` или через ``role_code``. При передаче
    ``role_code`` значение нормализуется к нижнему регистру.

    Attributes:
        user_id: Идентификатор пользователя, у которого снимается роль.
        role_id: Идентификатор снимаемой роли.
        role_code: Код снимаемой роли. Используется, если ``role_id`` не
            передан.
    """

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, у которого снимается роль.",
    )
    role_id: UUID | None = Field(
        default=None,
        description="Идентификатор снимаемой роли.",
    )
    role_code: str | SystemRole | None = Field(
        default=None,
        description="Код снимаемой роли. Используется, если role_id не передан.",
        examples=["user", "admin"],
    )

    @field_validator("role_code", mode="before")
    @classmethod
    def normalize_role_code(cls, value: object) -> object:
        """Нормализует код снимаемой роли.

        Args:
            value: Исходный код роли, ``SystemRole`` или ``None``.

        Returns:
            Нормализованный строковый код роли, ``None`` или исходное значение,
            если тип не обрабатывается этим валидатором.

        Raises:
            ValueError: Если строковый код роли пустой после нормализации.
            ValueError: Если строковый код роли длиннее 64 символов.
        """

        if value is None:
            return None

        if isinstance(value, SystemRole):
            return value.value

        if isinstance(value, str):
            normalized_value = value.strip().lower()
            if not normalized_value:
                raise ValueError("role_code не должен быть пустым.")
            if len(normalized_value) > 64:
                raise ValueError("role_code не должен превышать 64 символа.")
            return normalized_value

        return value

    @field_validator("role_code")
    @classmethod
    def validate_role_identifier(
        cls,
        value: str | SystemRole | None,
        info: object,
    ) -> str | SystemRole | None:
        """Проверяет, что снимаемая роль идентифицируема.

        Args:
            value: Код роли после предварительной нормализации.
            info: Контекст валидации Pydantic с уже обработанными значениями
                полей.

        Returns:
            Код роли или ``None``, если передан ``role_id``.

        Raises:
            ValueError: Если не передан ни ``role_id``, ни ``role_code``.
        """

        data = getattr(info, "data", {})
        role_id = data.get("role_id")

        if role_id is None and value is None:
            raise ValueError("Нужно передать role_id или role_code.")

        return value


class UserRoleRead(BaseSchema):
    """Представление назначенной пользователю роли.

    Используется для отображения связи пользователя с ролью, включая дату
    назначения, автора назначения и краткую информацию о роли.

    Attributes:
        user_id: Идентификатор пользователя, которому назначена роль.
        role_id: Идентификатор назначенной роли.
        assigned_at: Дата и время назначения роли.
        assigned_by: Идентификатор администратора или системного пользователя,
            назначившего роль.
        role: Краткая информация о назначенной роли, если она была загружена.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: UUID = Field(
        ...,
        description="Идентификатор пользователя, которому назначена роль.",
    )
    role_id: UUID = Field(
        ...,
        description="Идентификатор назначенной роли.",
    )
    assigned_at: datetime = Field(
        ...,
        description="Дата и время назначения роли.",
    )
    assigned_by: UUID | None = Field(
        default=None,
        description="Идентификатор администратора или системного пользователя, назначившего роль.",
    )
    role: RoleListItem | None = Field(
        default=None,
        description="Краткая информация о назначенной роли, если она была загружена.",
    )

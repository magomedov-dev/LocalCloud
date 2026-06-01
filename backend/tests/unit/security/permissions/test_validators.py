"""Тесты валидаторов прав доступа: нормализация действий, уровней и UUID."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from database.models.enums import NodeVisibility, PermissionLevel
from security.permissions.enums import PermissionAction, PermissionErrorCode
from security.permissions.exceptions import PermissionCheckError
from security.permissions.validators import (
    get_object_uuid,
    get_optional_user_id,
    normalize_moment,
    normalize_node_visibility,
    normalize_permission_action,
    normalize_permission_level,
)


class _SimpleUser:
    def __init__(self, id: uuid.UUID) -> None:
        self.id = id


class TestNormalizePermissionAction:
    def test_valid_enum_passes_through(self) -> None:
        assert normalize_permission_action(PermissionAction.READ) == PermissionAction.READ

    def test_string_read_works(self) -> None:
        assert normalize_permission_action("read") == PermissionAction.READ

    def test_string_write_works(self) -> None:
        assert normalize_permission_action("write") == PermissionAction.WRITE

    def test_case_insensitive(self) -> None:
        assert normalize_permission_action("READ") == PermissionAction.READ
        assert normalize_permission_action("Download") == PermissionAction.DOWNLOAD

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_permission_action("fly")
        assert exc_info.value.code == PermissionErrorCode.INVALID_ACTION

    def test_non_string_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_permission_action(42)  # type: ignore[arg-type]
        assert exc_info.value.code == PermissionErrorCode.INVALID_ACTION

    def test_none_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_permission_action(None)  # type: ignore[arg-type]
        assert exc_info.value.code == PermissionErrorCode.INVALID_ACTION


class TestNormalizePermissionLevel:
    def test_valid_enum_passes_through(self) -> None:
        assert normalize_permission_level(PermissionLevel.OWNER) == PermissionLevel.OWNER

    def test_string_read_works(self) -> None:
        assert normalize_permission_level("read") == PermissionLevel.READ

    def test_string_write_works(self) -> None:
        assert normalize_permission_level("write") == PermissionLevel.WRITE

    def test_case_insensitive(self) -> None:
        assert normalize_permission_level("OWNER") == PermissionLevel.OWNER

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_permission_level("superadmin")
        assert exc_info.value.code == PermissionErrorCode.INVALID_PERMISSION_LEVEL

    def test_non_string_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_permission_level(99)  # type: ignore[arg-type]
        assert exc_info.value.code == PermissionErrorCode.INVALID_PERMISSION_LEVEL


class TestNormalizeNodeVisibility:
    def test_valid_enum_passes_through(self) -> None:
        assert normalize_node_visibility(NodeVisibility.PUBLIC) == NodeVisibility.PUBLIC

    def test_string_public_works(self) -> None:
        assert normalize_node_visibility("public") == NodeVisibility.PUBLIC

    def test_string_private_works(self) -> None:
        assert normalize_node_visibility("private") == NodeVisibility.PRIVATE

    def test_case_insensitive(self) -> None:
        assert normalize_node_visibility("PUBLIC") == NodeVisibility.PUBLIC

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_node_visibility("hidden")
        assert exc_info.value.code == PermissionErrorCode.INVALID_NODE

    def test_none_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_node_visibility(None)
        assert exc_info.value.code == PermissionErrorCode.INVALID_NODE

    def test_non_string_raises(self) -> None:
        with pytest.raises(PermissionCheckError) as exc_info:
            normalize_node_visibility(123)  # type: ignore[arg-type]
        assert exc_info.value.code == PermissionErrorCode.INVALID_NODE


class TestGetObjectUuid:
    def test_object_with_uuid_id_returns_it(self) -> None:
        uid = uuid.uuid4()
        obj = _SimpleUser(id=uid)
        result = get_object_uuid(obj, "id")
        assert result == uid

    def test_object_with_str_id_converts(self) -> None:
        uid = uuid.uuid4()

        class StrId:
            id: str = str(uid)

        result = get_object_uuid(StrId(), "id")
        assert result == uid

    def test_missing_field_raises(self) -> None:
        class NoId:
            pass

        with pytest.raises(PermissionCheckError):
            get_object_uuid(NoId(), "id")

    def test_non_uuid_string_raises(self) -> None:
        class BadId:
            id: str = "not-a-uuid"

        with pytest.raises(PermissionCheckError):
            get_object_uuid(BadId(), "id")

    def test_field_none_raises(self) -> None:
        class NoneId:
            id = None

        with pytest.raises(PermissionCheckError):
            get_object_uuid(NoneId(), "id")


class TestGetOptionalUserId:
    def test_none_user_returns_none(self) -> None:
        assert get_optional_user_id(None) is None

    def test_user_with_valid_id_returns_uuid(self) -> None:
        uid = uuid.uuid4()
        user = _SimpleUser(id=uid)
        result = get_optional_user_id(user)
        assert result == uid

    def test_user_with_bad_id_returns_none(self) -> None:
        class BadUser:
            id = "not-valid-uuid"

        result = get_optional_user_id(BadUser())  # type: ignore[arg-type]
        assert result is None


class TestNormalizeMoment:
    def test_none_returns_current_utc_time(self) -> None:
        before = datetime.now(UTC)
        result = normalize_moment(None)
        after = datetime.now(UTC)
        assert before <= result <= after

    def test_naive_datetime_gets_utc_tzinfo(self) -> None:
        naive = datetime(2024, 1, 1, 12, 0, 0)
        result = normalize_moment(naive)
        assert result.tzinfo is not None
        assert result.replace(tzinfo=None) == naive

    def test_aware_datetime_returned_as_utc(self) -> None:
        aware = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        result = normalize_moment(aware)
        assert result.tzinfo is not None
        assert result == aware

    def test_aware_non_utc_converted_to_utc(self) -> None:
        import zoneinfo
        try:
            tz_plus2 = zoneinfo.ZoneInfo("Europe/Berlin")
        except Exception:
            # запасной вариант для окружений без tzdata
            from datetime import timezone as tz
            tz_plus2 = tz(timedelta(hours=2))

        aware = datetime(2024, 6, 1, 12, 0, 0, tzinfo=tz_plus2)
        result = normalize_moment(aware)
        # должно быть UTC
        assert result.tzinfo == UTC or str(result.tzinfo) == "UTC"

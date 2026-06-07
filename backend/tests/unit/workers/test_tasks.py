"""Тесты утилит задач воркера: результаты, разбор payload и сериализация."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4

import pytest

from workers.exceptions import WorkerTaskHandlerError
from workers.tasks import (
    cast_dict_jsonable,
    failure_result,
    jsonable,
    optional_payload_value,
    payload_datetime,
    payload_int,
    payload_uuid,
    require_payload_value,
    retry_result,
    success_result,
)
from workers.types import WorkerTaskExecutionResult


# ---------------------------------------------------------------------------
# success_result
# ---------------------------------------------------------------------------


class TestSuccessResult:
    def test_returns_execution_result(self) -> None:
        result = success_result()
        assert isinstance(result, WorkerTaskExecutionResult)

    def test_success_is_true(self) -> None:
        result = success_result()
        assert result.success is True

    def test_progress_percent_defaults_to_100(self) -> None:
        result = success_result()
        assert result.progress_percent == 100

    def test_retry_is_false(self) -> None:
        result = success_result()
        assert result.retry is False

    def test_result_data_none_by_default(self) -> None:
        result = success_result()
        assert result.result_data is None

    def test_result_data_none_when_passed_none(self) -> None:
        result = success_result(result_data=None)
        assert result.result_data is None

    def test_result_data_passed_through_jsonable(self) -> None:
        uid = uuid4()
        result = success_result(result_data={"id": uid})
        assert result.result_data == {"id": str(uid)}

    def test_custom_progress_percent(self) -> None:
        result = success_result(progress_percent=75)
        assert result.progress_percent == 75

    def test_plain_dict_stored_as_is(self) -> None:
        result = success_result(result_data={"key": "value"})
        assert result.result_data == {"key": "value"}


# ---------------------------------------------------------------------------
# failure_result
# ---------------------------------------------------------------------------


class TestFailureResult:
    def test_success_is_false(self) -> None:
        result = failure_result("error")
        assert result.success is False

    def test_retry_defaults_to_false(self) -> None:
        result = failure_result("error")
        assert result.retry is False

    def test_retry_true_when_specified(self) -> None:
        result = failure_result("error", retry=True)
        assert result.retry is True

    def test_error_message_stored(self) -> None:
        result = failure_result("something went wrong")
        assert result.error_message == "something went wrong"

    def test_error_code_stored(self) -> None:
        result = failure_result("error", error_code="ERR_001")
        assert result.error_code == "ERR_001"

    def test_error_code_none_by_default(self) -> None:
        result = failure_result("error")
        assert result.error_code is None

    def test_progress_percent_defaults_to_0(self) -> None:
        result = failure_result("error")
        assert result.progress_percent == 0

    def test_custom_progress_percent(self) -> None:
        result = failure_result("error", progress_percent=42)
        assert result.progress_percent == 42

    def test_result_data_none_by_default(self) -> None:
        result = failure_result("error")
        assert result.result_data is None

    def test_result_data_jsonable(self) -> None:
        uid = uuid4()
        result = failure_result("error", result_data={"id": uid})
        assert result.result_data == {"id": str(uid)}


# ---------------------------------------------------------------------------
# retry_result
# ---------------------------------------------------------------------------


class TestRetryResult:
    def test_success_is_false(self) -> None:
        result = retry_result("temporary error")
        assert result.success is False

    def test_retry_is_true(self) -> None:
        result = retry_result("temporary error")
        assert result.retry is True

    def test_error_message_stored(self) -> None:
        result = retry_result("connection timeout")
        assert result.error_message == "connection timeout"

    def test_error_code_stored(self) -> None:
        result = retry_result("error", error_code="TIMEOUT")
        assert result.error_code == "TIMEOUT"

    def test_progress_percent_is_0(self) -> None:
        result = retry_result("error")
        assert result.progress_percent == 0

    def test_result_data_jsonable(self) -> None:
        uid = uuid4()
        result = retry_result("error", result_data={"id": uid})
        assert result.result_data == {"id": str(uid)}


# ---------------------------------------------------------------------------
# require_payload_value
# ---------------------------------------------------------------------------


class TestRequirePayloadValue:
    def test_returns_value_when_key_exists(self) -> None:
        payload = {"user_id": "abc"}
        assert require_payload_value(payload, "user_id") == "abc"

    def test_raises_when_key_missing(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            require_payload_value({}, "missing_key")

    def test_raises_when_wrong_type(self) -> None:
        payload = {"count": "not-an-int"}
        with pytest.raises(WorkerTaskHandlerError):
            require_payload_value(payload, "count", expected_type=int)

    def test_returns_value_when_type_matches(self) -> None:
        payload = {"count": 42}
        assert require_payload_value(payload, "count", expected_type=int) == 42

    def test_no_expected_type_accepts_any_type(self) -> None:
        payload = {"data": [1, 2, 3]}
        assert require_payload_value(payload, "data") == [1, 2, 3]

    def test_accepts_tuple_of_types(self) -> None:
        payload = {"value": 3.14}
        result = require_payload_value(payload, "value", expected_type=(int, float))
        assert result == 3.14

    def test_raises_with_details_about_key(self) -> None:
        with pytest.raises(WorkerTaskHandlerError) as exc_info:
            require_payload_value({}, "my_key")
        assert "my_key" in str(exc_info.value.details)


# ---------------------------------------------------------------------------
# optional_payload_value
# ---------------------------------------------------------------------------


class TestOptionalPayloadValue:
    def test_returns_value_when_key_exists_and_type_matches(self) -> None:
        payload = {"limit": 100}
        assert optional_payload_value(payload, "limit", expected_type=int) == 100

    def test_returns_default_when_key_missing(self) -> None:
        result = optional_payload_value({}, "missing", default=42)
        assert result == 42

    def test_returns_default_when_value_is_none(self) -> None:
        payload = {"key": None}
        result = optional_payload_value(payload, "key", default="fallback")
        assert result == "fallback"

    def test_default_is_none_when_not_provided(self) -> None:
        result = optional_payload_value({}, "missing")
        assert result is None

    def test_raises_when_value_has_wrong_type(self) -> None:
        payload = {"count": "not-an-int"}
        with pytest.raises(WorkerTaskHandlerError):
            optional_payload_value(payload, "count", expected_type=int)

    def test_no_expected_type_accepts_any_type(self) -> None:
        payload = {"data": {"nested": True}}
        result = optional_payload_value(payload, "data")
        assert result == {"nested": True}

    def test_raises_with_tuple_expected_type_includes_all_names(self) -> None:
        # Значение неверного типа с кортежем ожидаемых типов задействует
        # ветку `" | ".join(...)` в _type_name.
        payload = {"count": "not-a-number"}
        with pytest.raises(WorkerTaskHandlerError) as excinfo:
            optional_payload_value(payload, "count", expected_type=(int, float))
        assert excinfo.value.details["expected_type"] == "int | float"


# ---------------------------------------------------------------------------
# payload_uuid
# ---------------------------------------------------------------------------


class TestPayloadUuid:
    def test_returns_uuid_when_value_is_uuid(self) -> None:
        uid = uuid4()
        payload = {"id": uid}
        assert payload_uuid(payload, "id") == uid

    def test_parses_uuid_from_string(self) -> None:
        uid = uuid4()
        payload = {"id": str(uid)}
        result = payload_uuid(payload, "id")
        assert result == uid
        assert isinstance(result, UUID)

    def test_raises_when_string_is_not_valid_uuid(self) -> None:
        payload = {"id": "not-a-uuid"}
        with pytest.raises(WorkerTaskHandlerError):
            payload_uuid(payload, "id")

    def test_raises_when_value_is_neither_uuid_nor_string(self) -> None:
        payload = {"id": 12345}
        with pytest.raises(WorkerTaskHandlerError):
            payload_uuid(payload, "id")

    def test_raises_when_key_is_missing(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            payload_uuid({}, "id")

    def test_parses_uuid_with_curly_braces_style(self) -> None:
        uid = uuid4()
        payload = {"id": f"{{{uid}}}"}
        # UUID() умеет разбирать формат "{...}"
        result = payload_uuid(payload, "id")
        assert result == uid


# ---------------------------------------------------------------------------
# payload_datetime
# ---------------------------------------------------------------------------


class TestPayloadDatetime:
    def test_returns_datetime_when_value_is_datetime(self) -> None:
        dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
        payload = {"ts": dt}
        assert payload_datetime(payload, "ts") == dt

    def test_parses_datetime_from_iso_string(self) -> None:
        dt = datetime(2024, 6, 15, 10, 30, 0)
        payload = {"ts": dt.isoformat()}
        result = payload_datetime(payload, "ts")
        assert result == dt

    def test_raises_for_invalid_iso_string(self) -> None:
        payload = {"ts": "not-a-date"}
        with pytest.raises(WorkerTaskHandlerError):
            payload_datetime(payload, "ts")

    def test_raises_for_wrong_type(self) -> None:
        payload = {"ts": 1234567890}
        with pytest.raises(WorkerTaskHandlerError):
            payload_datetime(payload, "ts")

    def test_raises_when_key_missing(self) -> None:
        with pytest.raises(WorkerTaskHandlerError):
            payload_datetime({}, "ts")


# ---------------------------------------------------------------------------
# payload_int
# ---------------------------------------------------------------------------


class TestPayloadInt:
    def test_returns_int_value(self) -> None:
        payload = {"count": 5}
        assert payload_int(payload, "count") == 5

    def test_returns_none_default_when_key_missing(self) -> None:
        result = payload_int({}, "count")
        assert result is None

    def test_returns_custom_default_when_key_missing(self) -> None:
        result = payload_int({}, "count", default=10)
        assert result == 10

    def test_raises_when_not_an_int(self) -> None:
        payload = {"count": "five"}
        with pytest.raises(WorkerTaskHandlerError):
            payload_int(payload, "count")

    def test_raises_for_bool_value(self) -> None:
        # bool — подкласс int, но должен отклоняться
        payload = {"count": True}
        with pytest.raises(WorkerTaskHandlerError):
            payload_int(payload, "count")

    def test_raises_when_below_min_value(self) -> None:
        payload = {"count": -1}
        with pytest.raises(WorkerTaskHandlerError):
            payload_int(payload, "count", min_value=0)

    def test_raises_when_above_max_value(self) -> None:
        payload = {"count": 101}
        with pytest.raises(WorkerTaskHandlerError):
            payload_int(payload, "count", max_value=100)

    def test_accepts_value_at_min_boundary(self) -> None:
        payload = {"count": 0}
        assert payload_int(payload, "count", min_value=0) == 0

    def test_accepts_value_at_max_boundary(self) -> None:
        payload = {"count": 100}
        assert payload_int(payload, "count", max_value=100) == 100

    def test_returns_none_when_value_is_none(self) -> None:
        payload = {"count": None}
        result = payload_int(payload, "count")
        assert result is None

    def test_accepts_zero(self) -> None:
        payload = {"count": 0}
        assert payload_int(payload, "count") == 0

    def test_accepts_negative(self) -> None:
        payload = {"count": -5}
        assert payload_int(payload, "count") == -5


# ---------------------------------------------------------------------------
# jsonable
# ---------------------------------------------------------------------------


class _SampleEnum(Enum):
    ALPHA = "alpha"
    BETA = 2


class _SomeObject:
    def __str__(self) -> str:
        return "custom-str"


class TestJsonable:
    def test_none_returns_none(self) -> None:
        assert jsonable(None) is None

    def test_str_returns_str(self) -> None:
        assert jsonable("hello") == "hello"

    def test_int_returns_int(self) -> None:
        assert jsonable(42) == 42

    def test_float_returns_float(self) -> None:
        assert jsonable(3.14) == 3.14

    def test_bool_returns_bool(self) -> None:
        assert jsonable(True) is True
        assert jsonable(False) is False

    def test_uuid_converted_to_str(self) -> None:
        uid = uuid4()
        result = jsonable(uid)
        assert result == str(uid)
        assert isinstance(result, str)

    def test_datetime_converted_to_iso_string(self) -> None:
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = jsonable(dt)
        assert result == dt.isoformat()
        assert isinstance(result, str)

    def test_enum_returns_value(self) -> None:
        assert jsonable(_SampleEnum.ALPHA) == "alpha"
        assert jsonable(_SampleEnum.BETA) == 2

    def test_dict_with_jsonable_values(self) -> None:
        uid = uuid4()
        result = jsonable({"id": uid, "count": 5})
        assert result == {"id": str(uid), "count": 5}

    def test_dict_keys_converted_to_str(self) -> None:
        result = jsonable({1: "one", 2: "two"})
        assert "1" in result
        assert "2" in result

    def test_list_with_jsonable_values(self) -> None:
        uid = uuid4()
        result = jsonable([uid, 42, "text"])
        assert result == [str(uid), 42, "text"]

    def test_nested_dict_in_list(self) -> None:
        uid = uuid4()
        result = jsonable([{"id": uid}])
        assert result == [{"id": str(uid)}]

    def test_other_object_returns_str(self) -> None:
        obj = _SomeObject()
        result = jsonable(obj)
        assert result == "custom-str"

    def test_empty_dict(self) -> None:
        assert jsonable({}) == {}

    def test_empty_list(self) -> None:
        assert jsonable([]) == []


# ---------------------------------------------------------------------------
# cast_dict_jsonable
# ---------------------------------------------------------------------------


class TestCastDictJsonable:
    def test_plain_dict_returned(self) -> None:
        result = cast_dict_jsonable({"key": "value"})
        assert result == {"key": "value"}

    def test_uuid_values_converted(self) -> None:
        uid = uuid4()
        result = cast_dict_jsonable({"id": uid})
        assert result["id"] == str(uid)

    def test_datetime_values_converted(self) -> None:
        dt = datetime(2024, 3, 15, tzinfo=UTC)
        result = cast_dict_jsonable({"ts": dt})
        assert result["ts"] == dt.isoformat()

    def test_all_keys_are_strings(self) -> None:
        result = cast_dict_jsonable({1: "one", 2: "two"})
        assert all(isinstance(k, str) for k in result)

    def test_none_values_preserved(self) -> None:
        result = cast_dict_jsonable({"key": None})
        assert result["key"] is None

    def test_nested_dict_values_converted(self) -> None:
        uid = uuid4()
        result = cast_dict_jsonable({"nested": {"id": uid}})
        assert result["nested"]["id"] == str(uid)

    def test_list_values_converted(self) -> None:
        uid = uuid4()
        result = cast_dict_jsonable({"ids": [uid]})
        assert result["ids"] == [str(uid)]

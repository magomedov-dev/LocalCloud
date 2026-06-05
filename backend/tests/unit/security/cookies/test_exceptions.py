"""Тесты исключения CookieError: хранение данных, str и to_dict."""

from __future__ import annotations


from security.cookies.enums import CookieErrorCode
from security.cookies.exceptions import CookieError


class TestCookieError:
    def test_message_stored(self) -> None:
        err = CookieError("test message", code=CookieErrorCode.INVALID_COOKIE_NAME)
        assert err.message == "test message"

    def test_code_stored(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_MAX_AGE)
        assert err.code == CookieErrorCode.INVALID_MAX_AGE

    def test_details_copied(self) -> None:
        original = {"key": "value"}
        err = CookieError("msg", code=CookieErrorCode.INVALID_COOKIE_NAME, details=original)
        assert err.details == {"key": "value"}
        # изменение исходного словаря не влияет на сохранённые details
        original["extra"] = "x"
        assert "extra" not in err.details

    def test_details_empty_by_default(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_COOKIE_NAME)
        assert err.details == {}

    def test_str_without_details(self) -> None:
        err = CookieError("only message", code=CookieErrorCode.INVALID_COOKIE_NAME)
        assert str(err) == "only message"

    def test_str_with_details(self) -> None:
        err = CookieError(
            "base message",
            code=CookieErrorCode.INVALID_COOKIE_NAME,
            details={"k": "v"},
        )
        result = str(err)
        assert "base message" in result
        assert "Details" in result

    def test_to_dict_basic_keys(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_TOKEN)
        d = err.to_dict()
        assert d["error"] == "CookieError"
        assert d["code"] == CookieErrorCode.INVALID_TOKEN.value
        assert d["message"] == "msg"

    def test_to_dict_with_details(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_SETTINGS, details={"foo": "bar"})
        d = err.to_dict()
        assert "details" in d
        assert d["details"]["foo"] == "bar"

    def test_to_dict_without_details_omits_key(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_SETTINGS)
        d = err.to_dict()
        assert "details" not in d

    def test_cause_stored(self) -> None:
        original = ValueError("original")
        err = CookieError("msg", code=CookieErrorCode.INVALID_SETTINGS, cause=original)
        assert err.cause is original
        assert err.__cause__ is original

    def test_to_dict_with_cause(self) -> None:
        original = RuntimeError("boom")
        err = CookieError("msg", code=CookieErrorCode.INVALID_SETTINGS, cause=original)
        d = err.to_dict()
        assert d["cause"] == "RuntimeError"

    def test_to_dict_without_cause_omits_key(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_SETTINGS)
        d = err.to_dict()
        assert "cause" not in d

    def test_default_code_is_invalid_settings(self) -> None:
        err = CookieError("msg")
        assert err.code == CookieErrorCode.INVALID_SETTINGS

    def test_is_exception(self) -> None:
        err = CookieError("msg", code=CookieErrorCode.INVALID_COOKIE_NAME)
        assert isinstance(err, Exception)

    def test_args_contains_message(self) -> None:
        err = CookieError("my message", code=CookieErrorCode.INVALID_COOKIE_NAME)
        assert err.args[0] == "my message"

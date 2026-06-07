"""Модульные тесты общих схем (пагинация, ответы, ошибки)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.common import (
    ErrorDetail,
    ErrorResponse,
    MessageResponse,
    PageMeta,
    PageResponse,
    PaginationParams,
    StatusResponse,
    ValidationErrorItem,
    ValidationErrorResponse,
)


class TestPageMetaComputedFields:
    """Тесты вычисляемых полей метаданных страницы."""

    def _make(self, limit: int, offset: int, total: int, count: int) -> PageMeta:
        return PageMeta(limit=limit, offset=offset, total=total, count=count)

    # has_next (есть ли следующая страница)
    def test_has_next_true_when_more_items_remain(self):
        m = self._make(limit=10, offset=0, total=15, count=10)
        assert m.has_next is True

    def test_has_next_false_when_all_items_returned(self):
        m = self._make(limit=10, offset=0, total=10, count=10)
        assert m.has_next is False

    def test_has_next_false_when_count_equals_remaining(self):
        m = self._make(limit=10, offset=5, total=10, count=5)
        assert m.has_next is False

    def test_has_next_false_when_total_zero(self):
        m = self._make(limit=10, offset=0, total=0, count=0)
        assert m.has_next is False

    # has_previous (есть ли предыдущая страница)
    def test_has_previous_true_when_offset_positive(self):
        m = self._make(limit=10, offset=10, total=30, count=10)
        assert m.has_previous is True

    def test_has_previous_false_when_offset_zero(self):
        m = self._make(limit=10, offset=0, total=30, count=10)
        assert m.has_previous is False

    # page (номер текущей страницы)
    def test_page_first_page(self):
        m = self._make(limit=10, offset=0, total=30, count=10)
        assert m.page == 1

    def test_page_second_page(self):
        m = self._make(limit=10, offset=10, total=30, count=10)
        assert m.page == 2

    def test_page_third_page(self):
        m = self._make(limit=10, offset=20, total=30, count=10)
        assert m.page == 3

    def test_page_partial_page(self):
        m = self._make(limit=5, offset=7, total=20, count=5)
        assert m.page == 2  # 7 // 5 + 1 = 2

    # pages (общее количество страниц)
    def test_pages_zero_when_total_is_zero(self):
        m = self._make(limit=10, offset=0, total=0, count=0)
        assert m.pages == 0

    def test_pages_exact_division(self):
        m = self._make(limit=5, offset=0, total=10, count=5)
        assert m.pages == 2

    def test_pages_rounds_up(self):
        m = self._make(limit=5, offset=0, total=11, count=5)
        assert m.pages == 3

    def test_pages_single_page(self):
        m = self._make(limit=100, offset=0, total=7, count=7)
        assert m.pages == 1

    def test_page_returns_one_when_limit_non_positive(self):
        # ge=1 и validate_assignment делают limit<=0 недостижимым при обычном
        # создании; model_construct обходит валидацию, чтобы проверить
        # защитную ветку в вычисляемом поле `page`.
        m = PageMeta.model_construct(limit=0, offset=20, total=30, count=0)
        assert m.page == 1


class TestPageMetaValidation:
    """Тесты валидации полей метаданных страницы."""

    def test_valid_construction(self):
        m = PageMeta(limit=10, offset=0, total=100, count=10)
        assert m.limit == 10

    def test_limit_must_be_positive(self):
        with pytest.raises(ValidationError):
            PageMeta(limit=0, offset=0, total=0, count=0)

    def test_offset_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            PageMeta(limit=10, offset=-1, total=0, count=0)

    def test_total_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            PageMeta(limit=10, offset=0, total=-1, count=0)

    def test_count_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            PageMeta(limit=10, offset=0, total=10, count=-1)


class TestErrorResponse:
    """Тесты схемы ответа об ошибке."""

    def test_success_is_false_by_default(self):
        r = ErrorResponse(error="SomeError", message="Something went wrong")
        assert r.success is False

    def test_required_fields(self):
        r = ErrorResponse(error="NotFound", message="Resource not found")
        assert r.error == "NotFound"
        assert r.message == "Resource not found"

    def test_missing_error_raises(self):
        with pytest.raises(ValidationError):
            ErrorResponse(message="oops")

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            ErrorResponse(error="BadError")

    def test_empty_error_raises(self):
        with pytest.raises(ValidationError):
            ErrorResponse(error="", message="msg")

    def test_empty_message_raises(self):
        with pytest.raises(ValidationError):
            ErrorResponse(error="Err", message="")

    def test_optional_fields_default_to_none(self):
        r = ErrorResponse(error="E", message="M")
        assert r.details is None
        assert r.request_id is None

    def test_details_can_be_list_of_error_details(self):
        detail = ErrorDetail(message="field error", field="email")
        r = ErrorResponse(error="E", message="M", details=[detail])
        assert isinstance(r.details, list)

    def test_details_can_be_dict(self):
        r = ErrorResponse(error="E", message="M", details={"key": "value"})
        assert isinstance(r.details, dict)


class TestPaginationParams:
    """Тесты параметров пагинации."""

    def test_defaults(self):
        p = PaginationParams()
        assert p.limit == 50
        assert p.offset == 0

    def test_valid_limit_range(self):
        PaginationParams(limit=1)
        PaginationParams(limit=100)

    def test_limit_zero_invalid(self):
        with pytest.raises(ValidationError):
            PaginationParams(limit=0)

    def test_limit_over_100_invalid(self):
        with pytest.raises(ValidationError):
            PaginationParams(limit=101)

    def test_negative_offset_invalid(self):
        with pytest.raises(ValidationError):
            PaginationParams(offset=-1)

    def test_zero_offset_valid(self):
        p = PaginationParams(offset=0)
        assert p.offset == 0

    def test_positive_offset_valid(self):
        p = PaginationParams(offset=100)
        assert p.offset == 100


class TestMessageResponse:
    """Тесты схемы текстового ответа."""

    def test_valid(self):
        r = MessageResponse(message="hello")
        assert r.message == "hello"

    def test_empty_message_invalid(self):
        with pytest.raises(ValidationError):
            MessageResponse(message="")

    def test_whitespace_stripped(self):
        r = MessageResponse(message="  hello  ")
        assert r.message == "hello"


class TestStatusResponse:
    """Тесты схемы ответа со статусом."""

    def test_valid_with_required_fields(self):
        r = StatusResponse(message="done", success=True)
        assert r.success is True
        assert r.status is None

    def test_status_optional(self):
        r = StatusResponse(message="done", success=False, status="deleted")
        assert r.status == "deleted"

    def test_missing_success_raises(self):
        with pytest.raises(ValidationError):
            StatusResponse(message="done")


class TestValidationErrorResponse:
    """Тесты схемы ответа об ошибке валидации."""

    def test_defaults(self):
        r = ValidationErrorResponse()
        assert r.success is False
        assert r.error == "ValidationError"
        assert r.errors == []

    def test_with_items(self):
        item = ValidationErrorItem(field="email", message="invalid email")
        r = ValidationErrorResponse(errors=[item])
        assert len(r.errors) == 1
        assert r.errors[0].field == "email"


class TestPageResponse:
    """Тесты схемы постраничного ответа."""

    def test_valid_page_response(self):
        meta = PageMeta(limit=10, offset=0, total=1, count=1)
        pr = PageResponse[str](items=["hello"], meta=meta)
        assert pr.items == ["hello"]
        assert pr.meta.total == 1

    def test_empty_items_default(self):
        meta = PageMeta(limit=10, offset=0, total=0, count=0)
        pr = PageResponse[str](meta=meta)
        assert pr.items == []

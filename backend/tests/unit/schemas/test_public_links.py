"""Модульные тесты схем публичных ссылок."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from database.models.enums import (
    BackgroundTaskStatus,
    PublicLinkPermissionType,
    PublicLinkStatus,
)
from schemas.public_links import (
    PublicLinkAccessRequest,
    PublicLinkCreateRequest,
    PublicLinkDownloadResponse,
    PublicLinkQueryParams,
    PublicLinkRead,
    PublicLinkRevokeRequest,
    PublicLinkUpdateRequest,
)


class TestPublicLinkCreateRequest:
    """Тесты запроса создания публичной ссылки."""

    def test_valid_minimal(self):
        r = PublicLinkCreateRequest(node_id=uuid4())
        assert r.permission_type == PublicLinkPermissionType.DOWNLOAD
        assert r.expires_at is None
        assert r.max_downloads is None
        assert r.password is None
        assert r.description is None

    def test_node_id_required(self):
        with pytest.raises(ValidationError):
            PublicLinkCreateRequest()

    def test_password_normalization(self):
        r = PublicLinkCreateRequest(node_id=uuid4(), password="  secret  ")
        assert r.password == "secret"

    def test_whitespace_password_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PublicLinkCreateRequest(node_id=uuid4(), password="   ")

    def test_description_normalization(self):
        r = PublicLinkCreateRequest(node_id=uuid4(), description="  my link  ")
        assert r.description == "my link"

    def test_whitespace_description_becomes_none(self):
        r = PublicLinkCreateRequest(node_id=uuid4(), description="   ")
        assert r.description is None

    def test_negative_max_downloads_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkCreateRequest(node_id=uuid4(), max_downloads=-1)

    def test_zero_max_downloads_valid(self):
        r = PublicLinkCreateRequest(node_id=uuid4(), max_downloads=0)
        assert r.max_downloads == 0

    def test_description_too_long_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkCreateRequest(node_id=uuid4(), description="a" * 2001)

    def test_password_too_long_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkCreateRequest(node_id=uuid4(), password="a" * 129)


class TestPublicLinkUpdateRequest:
    """Тесты запроса обновления публичной ссылки."""

    def test_at_least_one_field_required(self):
        with pytest.raises(ValidationError):
            PublicLinkUpdateRequest()

    def test_valid_single_field(self):
        r = PublicLinkUpdateRequest(is_active=True)
        assert r.is_active is True

    def test_password_and_clear_password_conflict_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkUpdateRequest(password="new_pass", clear_password=True)

    def test_clear_password_without_password_valid(self):
        r = PublicLinkUpdateRequest(clear_password=True)
        assert r.clear_password is True
        assert r.password is None

    def test_password_normalization(self):
        r = PublicLinkUpdateRequest(password="  mypass  ")
        assert r.password == "mypass"

    def test_whitespace_password_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PublicLinkUpdateRequest(password="   ")


class TestPublicLinkRead:
    """Тесты схемы чтения публичной ссылки."""

    def _make(self, **kwargs):
        now = datetime.now(timezone.utc)
        defaults = {
            "id": uuid4(),
            "node_id": uuid4(),
            "token": "abc123",
            "permission_type": PublicLinkPermissionType.DOWNLOAD,
            "status": PublicLinkStatus.ACTIVE,
            "download_count": 0,
            "view_count": 0,
            "upload_count": 0,
            "is_active": True,
            "created_at": now,
        }
        defaults.update(kwargs)
        return PublicLinkRead(**defaults)

    def test_valid_minimal(self):
        r = self._make()
        assert r.has_password is False
        assert r.is_download_limit_reached is False
        assert r.is_revoked is False

    def test_is_download_limit_reached_true(self):
        r = self._make(max_downloads=5, download_count=5)
        assert r.is_download_limit_reached is True

    def test_is_download_limit_reached_false_no_limit(self):
        r = self._make(max_downloads=None, download_count=100)
        assert r.is_download_limit_reached is False

    def test_is_revoked_true_when_status_revoked(self):
        r = self._make(status=PublicLinkStatus.REVOKED)
        assert r.is_revoked is True

    def test_is_revoked_true_when_revoked_at_set(self):
        now = datetime.now(timezone.utc)
        r = self._make(revoked_at=now, status=PublicLinkStatus.ACTIVE)
        assert r.is_revoked is True

    def test_is_revoked_false_when_active(self):
        r = self._make(status=PublicLinkStatus.ACTIVE, revoked_at=None)
        assert r.is_revoked is False


class TestPublicLinkAccessRequest:
    """Тесты запроса доступа по публичной ссылке."""

    def test_valid(self):
        r = PublicLinkAccessRequest(token="my-token")
        assert r.token == "my-token"

    def test_token_required(self):
        with pytest.raises(ValidationError):
            PublicLinkAccessRequest()

    def test_token_strips_whitespace(self):
        r = PublicLinkAccessRequest(token="  abc  ")
        assert r.token == "abc"

    def test_whitespace_token_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkAccessRequest(token="   ")

    def test_password_optional(self):
        r = PublicLinkAccessRequest(token="tok", password="secret")
        assert r.password == "secret"

    def test_whitespace_password_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkAccessRequest(token="tok", password="   ")


class TestPublicLinkRevokeRequest:
    """Тесты запроса отзыва публичной ссылки."""

    def test_no_reason(self):
        r = PublicLinkRevokeRequest()
        assert r.revoke_reason is None

    def test_reason_normalization(self):
        r = PublicLinkRevokeRequest(revoke_reason="  abuse  ")
        assert r.revoke_reason == "abuse"

    def test_whitespace_reason_becomes_none(self):
        r = PublicLinkRevokeRequest(revoke_reason="   ")
        assert r.revoke_reason is None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            PublicLinkRevokeRequest(revoke_reason="a" * 513)


class TestPublicLinkDownloadResponse:
    """Тесты ответа на скачивание по публичной ссылке."""

    def _make(self, **kwargs):
        now = datetime.now(timezone.utc)
        defaults = {
            "presigned_url": "https://example.com/download",
            "expires_at": now,
        }
        defaults.update(kwargs)
        return PublicLinkDownloadResponse(**defaults)

    def test_valid(self):
        r = self._make()
        assert r.method == "GET"
        assert r.headers == {}

    def test_method_uppercased(self):
        r = self._make(method="get")
        assert r.method == "GET"

    def test_empty_method_raises(self):
        with pytest.raises(ValidationError):
            self._make(method="")

    def test_presigned_url_required(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            PublicLinkDownloadResponse(expires_at=now)


class TestPublicLinkQueryParams:
    """Тесты параметров запроса списка публичных ссылок."""

    def test_defaults(self):
        q = PublicLinkQueryParams()
        assert q.sort_by == "created_at"
        assert q.sort_desc is True

    def test_query_normalization(self):
        q = PublicLinkQueryParams(query="  test  ")
        assert q.query == "test"

    def test_whitespace_query_raises_validation_error(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PublicLinkQueryParams(query="   ")

    def test_created_to_before_from_raises(self):
        d1 = datetime(2024, 1, 10, tzinfo=timezone.utc)
        d2 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            PublicLinkQueryParams(created_from=d1, created_to=d2)


class TestPublicLinkNoneBranches:
    """Тесты ветвей с явной передачей None в схемах публичных ссылок."""

    def test_create_optional_text_none(self):
        r = PublicLinkCreateRequest(node_id=uuid4(), password=None, description=None)
        assert r.password is None
        assert r.description is None

    def test_update_optional_text_none(self):
        r = PublicLinkUpdateRequest(password=None, description=None, is_active=True)
        assert r.password is None
        assert r.description is None

    def test_access_password_none(self):
        r = PublicLinkAccessRequest(token="tok123", password=None)
        assert r.password is None

    def test_revoke_reason_none(self):
        r = PublicLinkRevokeRequest(revoke_reason=None)
        assert r.revoke_reason is None

    def test_revoke_reason_whitespace_none(self):
        r = PublicLinkRevokeRequest(revoke_reason="   ")
        assert r.revoke_reason is None

    def test_query_params_query_none(self):
        q = PublicLinkQueryParams(query=None)
        assert q.query is None

    def test_query_params_valid_created_range(self):
        d_from = datetime(2024, 1, 1, tzinfo=timezone.utc)
        d_to = datetime(2024, 1, 10, tzinfo=timezone.utc)
        q = PublicLinkQueryParams(created_from=d_from, created_to=d_to)
        assert q.created_to == d_to

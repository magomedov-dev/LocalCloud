"""Unit-тесты классификации MIME-типов для превью (core/preview_mime)."""
from __future__ import annotations

import pytest

from core.preview_mime import (
    PREVIEW_IMAGE_CONTENT_TYPE,
    PREVIEW_TEXT_CONTENT_TYPE,
    is_image,
    is_pdf,
    is_text,
    is_video,
    preview_content_type,
    preview_required,
    produces_image_thumbnail,
)


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("image/png", True),
        ("IMAGE/JPEG", True),
        ("video/mp4", False),
        ("", False),
        (None, False),
    ],
)
def test_is_image(mime, expected) -> None:
    assert is_image(mime) is expected


@pytest.mark.parametrize(
    "mime, expected",
    [("video/mp4", True), ("video/webm", True), ("image/png", False), (None, False)],
)
def test_is_video(mime, expected) -> None:
    assert is_video(mime) is expected


@pytest.mark.parametrize(
    "mime, expected",
    [("application/pdf", True), ("APPLICATION/PDF", True), ("text/plain", False)],
)
def test_is_pdf(mime, expected) -> None:
    assert is_pdf(mime) is expected


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("text/plain", True),
        ("text/csv", True),
        ("application/json", True),
        ("image/png", False),
    ],
)
def test_is_text(mime, expected) -> None:
    assert is_text(mime) is expected


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("image/png", True),
        ("video/mp4", True),
        ("application/pdf", True),
        ("text/plain", True),
        ("application/json", True),
        ("application/zip", False),
        ("application/octet-stream", False),
        ("", False),
        (None, False),
    ],
)
def test_preview_required(mime, expected) -> None:
    assert preview_required(mime) is expected


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("image/png", True),
        ("video/mp4", True),
        ("application/pdf", True),
        ("text/plain", False),
        ("application/json", False),
        ("application/zip", False),
        ("", False),
        (None, False),
    ],
)
def test_produces_image_thumbnail(mime, expected) -> None:
    assert produces_image_thumbnail(mime) is expected


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("image/png", PREVIEW_IMAGE_CONTENT_TYPE),
        ("application/pdf", PREVIEW_IMAGE_CONTENT_TYPE),
        ("video/mp4", PREVIEW_IMAGE_CONTENT_TYPE),
        ("text/plain", PREVIEW_TEXT_CONTENT_TYPE),
        ("application/json", PREVIEW_TEXT_CONTENT_TYPE),
    ],
)
def test_preview_content_type(mime, expected) -> None:
    assert preview_content_type(mime) == expected

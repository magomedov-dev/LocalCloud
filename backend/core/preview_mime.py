"""Классификация MIME-типов для генерации превью файлов.

Единый источник правды о том, для каких типов файлов формируется превью.
Используется и воркером генерации превью, и сервисами загрузки/копирования,
чтобы условие постановки задачи в очередь совпадало с тем, что умеет воркер.

Модуль не имеет внешних зависимостей и не знает о слоях storage/DB.
"""

from __future__ import annotations

from typing import Final

_IMAGE_PREFIX: Final = "image/"
_VIDEO_PREFIX: Final = "video/"
_TEXT_PREFIX: Final = "text/"
_PDF_TYPE: Final = "application/pdf"
_TEXT_TYPES: Final = ("application/json",)

# MIME-типы сгенерированных превью-объектов в хранилище. Изображения, PDF и
# видео рендерятся в один webp-кадр; текст/JSON сохраняются как усечённый
# фрагмент. Значения совпадают с тем, что записывает воркер превью.
PREVIEW_IMAGE_CONTENT_TYPE: Final = "image/webp"
PREVIEW_TEXT_CONTENT_TYPE: Final = "text/plain; charset=utf-8"


def _normalize(mime_type: str | None) -> str:
    """Приводит MIME-тип к нормализованному виду."""

    return (mime_type or "").strip().lower()


def is_image(mime_type: str | None) -> bool:
    """Возвращает ``True`` для изображений (``image/*``)."""

    return _normalize(mime_type).startswith(_IMAGE_PREFIX)


def is_video(mime_type: str | None) -> bool:
    """Возвращает ``True`` для видео (``video/*``)."""

    return _normalize(mime_type).startswith(_VIDEO_PREFIX)


def is_pdf(mime_type: str | None) -> bool:
    """Возвращает ``True`` для PDF-документов."""

    return _normalize(mime_type) == _PDF_TYPE


def is_text(mime_type: str | None) -> bool:
    """Возвращает ``True`` для текстовых типов (``text/*`` и JSON)."""

    normalized = _normalize(mime_type)
    return normalized.startswith(_TEXT_PREFIX) or normalized in _TEXT_TYPES


def preview_required(mime_type: str | None) -> bool:
    """Проверяет, формируется ли превью для указанного MIME-типа.

    Args:
        mime_type: MIME-тип файла.

    Returns:
        ``True``, если для типа поддерживается генерация превью
        (изображение, видео, PDF или текст), иначе ``False``.
    """

    return (
        is_image(mime_type)
        or is_video(mime_type)
        or is_pdf(mime_type)
        or is_text(mime_type)
    )


def produces_image_thumbnail(mime_type: str | None) -> bool:
    """Возвращает ``True``, если превью для типа — растровая миниатюра.

    Изображения, PDF и видео рендерятся воркером в webp-кадр, пригодный для
    показа в `<img>`. Текст/JSON дают текстовый фрагмент, не миниатюру.
    """

    return is_image(mime_type) or is_pdf(mime_type) or is_video(mime_type)


def preview_content_type(mime_type: str | None) -> str:
    """Возвращает MIME-тип превью-объекта для исходного типа файла.

    Args:
        mime_type: MIME-тип исходного файла.

    Returns:
        ``image/webp`` для изображений/PDF/видео, иначе ``text/plain``.
    """

    if produces_image_thumbnail(mime_type):
        return PREVIEW_IMAGE_CONTENT_TYPE
    return PREVIEW_TEXT_CONTENT_TYPE

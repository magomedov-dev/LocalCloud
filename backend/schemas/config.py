from __future__ import annotations

from pydantic import Field

from schemas.common import BaseSchema


class ClientFeatureFlags(BaseSchema):
    """Флаги функциональности, влияющие на поведение клиента.

    Отдаются фронтенду публичным endpoint-ом конфигурации, чтобы UI мог
    скрывать недоступные возможности на слабых или ограниченных
    развёртываниях (например, не показывать превью и просмотрщик файлов).
    Значения берутся из `core.config.FeatureSettings`.

    Attributes:
        previews_enabled: Показывать ли preview-миниатюры файлов.
        file_viewer_enabled: Доступен ли просмотр содержимого файлов.
        media_playback_enabled: Доступно ли проигрывание аудио/видео.
        file_editing_enabled: Доступно ли редактирование текстовых файлов.
    """

    previews_enabled: bool = Field(
        ...,
        description="Показывать ли preview-миниатюры файлов.",
    )
    file_viewer_enabled: bool = Field(
        ...,
        description="Доступен ли просмотр содержимого файлов.",
    )
    media_playback_enabled: bool = Field(
        ...,
        description="Доступно ли проигрывание аудио/видео.",
    )
    file_editing_enabled: bool = Field(
        ...,
        description="Доступно ли редактирование текстовых файлов.",
    )


class ClientConfigResponse(BaseSchema):
    """Публичная конфигурация клиента.

    Содержит набор флагов функциональности, на основе которых фронтенд
    адаптирует UI под конкретное развёртывание. Не содержит секретов и
    доступна без аутентификации.

    Attributes:
        features: Флаги функциональности приложения.
    """

    features: ClientFeatureFlags = Field(
        ...,
        description="Флаги функциональности приложения.",
    )

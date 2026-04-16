from fastapi import APIRouter, status

from core.config import get_settings
from schemas.config import ClientConfigResponse, ClientFeatureFlags

# Маршрутизатор публичной конфигурации клиента.
router = APIRouter(prefix="/config", tags=["config"])


@router.get(
    "",
    response_model=ClientConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def get_client_config() -> ClientConfigResponse:
    """Возвращает публичную конфигурацию клиента.

    Отдаёт фронтенду флаги функциональности развёртывания (превью, просмотр,
    проигрывание и редактирование файлов), на основе которых UI скрывает
    недоступные возможности. Конфигурация не содержит секретов и доступна
    без аутентификации, поэтому фронтенд может получить её ещё до входа.

    Returns:
        Публичная конфигурация клиента с флагами функциональности.
    """

    features = get_settings().features
    return ClientConfigResponse(
        features=ClientFeatureFlags(
            previews_enabled=features.previews_enabled,
            file_viewer_enabled=features.file_viewer_enabled,
            media_playback_enabled=features.media_playback_enabled,
            file_editing_enabled=features.file_editing_enabled,
        )
    )

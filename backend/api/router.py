from __future__ import annotations

from fastapi import APIRouter

from api.v1.audit import router as audit_router
from api.v1.auth import router as auth_router
from api.v1.downloads import router as downloads_router
from api.v1.folders import router as folders_router
from api.v1.health import router as health_router
from api.v1.nodes import router as nodes_router
from api.v1.permissions import router as permissions_router
from api.v1.public_links import router as public_links_router
from api.v1.quotas import router as quotas_router
from api.v1.registration import router as registration_router
from api.v1.tasks import router as tasks_router
from api.v1.trash import router as trash_router
from api.v1.uploads import router as uploads_router
from api.v1.users import router as users_router
from core.config import get_settings

settings = get_settings()

# Корневой маршрутизатор API приложения.
api_router = APIRouter()

# Маршрутизатор API v1 с префиксом из настроек приложения.
v1_router = APIRouter(prefix=settings.app.api_v1_prefix)

v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(registration_router)
v1_router.include_router(users_router)
v1_router.include_router(quotas_router)
v1_router.include_router(nodes_router)
v1_router.include_router(folders_router)
v1_router.include_router(uploads_router)
v1_router.include_router(downloads_router)
v1_router.include_router(trash_router)
v1_router.include_router(permissions_router)
v1_router.include_router(public_links_router)
v1_router.include_router(audit_router)
v1_router.include_router(tasks_router)

api_v1_prefix = settings.app.api_v1_prefix
api_prefix = settings.app.api_prefix
include_prefix = ""
if not api_v1_prefix.startswith(api_prefix.rstrip("/") + "/"):
    include_prefix = api_prefix

api_router.include_router(v1_router, prefix=include_prefix)

__all__ = ["api_router"]

from __future__ import annotations

from api.v1.audit import router as audit_router
from api.v1.auth import router as auth_router
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

__all__ = [
    "auth_router",
    "registration_router",
    "users_router",
    "nodes_router",
    "folders_router",
    "uploads_router",
    "trash_router",
    "permissions_router",
    "public_links_router",
    "quotas_router",
    "audit_router",
    "tasks_router",
    "health_router",
]

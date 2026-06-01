"""API 路由模块

将所有路由拆分为独立模块，通过 APIRouter 组织。
"""
from .tasks import router as tasks_router, runs_router
from .agents import router as agents_router
from .catalog import router as catalog_router
from .memory import router as memory_router
from .config import router as config_router
from .evolution import router as evolution_router
from .chat_sessions import router as chat_sessions_router
from .chatrooms import router as chatrooms_router
from .personas import router as personas_router
from .artifacts import router as artifacts_router
from .workspaces import router as workspaces_router
from .attachments import router as attachments_router

__all__ = [
    "tasks_router",
    "runs_router",
    "agents_router",
    "catalog_router",
    "memory_router",
    "config_router",
    "evolution_router",
    "chat_sessions_router",
    "chatrooms_router",
    "personas_router",
    "artifacts_router",
    "workspaces_router",
    "attachments_router",
]

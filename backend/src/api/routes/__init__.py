"""API 路由模块

将所有路由拆分为独立模块，通过 APIRouter 组织。
"""
from .tasks import router as tasks_router
from .agents import router as agents_router
from .workflows import router as workflows_router
from .memory import router as memory_router
from .config import router as config_router

__all__ = [
    "tasks_router",
    "agents_router",
    "workflows_router",
    "memory_router",
    "config_router",
]

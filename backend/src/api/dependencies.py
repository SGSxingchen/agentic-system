"""依赖注入模块

提供全局共享状态的 getter，供路由模块使用。
所有组件实例在 main.py 的 lifespan 中初始化，
通过此模块暴露给各路由。
"""
from typing import Callable, Coroutine, Optional


# ─── 全局状态容器 ─────────────────────────────────────────


class _AppState:
    """应用全局状态（模块级单例）"""

    def __init__(self):
        self.bus = None                    # UnifiedBus 实例
        self.agent_registry = None         # AgentRegistry 实例
        self.current_llm_client = None     # 当前 LLM 客户端
        self.memory_store = None           # 记忆存储
        self.memory_formation = None       # 记忆形成
        self.memory_retriever = None       # 记忆检索
        self.memory_buffer = None          # 对话反思缓冲
        self.reload_agent: Optional[Callable[[], Coroutine]] = None
        self.context_store = None          # ContextStore 实例
        self.capability_registry = None    # CapabilityRegistry 实例
        self.pipeline = None               # Pipeline 实例


_state = _AppState()


# ─── Setter（由 main.py 调用） ────────────────────────────

def set_bus(bus) -> None:
    _state.bus = bus


def set_agent_registry(registry) -> None:
    _state.agent_registry = registry


def set_llm_client(client) -> None:
    _state.current_llm_client = client


def set_memory_store(store) -> None:
    _state.memory_store = store


def set_memory_formation(formation) -> None:
    _state.memory_formation = formation


def set_memory_retriever(retriever) -> None:
    _state.memory_retriever = retriever


def set_memory_buffer(buffer) -> None:
    _state.memory_buffer = buffer


def set_reload_agent_fn(fn: Callable[[], Coroutine]) -> None:
    _state.reload_agent = fn


def set_context_store(store) -> None:
    _state.context_store = store


def set_capability_registry(registry) -> None:
    _state.capability_registry = registry


def set_pipeline(pipeline) -> None:
    _state.pipeline = pipeline


# ─── Getter（由路由调用） ─────────────────────────────────

def get_bus():
    return _state.bus


def get_agent_registry():
    return _state.agent_registry


def get_llm_client():
    return _state.current_llm_client


def get_memory_store():
    return _state.memory_store


def get_memory_formation():
    return _state.memory_formation


def get_memory_retriever():
    return _state.memory_retriever


def get_memory_buffer():
    return _state.memory_buffer


def reload_agent_fn() -> Optional[Callable[[], Coroutine]]:
    return _state.reload_agent


def get_context_store():
    return _state.context_store


def get_capability_registry():
    return _state.capability_registry


def get_pipeline():
    return _state.pipeline

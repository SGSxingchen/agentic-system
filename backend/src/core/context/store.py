"""上下文存储 - 分层上下文管理

实现三层上下文:
- project_context: 项目级，持久化到 JSON 文件
- session_context: 会话级，内存存储，会话结束即销毁
- agent_context: 智能体私有上下文，按 agent_id 隔离
"""
import asyncio
import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class ContextScope(str, Enum):
    """上下文作用域"""
    PROJECT = "project"
    SESSION = "session"
    AGENT = "agent"


class ContextStore:
    """分层上下文存储

    Usage::

        store = ContextStore(persist_dir="./data")
        await store.load_project_context()

        await store.set("repo_url", "https://...", ContextScope.PROJECT)
        url = await store.get("repo_url", ContextScope.PROJECT)

        await store.set("current_task", {...}, ContextScope.SESSION)

        await store.set("scratchpad", "...", ContextScope.AGENT, agent_id="coder")
    """

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        self._project: Dict[str, Any] = {}
        self._session: Dict[str, Any] = {}
        # agent_id -> {key: value}
        self._agent: Dict[str, Dict[str, Any]] = {}
        self._persist_path: Optional[Path] = None
        self._lock = asyncio.Lock()

        if persist_dir:
            self._persist_path = Path(persist_dir) / "project_context.json"

    # ─── 通用 CRUD ────────────────────────────────────────

    async def set(
        self,
        key: str,
        value: Any,
        scope: ContextScope = ContextScope.SESSION,
        agent_id: Optional[str] = None,
    ) -> None:
        """设置上下文值

        Args:
            key: 键名
            value: 值（需可 JSON 序列化，对 PROJECT 作用域而言）
            scope: 作用域
            agent_id: 当 scope=AGENT 时必须提供
        """
        store = self._resolve_store(scope, agent_id)
        async with self._lock:
            store[key] = value

    async def get(
        self,
        key: str,
        scope: ContextScope = ContextScope.SESSION,
        agent_id: Optional[str] = None,
        default: Any = None,
    ) -> Any:
        """获取上下文值

        按指定 scope 查找。找不到时返回 default。
        """
        store = self._resolve_store(scope, agent_id)
        return store.get(key, default)

    async def delete(
        self,
        key: str,
        scope: ContextScope = ContextScope.SESSION,
        agent_id: Optional[str] = None,
    ) -> bool:
        """删除上下文值，返回是否成功删除"""
        store = self._resolve_store(scope, agent_id)
        async with self._lock:
            if key in store:
                del store[key]
                return True
            return False

    async def get_all(
        self,
        scope: ContextScope = ContextScope.SESSION,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取某个作用域的所有上下文（返回副本）"""
        store = self._resolve_store(scope, agent_id)
        return dict(store)

    async def clear(
        self,
        scope: ContextScope = ContextScope.SESSION,
        agent_id: Optional[str] = None,
    ) -> None:
        """清空指定作用域的所有上下文"""
        async with self._lock:
            if scope == ContextScope.PROJECT:
                self._project.clear()
            elif scope == ContextScope.SESSION:
                self._session.clear()
            elif scope == ContextScope.AGENT:
                if agent_id:
                    self._agent.pop(agent_id, None)
                else:
                    # 无 agent_id 则清空所有 agent 上下文
                    self._agent.clear()

    # ─── 持久化（项目级）───────────────────────────────────

    async def save_project_context(self) -> None:
        """将项目级上下文持久化到 JSON 文件"""
        if self._persist_path is None:
            return
        async with self._lock:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self._project, ensure_ascii=False, indent=2)
            self._persist_path.write_text(data, encoding="utf-8")

    async def load_project_context(self) -> None:
        """从 JSON 文件加载项目级上下文"""
        if self._persist_path is None or not self._persist_path.exists():
            return
        async with self._lock:
            raw = self._persist_path.read_text(encoding="utf-8")
            self._project = json.loads(raw)

    # ─── 内部方法 ─────────────────────────────────────────

    def _resolve_store(
        self,
        scope: ContextScope,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """根据 scope 返回对应的存储字典"""
        if scope == ContextScope.PROJECT:
            return self._project
        elif scope == ContextScope.SESSION:
            return self._session
        elif scope == ContextScope.AGENT:
            if not agent_id:
                raise ValueError("agent_id is required for AGENT scope")
            if agent_id not in self._agent:
                self._agent[agent_id] = {}
            return self._agent[agent_id]
        else:
            raise ValueError(f"Unknown scope: {scope}")

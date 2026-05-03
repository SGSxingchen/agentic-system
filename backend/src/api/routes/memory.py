"""记忆系统路由

端点:
- GET    /api/memory/stats       — 获取记忆统计
- GET    /api/memory/list        — 列出记忆
- POST   /api/memory/search      — 搜索/召回测试
- POST   /api/memory/create      — 手动创建记忆
- PUT    /api/memory/{memory_id} — 更新记忆
- DELETE /api/memory/{memory_id} — 删除记忆
- GET    /api/memory/settings    — 获取记忆系统设置和运行状态
- POST   /api/memory/settings    — 保存记忆系统设置
- POST   /api/memory/consolidate — 触发记忆巩固
- POST   /api/memory/forget      — 触发记忆遗忘
"""
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
import yaml

from ..schemas import (
    APIResponse,
    MemoryCreateRequest,
    MemorySearchRequest,
    MemorySettingsUpdateRequest,
    MemoryUpdateRequest,
)
from ..dependencies import (
    get_memory_buffer,
    get_memory_store,
    get_memory_formation,
    get_memory_retriever,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])

MEMORY_DEFAULTS: Dict[str, Any] = {
    "backend": "chroma",
    "persist_dir": "./data/chroma",
    "collection_name": "agent_memories",
    "auto_reflection_enabled": True,
    "reflection_min_turns": 3,
    "reflection_max_messages": 12,
    "recall_max_results": 3,
    "recall_max_chars": 1200,
    "recall_score_threshold": 0.0,
    "fallback_to_memory_on_error": True,
    "consolidation_threshold": 0.3,
    "forget_after_days": 30,
    "forget_min_importance": 0.3,
}


def _runtime_config_path() -> Path:
    return Path(__file__).parent.parent.parent / "config.yaml"


def _load_runtime_config() -> Dict[str, Any]:
    path = _runtime_config_path()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_runtime_config(config: Dict[str, Any]) -> None:
    _runtime_config_path().write_text(
        yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _memory_config() -> Dict[str, Any]:
    from core.config import load_config

    config = load_config()
    memory = config.get("memory", {}) if isinstance(config.get("memory"), dict) else {}
    return {**MEMORY_DEFAULTS, **memory}


def _settings_response(*, note: str = "") -> Dict[str, Any]:
    settings = _memory_config()
    store = get_memory_store()
    buffer = get_memory_buffer()
    formation = get_memory_formation()

    if buffer:
        settings["reflection_min_turns"] = getattr(buffer, "min_turns", settings["reflection_min_turns"])
        settings["reflection_max_messages"] = getattr(
            buffer,
            "max_window_messages",
            settings["reflection_max_messages"],
        )

    if formation:
        settings["consolidation_threshold"] = getattr(
            formation,
            "consolidation_threshold",
            settings["consolidation_threshold"],
        )
        settings["forget_after_days"] = getattr(
            formation,
            "forget_after_days",
            settings["forget_after_days"],
        )
        settings["forget_min_importance"] = getattr(
            formation,
            "forget_min_importance",
            settings["forget_min_importance"],
        )

    settings["status"] = {
        "initialized": store is not None,
        "runtime_store": type(store).__name__ if store else "",
        "note": note,
    }
    return settings


def _apply_runtime_settings(settings: Dict[str, Any]) -> None:
    buffer = get_memory_buffer()
    if buffer:
        buffer.min_turns = max(1, int(settings.get("reflection_min_turns", 3)))
        buffer.max_window_messages = max(2, int(settings.get("reflection_max_messages", 12)))

    formation = get_memory_formation()
    if formation:
        formation.consolidation_threshold = float(settings.get("consolidation_threshold", 0.3))
        formation.forget_after_days = int(settings.get("forget_after_days", 30))
        formation.forget_min_importance = float(settings.get("forget_min_importance", 0.3))


@router.get("/stats", response_model=APIResponse)
async def memory_stats():
    """获取记忆系统统计"""
    formation = get_memory_formation()
    if not formation:
        return APIResponse(status="error", message="记忆系统未初始化")

    stats = await formation.get_stats()
    return APIResponse(status="ok", data=stats)


@router.get("/list", response_model=APIResponse)
async def memory_list(type: str = "", limit: int = 20):
    """列出记忆"""
    store = get_memory_store()
    if not store:
        return APIResponse(status="error", message="记忆系统未初始化")

    from core.memory import MemoryType

    memory_type = None
    if type:
        try:
            memory_type = MemoryType(type)
        except ValueError:
            return APIResponse(status="error", message=f"无效的记忆类型: {type}")

    memories = await store.get_all(memory_type=memory_type, limit=limit)
    return APIResponse(
        status="ok",
        data=[m.to_dict() for m in memories],
    )


@router.post("/search", response_model=APIResponse)
async def memory_search(body: MemorySearchRequest):
    """搜索记忆"""
    retriever = get_memory_retriever()
    if not retriever:
        return APIResponse(status="error", message="记忆系统未初始化")

    results = await retriever.retrieve_with_scores(
        context=body.query,
        max_results=body.max_results,
    )
    return APIResponse(
        status="ok",
        data=[
            {
                **item["memory"].to_dict(),
                "retrieval": item["retrieval"],
            }
            for item in results
        ],
    )


@router.post("/create", response_model=APIResponse)
async def memory_create(body: MemoryCreateRequest):
    """手动创建记忆"""
    formation = get_memory_formation()
    if not formation:
        return APIResponse(status="error", message="记忆系统未初始化")

    from core.memory import MemoryType

    try:
        memory_type = MemoryType(body.type)
    except ValueError:
        return APIResponse(status="error", message=f"无效的记忆类型: {body.type}")

    memory = await formation.create_memory(
        content=body.content,
        memory_type=memory_type,
        importance=body.importance,
        metadata=body.metadata,
    )
    return APIResponse(status="ok", data=memory.to_dict())


@router.get("/settings", response_model=APIResponse)
async def memory_settings():
    """获取记忆系统设置和运行状态。"""
    return APIResponse(status="ok", data=_settings_response())


@router.post("/settings", response_model=APIResponse)
async def memory_settings_update(body: MemorySettingsUpdateRequest):
    """保存记忆系统设置。

    反思阈值、巩固/遗忘阈值会同步到当前进程；存储后端和持久化路径写入
    运行时配置，通常需要重启后才会完全切换。
    """
    payload = body.model_dump(exclude_none=True)
    if "backend" in payload and payload["backend"] not in {"memory", "chroma"}:
        return APIResponse(status="error", message="backend 仅支持 memory 或 chroma")

    existing = _load_runtime_config()
    current_memory = existing.get("memory", {}) if isinstance(existing.get("memory"), dict) else {}
    before = _memory_config()
    merged_memory = {**current_memory, **payload}
    existing["memory"] = merged_memory
    _write_runtime_config(existing)

    after = {**before, **payload}
    _apply_runtime_settings(after)

    restart_keys = {"backend", "persist_dir", "collection_name", "fallback_to_memory_on_error"}
    changed_restart_keys = [key for key in restart_keys if key in payload and payload[key] != before.get(key)]
    note = ""
    message = "记忆设置已保存"
    if changed_restart_keys:
        note = "后端/持久化相关设置已保存，需重启服务后完全生效"
        message = note

    return APIResponse(status="ok", message=message, data=_settings_response(note=note))


@router.put("/{memory_id}", response_model=APIResponse)
async def memory_update(memory_id: str, body: MemoryUpdateRequest):
    """更新记忆"""
    store = get_memory_store()
    if not store:
        return APIResponse(status="error", message="记忆系统未初始化")

    memory = await store.get(memory_id)
    if not memory:
        return APIResponse(status="error", message="记忆不存在")

    from core.memory import MemoryType

    if body.type is not None:
        try:
            memory.type = MemoryType(body.type)
        except ValueError:
            return APIResponse(status="error", message=f"无效的记忆类型: {body.type}")
    if body.content is not None:
        memory.content = body.content
    if body.importance is not None:
        memory.importance = body.importance
    if body.metadata is not None:
        memory.metadata = body.metadata

    success = await store.update(memory)
    if success:
        return APIResponse(status="ok", data=memory.to_dict())
    return APIResponse(status="error", message="记忆更新失败")


@router.delete("/{memory_id}", response_model=APIResponse)
async def memory_delete(memory_id: str):
    """删除记忆"""
    store = get_memory_store()
    if not store:
        return APIResponse(status="error", message="记忆系统未初始化")

    success = await store.delete(memory_id)
    if success:
        return APIResponse(status="ok")
    return APIResponse(status="error", message="记忆不存在")


@router.post("/consolidate", response_model=APIResponse)
async def memory_consolidate():
    """触发记忆巩固"""
    formation = get_memory_formation()
    if not formation:
        return APIResponse(status="error", message="记忆系统未初始化")

    stats = await formation.consolidate()
    return APIResponse(status="ok", data=stats)


@router.post("/forget", response_model=APIResponse)
async def memory_forget():
    """触发记忆遗忘"""
    formation = get_memory_formation()
    if not formation:
        return APIResponse(status="error", message="记忆系统未初始化")

    forgotten = await formation.forget()
    return APIResponse(status="ok", data={"forgotten": forgotten})

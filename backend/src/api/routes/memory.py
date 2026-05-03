"""记忆系统路由

从原 main.py 迁移，保持功能完全兼容。

端点:
- GET    /api/memory/stats       — 获取记忆统计
- GET    /api/memory/list        — 列出记忆
- POST   /api/memory/search      — 搜索记忆
- POST   /api/memory/create      — 手动创建记忆
- DELETE /api/memory/{memory_id} — 删除记忆
- POST   /api/memory/consolidate — 触发记忆巩固
- POST   /api/memory/forget      — 触发记忆遗忘
"""
from fastapi import APIRouter

from ..schemas import APIResponse, MemoryCreateRequest, MemorySearchRequest
from ..dependencies import get_memory_store, get_memory_formation, get_memory_retriever

router = APIRouter(prefix="/api/memory", tags=["memory"])


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

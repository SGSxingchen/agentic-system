"""配置与健康检查路由

端点:
- GET  /api/config   — 获取配置（隐藏 api_key）
- POST /api/config   — 更新配置并热重载
- GET  /api/health   — 健康检查
"""
from pathlib import Path

from fastapi import APIRouter

from ..schemas import APIResponse, ConfigUpdateRequest
from ..dependencies import (
    get_bus,
    get_agent_registry,
    get_memory_store,
    get_capability_registry,
    reload_agent_fn,
)

router = APIRouter(tags=["config"])


@router.get("/api/config", response_model=APIResponse)
async def get_config():
    """获取配置（不暴露 api_key）"""
    from core.config import load_config

    config = load_config()
    return APIResponse(
        status="ok",
        data={
            "llm": {
                "provider": config["llm"]["provider"],
                "model": config["llm"]["model"],
                "api_key_set": bool(config["llm"]["api_key"]),
                "base_url": config["llm"].get("base_url", ""),
            }
        },
    )


@router.post("/api/config", response_model=APIResponse)
async def update_config(config_data: ConfigUpdateRequest):
    """更新配置并热重载"""
    import yaml

    try:
        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        config_dict = {
            "llm": config_data.llm.model_dump(),
        }
        config_path.write_text(yaml.dump(config_dict))
        print(f"[OK] 配置已保存到: {config_path}")

        # 热重载 Agent
        reload = reload_agent_fn()
        if reload:
            await reload()

        return APIResponse(status="ok", message="配置已更新并重新加载")
    except Exception as e:
        print(f"[ERROR] 配置更新失败: {e}")
        import traceback

        traceback.print_exc()
        return APIResponse(status="error", message=str(e))


@router.get("/api/health", response_model=APIResponse)
async def health():
    """健康检查"""
    bus = get_bus()
    cap_registry = get_capability_registry()
    memory_store = get_memory_store()
    registry = get_agent_registry()

    return APIResponse(
        status="ok",
        data={
            "bus_running": bus._running if bus else False,
            "agent_loaded": cap_registry is not None and "assistant" in cap_registry,
            "memory_initialized": memory_store is not None,
            "agents_registered": len(registry) if registry else 0,
        },
    )

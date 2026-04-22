"""FastAPI 应用入口 — 重构版

架构:
- Pipeline 统一编排所有任务
- Agent 全配置化（agents.yaml），内置 tool_use 循环
- 能力插件自动发现（capabilities/ 目录扫描）
- Bus 仅用于前端状态通知
"""
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# 修复导入路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.bus import UnifiedBus
from core.llm import create_llm_client
from core.config import load_config, load_yaml_configs
from core.memory import (
    MemoryFormation,
    MemoryRetriever,
    create_memory_store,
)
from core.agent import Agent, AgentRegistry
from core.capability import CapabilityRegistry
from core.capability.agent_adapter import AgentCapability
from core.context import ContextStore
from core.pipeline import Pipeline

# 依赖注入 setter / getter
from .dependencies import (
    set_bus,
    set_agent_registry,
    set_llm_client,
    set_memory_store,
    set_memory_formation,
    set_memory_retriever,
    set_reload_agent_fn,
    set_context_store,
    set_capability_registry,
    set_pipeline,
    get_capability_registry,
)

# 路由
from .routes import (
    tasks_router,
    agents_router,
    workflows_router,
    memory_router,
    config_router,
)

# WebSocket
from .websocket.handlers import websocket_endpoint as ws_handler


# ─── 全局实例 ─────────────────────────────────────────────

bus = UnifiedBus()
registry = AgentRegistry()

# 缓存已加载的 config/ 配置
_yaml_configs: Dict[str, Any] = {}


# ─── 配置加载辅助 ─────────────────────────────────────────


def _load_external_configs() -> Dict[str, Any]:
    """加载 config/ 目录下的 YAML 配置，缓存结果"""
    global _yaml_configs
    if not _yaml_configs:
        _yaml_configs = load_yaml_configs()
    return _yaml_configs


def clear_yaml_cache() -> None:
    """清除 YAML 配置缓存"""
    global _yaml_configs
    _yaml_configs = {}


# ─── 初始化函数 ───────────────────────────────────────────


async def init_memory_system():
    """初始化记忆系统"""
    config = load_config()
    memory_config = config.get("memory", {})
    backend = memory_config.get("backend", "memory")

    store_kwargs = {}
    if backend == "chroma":
        store_kwargs["persist_dir"] = memory_config.get("persist_dir", "./data/chroma")
        store_kwargs["collection_name"] = memory_config.get("collection_name", "agent_memories")

    memory_store = create_memory_store(backend, **store_kwargs)
    memory_formation = MemoryFormation(store=memory_store)
    memory_retriever = MemoryRetriever(store=memory_store)

    set_memory_store(memory_store)
    set_memory_formation(memory_formation)
    set_memory_retriever(memory_retriever)

    print(f"[OK] 记忆系统已初始化 (backend={backend})")
    return memory_store, memory_formation, memory_retriever


def _discover_capabilities(cap_registry: CapabilityRegistry) -> None:
    """自动发现并注册所有能力插件"""
    src_dir = Path(__file__).parent.parent  # backend/src/
    capabilities_dir = src_dir / "capabilities"

    if capabilities_dir.is_dir():
        count = cap_registry.discover_plugins([str(capabilities_dir)])
        print(f"[OK] 能力插件自动发现: {count} 个能力已注册")
    else:
        print(f"[WARN] 能力插件目录不存在: {capabilities_dir}")


def _create_agents_from_config(
    agents_config: List[Dict[str, Any]],
    llm_client: Any,
    cap_registry: CapabilityRegistry,
) -> List[Agent]:
    """从 agents.yaml 配置创建 Agent 实例（两阶段加载）

    阶段 1: 创建所有 Agent（只绑定非 Agent 工具），注册为 Capability
    阶段 2: 回填 Agent 互调工具（此时所有 Agent 已在 registry 中）
    """
    agent_names = {d["name"] for d in agents_config}
    agents = []
    deferred_tools: List[tuple] = []  # (agent, [tool_name, ...])

    # ── 阶段 1: 创建 Agent，只绑定普通工具 ──
    for agent_def in agents_config:
        name = agent_def["name"]
        tool_names = agent_def.get("tools", [])

        tools = []
        agent_tool_names = []
        for tool_name in tool_names:
            if tool_name in agent_names:
                # 其他 Agent 还没注册，先记下来
                agent_tool_names.append(tool_name)
            else:
                cap = cap_registry.get(tool_name)
                if cap:
                    tools.append(cap)
                else:
                    print(f"[WARN] Agent '{name}' 引用的工具 '{tool_name}' 未找到，跳过")

        agent = Agent(
            name=name,
            llm_client=llm_client,
            system_prompt=agent_def.get("system_prompt", ""),
            tools=tools,
            output_format=agent_def.get("output_format", "text"),
            max_iterations=agent_def.get("max_iterations", 10),
            description=agent_def.get("description", ""),
        )
        agents.append(agent)

        # 注册为 Capability（带 input_schema）
        input_schema = agent_def.get("input_schema")
        cap_registry.register_native(AgentCapability(agent, input_schema))

        if agent_tool_names:
            deferred_tools.append((agent, agent_tool_names))

    # ── 阶段 2: 回填 Agent 互调工具 ──
    for agent, tool_names in deferred_tools:
        for tool_name in tool_names:
            cap = cap_registry.get(tool_name)
            if cap:
                agent._tools.append(cap)
            else:
                print(f"[WARN] Agent '{agent.name}' 引用的 Agent 工具 '{tool_name}' 未找到")

    for agent in agents:
        print(f"  [+] Agent '{agent.name}' (tools: {[t.name for t in agent._tools]})")

    return agents


async def reload_agents():
    """重新加载所有 Agent（热重载）"""
    try:
        config = load_config()
        print(f"[INFO] 加载配置: {config['llm']['provider']} - {config['llm']['model']}")

        # 重新创建 LLM 客户端
        llm_client = create_llm_client(
            provider=config["llm"]["provider"],
            api_key=config["llm"]["api_key"],
            model=config["llm"]["model"],
            base_url=config["llm"].get("base_url") or None,
        )
        set_llm_client(llm_client)

        # 获取能力注册表
        from .dependencies import get_capability_registry
        cap_registry = get_capability_registry()

        # 先注销旧的 Agent 能力
        for meta in registry.list_all():
            cap_registry.unregister(meta.name)
        # 清空 Agent 注册表
        for meta in registry.list_all():
            registry.unregister(meta.name)

        # 从 config/agents.yaml 加载
        ext_configs = _load_external_configs()
        agents_config = ext_configs.get("agents", [])

        if not agents_config:
            # Fallback: 硬编码默认 Agent
            print("[WARN] config/agents.yaml 未找到或为空，使用默认配置")
            agents_config = [
                {"name": "assistant", "description": "对话助手", "system_prompt": "你是一个友好的AI助手。", "tools": [], "output_format": "text"},
                {"name": "planner", "description": "任务规划", "system_prompt": "你是一个任务规划智能体。", "tools": [], "output_format": "json"},
                {"name": "coder", "description": "代码生成", "system_prompt": "你是一位资深软件工程师。", "tools": [], "output_format": "json"},
                {"name": "reviewer", "description": "代码审查", "system_prompt": "你是一位代码审查专家。", "tools": [], "output_format": "json"},
            ]

        print(f"[INFO] 从配置加载 {len(agents_config)} 个 Agent:")
        agents = _create_agents_from_config(agents_config, llm_client, cap_registry)

        for agent in agents:
            # 注册到 AgentRegistry（元数据查询用，AgentCapability 已在 _create 内注册）
            registry.register(agent)

        # 启动所有 Agent
        await registry.start_all()

        print(
            f"[OK] 所有 Agent 已加载 "
            f"({config['llm']['provider']} - {config['llm']['model']}, "
            f"{len(registry)} 个 Agent)"
        )
    except Exception as e:
        print(f"[ERROR] Agent 加载失败: {e}")
        import traceback
        traceback.print_exc()
        raise


# ─── 应用生命周期 ─────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 注入总线
    set_bus(bus)
    set_agent_registry(registry)
    set_reload_agent_fn(reload_agents)

    # 启动总线（仅用于前端通知）
    await bus.start()

    # 初始化上下文存储
    context_store = ContextStore()
    set_context_store(context_store)
    print("[OK] 上下文存储已初始化")

    # 初始化能力系统（目录扫描自动发现）
    cap_registry = CapabilityRegistry()
    _discover_capabilities(cap_registry)
    set_capability_registry(cap_registry)

    # 初始化记忆系统
    await init_memory_system()

    # 初始化所有 Agent（从 config/agents.yaml）
    await reload_agents()

    # 初始化 Pipeline
    ext_configs = _load_external_configs()
    pipeline = Pipeline(cap_registry, bus)

    # 加载管线模板（从 config/pipelines.yaml 或 config/workflows.yaml）
    pipelines_config = ext_configs.get("pipelines") or ext_configs.get("workflows")
    if pipelines_config and isinstance(pipelines_config, dict):
        pipeline.load_templates(pipelines_config)
        print(f"[OK] Pipeline 已初始化 (已加载 {len(pipelines_config)} 个模板)")
    else:
        print("[OK] Pipeline 已初始化")
    set_pipeline(pipeline)

    print("[OK] 系统全部初始化完成!")

    yield

    # 关闭
    print("[INFO] 正在关闭系统...")
    await registry.stop_all()
    await bus.stop()
    print("[OK] 系统已安全关闭")


# ─── 创建 FastAPI 应用 ────────────────────────────────────


app = FastAPI(
    title="Multi-Agent Code System",
    description="多智能体协作代码生成与审查系统 API",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(workflows_router)
app.include_router(memory_router)
app.include_router(config_router)


# ─── Chat REST 端点（前端 ChatPanel fallback）─────────────


@app.post("/api/chat")
async def chat_endpoint(req: dict):
    """REST 聊天端点 — 调用 assistant Agent"""
    message = req.get("message", "")
    if not message:
        return {"status": "error", "message": "message is required"}

    cap_registry = get_capability_registry()
    if not cap_registry or "assistant" not in cap_registry:
        return {"status": "error", "message": "Assistant 未初始化"}

    try:
        result = await cap_registry.execute("assistant", message=message)
        response_text = result.get("response", str(result))
        return {"status": "ok", "response": response_text}
    except Exception as e:
        return {"status": "error", "message": f"处理失败: {str(e)}"}


@app.post("/api/chat/stream")
async def chat_stream_endpoint(req: dict):
    """SSE 流式聊天端点 — 逐步返回 Agent 事件"""
    import json as _json

    message = req.get("message", "")
    if not message:
        return {"status": "error", "message": "message is required"}

    cap_registry = get_capability_registry()
    if not cap_registry or "assistant" not in cap_registry:
        return {"status": "error", "message": "Assistant 未初始化"}

    cap = cap_registry.get("assistant")

    async def event_generator():
        try:
            if hasattr(cap, "execute_stream"):
                async for event in cap.execute_stream(message=message):
                    yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
            else:
                # fallback: 非流式
                result = await cap_registry.execute("assistant", message=message)
                response_text = result.get("response", str(result))
                yield f"data: {_json.dumps({'type': 'thinking', 'content': response_text}, ensure_ascii=False)}\n\n"
                yield f"data: {_json.dumps({'type': 'done', 'content': result}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'done', 'content': {'error': str(e)}}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# WebSocket 端点
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    """WebSocket 连接端点"""
    await ws_handler(websocket)


# ─── 入口 ────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)

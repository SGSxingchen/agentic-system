"""FastAPI application entrypoint for the multi-agent system."""

from __future__ import annotations

import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import Agent, AgentRegistry
from core.capability import (
    CapabilityRegistry,
    apply_prompt_overrides,
    load_dynamic_capabilities,
)
from core.capability.agent_adapter import AgentCapability
from core.bus import UnifiedBus
from core.config import load_config, load_yaml_configs
from core.context import ContextStore
from core.llm import create_llm_client
from core.mcp import format_mcp_servers_for_prompt, normalize_agent_mcp_servers
from core.skills import format_skills_for_prompt, load_agent_skills
from core.memory import (
    ConversationMemoryBuffer,
    MemoryFormation,
    MemoryRetriever,
    create_memory_store,
)
from core.pipeline import Pipeline

from .dependencies import (
    get_capability_registry,
    set_agent_registry,
    set_bus,
    set_capability_registry,
    set_context_store,
    set_llm_client,
    set_memory_buffer,
    set_memory_formation,
    set_memory_retriever,
    set_memory_store,
    set_pipeline,
    set_reload_agent_fn,
)
from .routes import (
    agents_router,
    chat_sessions_router,
    config_router,
    evolution_router,
    memory_router,
    personas_router,
    pipelines_router,
    tasks_router,
)
from .websocket.handlers import (
    build_memory_context,
    broadcast_monitor_event,
    register_bus_event_bridge,
    schedule_memory_reflection,
    websocket_endpoint as ws_handler,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

bus: Optional[UnifiedBus] = None
registry = AgentRegistry()
_yaml_configs: Dict[str, Any] = {}


def _resolve_project_path(raw_path: str, default: str) -> str:
    path = Path(raw_path or default)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return str(path)


def _load_external_configs() -> Dict[str, Any]:
    global _yaml_configs
    if not _yaml_configs:
        _yaml_configs = load_yaml_configs()
    return _yaml_configs


def clear_yaml_cache() -> None:
    global _yaml_configs
    _yaml_configs = {}


def _attach_stream_memory_usage(
    event: dict[str, Any],
    *,
    memories_used: int,
) -> dict[str, Any]:
    """Attach memory usage to stream events without mutating the original."""

    enriched = dict(event)
    enriched["memories_used"] = memories_used
    if enriched.get("type") == "done" and isinstance(enriched.get("content"), dict):
        content = dict(enriched["content"])
        content.setdefault("memories_used", memories_used)
        enriched["content"] = content
    return enriched


async def init_memory_system(config: Dict[str, Any]):
    """Initialize the configured memory backend."""

    memory_config = config.get("memory", {})
    backend = memory_config.get("backend", "chroma")
    store_kwargs: Dict[str, Any] = {}

    if backend == "chroma":
        store_kwargs["persist_dir"] = _resolve_project_path(
            memory_config.get("persist_dir", "./data/chroma"),
            "./data/chroma",
        )
        store_kwargs["collection_name"] = memory_config.get(
            "collection_name",
            "agent_memories",
        )

    try:
        memory_store = create_memory_store(backend, **store_kwargs)
    except Exception as exc:
        fallback_enabled = bool(memory_config.get("fallback_to_memory_on_error", True))
        detail = (
            f"[WARN] memory backend '{backend}' failed to initialize: {exc}"
        )
        if backend == "chroma":
            detail += (
                "\n[WARN] Chroma 持久化未启用。请安装依赖 `pip install chromadb` "
                "或设置 MEMORY_BACKEND=memory 显式使用内存后端。"
            )
        if not fallback_enabled:
            print(detail)
            raise
        print(detail)
        print("[WARN] falling back to in-memory memory store; data will not persist")
        backend = "memory"
        store_kwargs = {}
        memory_store = create_memory_store("memory")
    memory_formation = MemoryFormation(
        store=memory_store,
        consolidation_threshold=float(memory_config.get("consolidation_threshold", 0.3)),
        forget_after_days=int(memory_config.get("forget_after_days", 30)),
        forget_min_importance=float(memory_config.get("forget_min_importance", 0.3)),
    )
    memory_retriever = MemoryRetriever(store=memory_store)
    memory_buffer = ConversationMemoryBuffer(
        min_turns=int(memory_config.get("reflection_min_turns", 3)),
        max_window_messages=int(memory_config.get("reflection_max_messages", 12)),
    )

    set_memory_store(memory_store)
    set_memory_formation(memory_formation)
    set_memory_retriever(memory_retriever)
    set_memory_buffer(memory_buffer)

    print(
        "[OK] memory initialized "
        f"(backend={backend}, persist_dir={store_kwargs.get('persist_dir', '-')}, "
        f"reflection_min_turns={memory_buffer.min_turns})"
    )
    return memory_store, memory_formation, memory_retriever


def _discover_capabilities(cap_registry: CapabilityRegistry) -> None:
    """Auto-discover capabilities from the local capabilities package."""

    capabilities_dir = Path(__file__).parent.parent / "capabilities"
    if capabilities_dir.is_dir():
        count = cap_registry.discover_plugins([str(capabilities_dir)])
        print(f"[OK] discovered {count} capabilities")
    else:
        print(f"[WARN] capabilities directory missing: {capabilities_dir}")


def _register_dynamic_capabilities(cap_registry: CapabilityRegistry) -> None:
    """Register YAML-defined dynamic tools."""

    ext_configs = _load_external_configs()
    capability_defs = ext_configs.get("capabilities", [])
    loaded = load_dynamic_capabilities(cap_registry, capability_defs)
    if loaded:
        print(f"[OK] loaded dynamic tools: {', '.join(loaded)}")


def _apply_capability_prompt_overrides(cap_registry: CapabilityRegistry) -> None:
    """Apply YAML-defined LLM-facing tool prompts."""

    ext_configs = _load_external_configs()
    capability_defs = ext_configs.get("capabilities", [])
    applied = apply_prompt_overrides(cap_registry, capability_defs)
    if applied:
        print(f"[OK] applied tool prompt overrides: {', '.join(applied)}")


def _create_agents_from_config(
    agents_config: List[Dict[str, Any]],
    llm_client: Any,
    cap_registry: CapabilityRegistry,
) -> List[Agent]:
    """Create configured agents and register agent-to-agent capability adapters."""

    agent_names = {item["name"] for item in agents_config}
    agents: List[Agent] = []
    deferred_tools: List[tuple[Agent, List[str]]] = []

    for agent_def in agents_config:
        name = agent_def["name"]
        tool_names = agent_def.get("tools", [])

        tools = []
        agent_tool_names: List[str] = []
        for tool_name in tool_names:
            if tool_name in agent_names:
                agent_tool_names.append(tool_name)
                continue

            capability = cap_registry.get(tool_name)
            if capability:
                tools.append(capability)
            else:
                print(f"[WARN] agent '{name}' references missing tool '{tool_name}'")

        loaded_skills = load_agent_skills(agent_def, project_root=PROJECT_ROOT)
        mcp_servers = normalize_agent_mcp_servers(agent_def)
        runtime_blocks = [
            block
            for block in (
                format_skills_for_prompt(loaded_skills),
                format_mcp_servers_for_prompt(mcp_servers),
            )
            if block
        ]
        system_prompt = agent_def.get("system_prompt", "")
        if runtime_blocks:
            system_prompt = system_prompt.rstrip() + "\n\n" + "\n\n".join(runtime_blocks)

        if loaded_skills:
            print(f"  [skills] agent '{name}' loaded {len(loaded_skills)} skill(s): {', '.join(skill.name for skill in loaded_skills)}")
        if mcp_servers:
            print(f"  [mcp] agent '{name}' configured {len(mcp_servers)} MCP server(s): {', '.join(server.name for server in mcp_servers)} (adapter not auto-started)")

        agent = Agent(
            name=name,
            llm_client=llm_client,
            system_prompt=system_prompt,
            tools=tools,
            output_format=agent_def.get("output_format", "text"),
            max_iterations=agent_def.get("max_iterations", 10),
            description=agent_def.get("description", ""),
            token_budget=agent_def.get("token_budget"),
            token_budget_nudge_threshold=agent_def.get(
                "token_budget_nudge_threshold", 0.85
            ),
            runtime_config={
                "skills": [skill.__dict__ for skill in loaded_skills],
                "mcp_servers": [server.__dict__ for server in mcp_servers],
                "mcp_capability_status": "configured_not_connected" if mcp_servers else "not_configured",
            },
        )
        agents.append(agent)

        cap_registry.register_native(
            AgentCapability(agent, agent_def.get("input_schema"))
        )

        if agent_tool_names:
            deferred_tools.append((agent, agent_tool_names))

    for agent, tool_names in deferred_tools:
        for tool_name in tool_names:
            capability = cap_registry.get(tool_name)
            if capability:
                agent._tools.append(capability)
            else:
                print(
                    f"[WARN] agent '{agent.name}' references missing agent tool '{tool_name}'"
                )

    for agent in agents:
        print(f"  [+] agent '{agent.name}' tools={[tool.name for tool in agent._tools]}")

    return agents


async def reload_agents() -> None:
    """Reload all configured agents from merged config sources."""

    try:
        clear_yaml_cache()
        config = load_config()
        llm_config = config.get("llm", {})

        llm_client = create_llm_client(
            provider=llm_config.get("provider", "openai"),
            api_key=llm_config.get("api_key", ""),
            model=llm_config.get("model", "gpt-3.5-turbo"),
            base_url=llm_config.get("base_url") or None,
            generation_config=llm_config,
        )
        set_llm_client(llm_client)

        cap_registry = get_capability_registry()
        if cap_registry is None:
            raise RuntimeError("Capability registry is not initialized")

        for metadata in registry.list_all():
            cap_registry.unregister(metadata.name)
        for metadata in registry.list_all():
            registry.unregister(metadata.name)

        ext_configs = _load_external_configs()
        agents_config = ext_configs.get("agents", [])
        if not agents_config:
            raise RuntimeError("config/agents.yaml is missing or empty")

        print(f"[INFO] loading {len(agents_config)} configured agents")
        agents = _create_agents_from_config(agents_config, llm_client, cap_registry)

        for agent in agents:
            registry.register(agent)

        await registry.start_all()
        print(
            "[OK] agents loaded "
            f"({llm_config.get('provider')} - {llm_config.get('model')}, {len(registry)} agents)"
        )
    except Exception as exc:
        print(f"[ERROR] failed to reload agents: {exc}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application dependencies and background infrastructure."""

    global bus

    config = load_config()
    bus_config = config.get("bus", {})
    context_config = config.get("context", {})

    bus = UnifiedBus(
        queue_size=int(bus_config.get("queue_size", 1000)),
        history_size=int(bus_config.get("history_size", 500)),
    )

    set_bus(bus)
    set_agent_registry(registry)
    set_reload_agent_fn(reload_agents)

    await bus.start()
    register_bus_event_bridge(bus)

    context_store = ContextStore(
        persist_dir=_resolve_project_path(
            context_config.get("persist_dir", "./data/context"),
            "./data/context",
        )
    )
    await context_store.load_project_context()
    set_context_store(context_store)
    print("[OK] context store initialized")

    cap_registry = CapabilityRegistry()
    _discover_capabilities(cap_registry)
    _register_dynamic_capabilities(cap_registry)
    _apply_capability_prompt_overrides(cap_registry)
    set_capability_registry(cap_registry)

    await init_memory_system(config)
    await reload_agents()

    pipeline = Pipeline(cap_registry, bus)
    ext_configs = _load_external_configs()
    pipeline_templates = ext_configs.get("pipelines")
    if isinstance(pipeline_templates, dict):
        pipeline.load_templates(pipeline_templates)
        print(f"[OK] pipeline initialized with {len(pipeline_templates)} templates")
    else:
        print("[OK] pipeline initialized without templates")
    set_pipeline(pipeline)

    print("[OK] system initialization completed")

    try:
        yield
    finally:
        print("[INFO] shutting down system...")
        await context_store.save_project_context()
        await registry.stop_all()
        await bus.stop()
        print("[OK] shutdown completed")


APP_CONFIG = load_config()
SERVER_CONFIG = APP_CONFIG.get("server", {})
CORS_ORIGINS = SERVER_CONFIG.get(
    "cors_origins",
    ["http://localhost:3000", "http://localhost:3001"],
)

app = FastAPI(
    title="Multi-Agent Code System",
    description="Multi-agent code generation and review system API",
    version=APP_CONFIG.get("system", {}).get("version", "0.3.0"),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(agents_router)
app.include_router(pipelines_router)
app.include_router(memory_router)
app.include_router(personas_router)
app.include_router(config_router)
app.include_router(evolution_router)
app.include_router(chat_sessions_router)


@app.post("/api/chat")
async def chat_endpoint(req: dict):
    """Fallback REST chat endpoint for the assistant agent."""

    message = req.get("message", "")
    if not message:
        return {"status": "error", "message": "message is required"}

    cap_registry = get_capability_registry()
    if not cap_registry or "assistant" not in cap_registry:
        return {"status": "error", "message": "Assistant is not initialized"}

    try:
        payload = {"message": message}
        if req.get("session_id"):
            payload["session_id"] = req.get("session_id")
        if req.get("persona_id"):
            payload["persona_id"] = req.get("persona_id")
        if isinstance(req.get("messages"), list):
            payload["messages"] = req["messages"]
        elif isinstance(req.get("history"), list):
            payload["history"] = req["history"]

        memory_context, memories_used = await build_memory_context(message)
        if memory_context:
            payload["memory_context"] = memory_context

        start = time.perf_counter()
        result = await cap_registry.execute("assistant", **payload)
        response_text = result.get("response", str(result))
        schedule_memory_reflection(
            user_message=message,
            assistant_text=response_text,
            source="rest_chat",
            session_id=req.get("session_id"),
        )
        return {
            "status": "ok",
            "response": response_text,
            "memories_used": memories_used,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
            "usage": result.get("usage", {}),
        }
    except Exception as exc:
        return {"status": "error", "message": f"processing failed: {str(exc)}"}


@app.post("/api/chat/stream")
async def chat_stream_endpoint(req: dict):
    """SSE streaming chat endpoint."""

    import json as _json

    message = req.get("message", "")
    if not message:
        return {"status": "error", "message": "message is required"}

    cap_registry = get_capability_registry()
    if not cap_registry or "assistant" not in cap_registry:
        return {"status": "error", "message": "Assistant is not initialized"}

    capability = cap_registry.get("assistant")

    async def event_generator():
        def sse(event: dict[str, Any]) -> str:
            return f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"

        request_started_at = time.perf_counter()
        tool_started_at: dict[str, float] = {}
        try:
            payload = {"message": message}
            if req.get("session_id"):
                payload["session_id"] = req.get("session_id")
            if req.get("persona_id"):
                payload["persona_id"] = req.get("persona_id")
            if isinstance(req.get("messages"), list):
                payload["messages"] = req["messages"]
            elif isinstance(req.get("history"), list):
                payload["history"] = req["history"]

            memory_context, memories_used = await build_memory_context(message)
            if memory_context:
                payload["memory_context"] = memory_context

            if hasattr(capability, "execute_stream"):
                final_response = ""
                progress_event = {
                    "type": "agent_progress",
                    "agent": "assistant",
                    "activity": "planning",
                    "status": "running",
                    "message": "Preparing context and contacting LLM",
                }
                await broadcast_monitor_event("agent_progress", progress_event)
                yield sse(progress_event)
                async for event in capability.execute_stream(**payload):
                    if isinstance(event, dict) and event.get("type") == "tool_call":
                        tool_name = str(event.get("tool") or "")
                        call_id = str(event.get("tool_call_id") or f"{tool_name}:{len(tool_started_at) + 1}")
                        tool_started_at[call_id] = time.perf_counter()
                        progress_event = {
                            "type": "agent_progress",
                            "agent": "assistant",
                            "activity": "calling_tool",
                            "status": "running",
                            "tool": tool_name,
                            "tool_call_id": call_id,
                        }
                        event = dict(event)
                        event["tool_call_id"] = call_id
                        event.setdefault("status", "running")
                        await broadcast_monitor_event("agent_progress", progress_event)
                        await broadcast_monitor_event(
                            "tool_call_started",
                            {
                                **progress_event,
                                "args": event.get("args"),
                                "concurrent": bool(event.get("concurrent")),
                            },
                        )
                        yield sse(progress_event)
                    elif isinstance(event, dict) and event.get("type") == "tool_result":
                        tool_name = str(event.get("tool") or "")
                        call_id = str(event.get("tool_call_id") or f"{tool_name}:latest")
                        started = tool_started_at.pop(call_id, None)
                        elapsed_ms = round((time.perf_counter() - started) * 1000, 2) if started else None
                        result_payload = event.get("result")
                        is_error = isinstance(result_payload, dict) and bool(result_payload.get("error"))
                        progress_event = {
                            "type": "agent_progress",
                            "agent": "assistant",
                            "activity": "waiting",
                            "status": "error" if is_error else "running",
                            "tool": tool_name,
                            "tool_call_id": call_id,
                            "elapsed_ms": elapsed_ms,
                        }
                        event = dict(event)
                        event["tool_call_id"] = call_id
                        event["status"] = "error" if is_error else "success"
                        event["elapsed_ms"] = elapsed_ms
                        await broadcast_monitor_event("agent_progress", progress_event)
                        await broadcast_monitor_event(
                            "tool_call_finished",
                            {
                                **progress_event,
                                "status": "error" if is_error else "success",
                                "result": result_payload,
                                "truncated": bool(event.get("truncated")),
                            },
                        )
                        yield sse(progress_event)
                    if isinstance(event, dict) and event.get("type") == "done":
                        event = dict(event)
                        event["elapsed_ms"] = round((time.perf_counter() - request_started_at) * 1000, 2)
                        event = _attach_stream_memory_usage(
                            event,
                            memories_used=memories_used,
                        )
                        content = event.get("content")
                        if isinstance(content, dict):
                            final_response = str(content.get("response") or content)
                        else:
                            final_response = str(content or "")
                        done_progress = {
                            "type": "agent_progress",
                            "agent": "assistant",
                            "activity": "completed",
                            "status": "completed",
                            "elapsed_ms": event.get("elapsed_ms"),
                        }
                        await broadcast_monitor_event("agent_progress", done_progress)
                    yield sse(event)
                    if isinstance(event, dict) and event.get("type") == "done":
                        yield sse(done_progress)
                if final_response:
                    schedule_memory_reflection(
                        user_message=message,
                        assistant_text=final_response,
                        source="rest_chat_stream",
                        session_id=req.get("session_id"),
                    )
            else:
                result = await cap_registry.execute("assistant", **payload)
                response_text = result.get("response", str(result))
                schedule_memory_reflection(
                    user_message=message,
                    assistant_text=response_text,
                    source="rest_chat_stream",
                    session_id=req.get("session_id"),
                )
                yield sse({'type': 'thinking', 'content': response_text})
                elapsed_ms = round((time.perf_counter() - request_started_at) * 1000, 2)
                yield sse({'type': 'done', 'content': result, 'usage': result.get('usage', {}), 'elapsed_ms': elapsed_ms})
        except Exception as exc:
            yield sse({'type': 'done', 'content': {'error': str(exc)}})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    """Primary WebSocket endpoint."""

    await ws_handler(websocket)


if __name__ == "__main__":
    import uvicorn

    config = load_config()
    server_config = config.get("server", {})
    uvicorn.run(
        app,
        host=server_config.get("host", "127.0.0.1"),
        port=int(server_config.get("port", 8001)),
    )

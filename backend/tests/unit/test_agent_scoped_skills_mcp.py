import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.mcp import (
    build_mcp_capability_status,
    format_mcp_servers_for_prompt,
    merge_mcp_servers_preserving_masked_env,
    normalize_agent_mcp_servers,
    validate_agent_mcp_servers_payload,
    validate_mcp_server_payload,
)
from core.mcp_adapter import (
    MCPServerProxyCapability,
    build_agent_mcp_runtime_status,
    build_mcp_proxy_tool_name,
    create_agent_mcp_proxy_capabilities,
)
from core.skills import format_skills_for_prompt, load_agent_skills


def test_load_agent_skills_from_directory_and_disabled(tmp_path):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\n# Instructions\nFollow demo steps.",
        encoding="utf-8",
    )

    agent = {"name": "assistant", "skills": {"directories": [str(tmp_path / "skills")]}}
    skills = load_agent_skills(agent, project_root=tmp_path)
    assert [skill.name for skill in skills] == ["demo"]
    prompt = format_skills_for_prompt(skills)
    assert "Demo skill" in prompt
    assert "Follow demo steps" in prompt

    disabled = {"name": "assistant", "skills": {"directories": [str(tmp_path / "skills")], "disabled": ["demo"]}}
    assert load_agent_skills(disabled, project_root=tmp_path) == []


def test_load_agent_skills_inline_items_are_agent_scoped():
    agent = {
        "name": "coder",
        "skills": {
            "items": [
                {"name": "repo_style", "description": "Repo conventions", "instructions": "Keep patches small."}
            ]
        },
    }
    skills = load_agent_skills(agent)
    assert len(skills) == 1
    assert skills[0].name == "repo_style"
    assert "Keep patches small" in format_skills_for_prompt(skills)
    assert load_agent_skills({"name": "reviewer"}) == []


def test_disabled_skill_or_missing_path_does_not_prevent_startup(tmp_path):
    agent = {
        "name": "assistant",
        "skills": {
            "items": [
                {"name": "disabled_inline", "instructions": "ignore", "enabled": False},
                {"path": str(tmp_path / "missing" / "SKILL.md")},
                {"name": "active_inline", "instructions": "load this"},
            ],
            "disabled": ["disabled_by_name"],
        },
    }

    skills = load_agent_skills(agent, project_root=tmp_path)

    assert [skill.name for skill in skills] == ["active_inline"]


def test_agent_mcp_normalization_validation_and_prompt():
    agent = {
        "name": "assistant",
        "mcp_servers": [
            {
                "name": "filesystem",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                "env": {"DEBUG": "1"},
                "enabled": True,
                "description": "Read project files",
            },
            {"name": "off", "command": "noop", "enabled": False},
        ],
    }
    servers = normalize_agent_mcp_servers(agent)
    assert len(servers) == 1
    assert servers[0].name == "filesystem"
    assert servers[0].env == {"DEBUG": "1"}
    prompt = format_mcp_servers_for_prompt(servers)
    assert "filesystem" in prompt
    assert "Agent-scoped proxy tool" in prompt
    assert validate_mcp_server_payload({"name": "bad", "enabled": True}) == ["command is required when server is enabled"]


def test_mcp_payload_list_validation_reports_duplicate_and_invalid_servers():
    errors = validate_agent_mcp_servers_payload([
        {"name": "fs", "command": "npx", "transport": "stdio"},
        {"name": "fs", "command": "node", "transport": "stdio"},
        {"name": "bad", "enabled": True, "args": "not-list", "transport": "websocket"},
    ])

    assert "MCP server 'fs' 配置无效: duplicate server name" in errors
    assert "MCP server 'bad' 配置无效: command is required when server is enabled" in errors
    assert "MCP server 'bad' 配置无效: args must be a list of strings" in errors
    assert "MCP server 'bad' 配置无效: transport must be one of http, sse, stdio, streamable_http" in errors


def test_mcp_masked_env_values_preserve_existing_secrets():
    merged = merge_mcp_servers_preserving_masked_env(
        [
            {
                "name": "filesystem",
                "command": "npx",
                "env": {"TOKEN": "real-secret", "MODE": "prod"},
            }
        ],
        [
            {
                "name": "filesystem",
                "command": "npx",
                "env": {"TOKEN": "********", "MODE": "dev", "NEW": "${NEW_TOKEN}"},
            }
        ],
    )

    assert merged[0]["env"] == {
        "TOKEN": "real-secret",
        "MODE": "dev",
        "NEW": "${NEW_TOKEN}",
    }


def test_mcp_capability_status_explains_runtime_pending():
    status = build_mcp_capability_status({
        "mcp_servers": [
            {"name": "fs", "command": "npx", "enabled": True},
            {"name": "disabled", "enabled": False},
        ]
    })

    assert status["state"] == "configured_pending_runtime"
    assert status["enabled_servers"] == 1
    assert status["configured_servers"] == 2
    assert "Agent 作用域代理工具" in status["message"]


def test_mcp_capability_status_reports_config_errors():
    status = build_mcp_capability_status({"mcp_servers": [{"name": "bad", "enabled": True}]})

    assert status["state"] == "config_error"
    assert status["enabled_servers"] == 0
    assert status["errors"] == ["MCP server 'bad' 配置无效: command is required when server is enabled"]


def test_mcp_capability_status_keeps_disabled_servers_unconnected():
    status = build_mcp_capability_status({
        "mcp_servers": [
            {"name": "disabled_fs", "command": "npx", "enabled": False},
        ]
    })

    assert status["state"] == "disabled"
    assert status["configured_servers"] == 1
    assert status["enabled_servers"] == 0
    assert status["connected_tools"] == 0


def test_mcp_proxy_tool_name_is_agent_scoped_and_stable():
    first = build_mcp_proxy_tool_name("assistant", "filesystem")
    second = build_mcp_proxy_tool_name("assistant", "filesystem")
    sanitized = build_mcp_proxy_tool_name("assistant", "file-system")
    reviewer = build_mcp_proxy_tool_name("reviewer", "filesystem")

    assert first == "mcp__assistant__filesystem"
    assert second == first
    assert sanitized == "mcp__assistant__file-system"
    assert reviewer == "mcp__reviewer__filesystem"
    assert reviewer != first


def test_mcp_adapter_does_not_register_disabled_servers():
    servers = normalize_agent_mcp_servers({
        "mcp_servers": [
            {"name": "filesystem", "command": "npx", "enabled": True},
            {"name": "off", "command": "npx", "enabled": False},
        ]
    })
    tools = create_agent_mcp_proxy_capabilities(
        agent_name="assistant",
        servers=servers,
        project_root=Path.cwd(),
    )

    names = [tool.name for tool in tools]
    assert names == ["mcp__assistant__filesystem"]
    assert all("__off__" not in name for name in names)


def test_agent_mcp_proxy_tools_remain_scoped_in_agent_runtime_tools():
    assistant = SimpleNamespace(name="assistant", _tools=[])
    reviewer = SimpleNamespace(name="reviewer", _tools=[])
    server = normalize_agent_mcp_servers({"mcp_servers": [{"name": "filesystem", "command": "npx"}]})

    assistant._tools.extend(
        create_agent_mcp_proxy_capabilities(
            agent_name="assistant",
            servers=server,
            project_root=Path.cwd(),
        )
    )
    reviewer._tools.extend(
        create_agent_mcp_proxy_capabilities(
            agent_name="reviewer",
            servers=server,
            project_root=Path.cwd(),
        )
    )

    assistant_tool_names = {tool.name for tool in assistant._tools}
    reviewer_tool_names = {tool.name for tool in reviewer._tools}

    assert assistant_tool_names == {"mcp__assistant__filesystem"}
    assert reviewer_tool_names == {"mcp__reviewer__filesystem"}
    assert assistant_tool_names.isdisjoint(reviewer_tool_names)


def test_mcp_capability_status_reports_adapter_connection_states():
    configured = {"mcp_servers": [{"name": "filesystem", "command": "npx", "enabled": True}]}

    for expected_state in ("proxy_available", "partial", "adapter_unavailable"):
        status = build_mcp_capability_status(
            configured,
            runtime_status={
                "state": expected_state,
                "registered_tools": 1,
                "connected_tools": 1 if expected_state in {"proxy_available", "partial"} else 0,
            },
        )

        assert status["state"] == expected_state
        assert status["state"] != "configured_not_connected"
        assert status["enabled_servers"] == 1


def test_mcp_runtime_status_reports_adapter_unavailable(monkeypatch, tmp_path):
    import core.mcp_adapter as adapter

    monkeypatch.setattr(adapter, "is_mcp_sdk_available", lambda: False)
    servers = normalize_agent_mcp_servers({"mcp_servers": [{"name": "filesystem", "command": "npx"}]})

    status = build_agent_mcp_runtime_status("assistant", servers, project_root=tmp_path)

    assert status["state"] == "adapter_unavailable"
    assert status["registered_tools"] == 1
    assert status["connected_tools"] == 0
    assert status["servers"]["filesystem"]["tool"] == "mcp__assistant__filesystem"


async def test_mcp_proxy_returns_clear_error_when_sdk_missing(monkeypatch, tmp_path):
    import core.mcp_adapter as adapter

    monkeypatch.setattr(adapter, "is_mcp_sdk_available", lambda: False)
    server = normalize_agent_mcp_servers({"mcp_servers": [{"name": "filesystem", "command": "npx"}]})[0]
    tool = MCPServerProxyCapability(
        agent_name="assistant",
        server=server,
        project_root=tmp_path,
    )

    result = await tool.execute(operation="list_tools")

    assert result["error"] == "mcp_sdk_unavailable"


async def test_agent_routes_return_scoped_config_and_mcp_status(monkeypatch):
    from api.routes import agents as agent_routes

    class Status:
        value = "idle"

    class Meta:
        name = "assistant"
        status = Status()
        capabilities = ["memory_search"]
        description = "Assistant"
        runtime_config = {
            "llm": {"provider": "openai", "model": "gpt-global", "source": "global_default"},
            "mcp_capability_status": {
                "state": "adapter_unavailable",
                "configured_servers": 1,
                "enabled_servers": 1,
                "registered_tools": 1,
                "connected_tools": 0,
            },
        }

    class Agent:
        def get_metadata(self):
            return Meta()

    class Registry:
        def list_all(self):
            return [Meta()]

        def get(self, name):
            return Agent() if name == "assistant" else None

    config = {
        "name": "assistant",
        "skills": {"items": [{"name": "style", "instructions": "short"}]},
        "mcp_servers": [{"name": "fs", "command": "npx", "env": {"TOKEN": "secret"}, "enabled": True}],
        "llm": {"provider": "openai", "model": "gpt-5.4-mini", "temperature": 0.2},
        "default_workspace_id": "project-demo",
    }
    monkeypatch.setattr(agent_routes, "get_agent_registry", lambda: Registry())
    monkeypatch.setattr(agent_routes, "_agent_config_map", lambda: {"assistant": config})

    listed = await agent_routes.list_agents()
    detail = await agent_routes.get_agent("assistant")

    assert listed.status == "ok"
    assert listed.data[0]["skills"]["items"][0]["name"] == "style"
    assert listed.data[0]["mcp_servers"][0]["name"] == "fs"
    assert listed.data[0]["mcp_servers"][0]["env"] == {"TOKEN": "********"}
    assert listed.data[0]["mcp_capability_status"]["state"] == "adapter_unavailable"
    assert listed.data[0]["llm"]["model"] == "gpt-5.4-mini"
    assert listed.data[0]["model"] == "gpt-5.4-mini"
    assert listed.data[0]["workspace_binding"]["workspace_id"] == "project-demo"
    assert detail.data["mcp_capability_status"]["enabled_servers"] == 1


async def test_agent_routes_show_inherited_global_model(monkeypatch):
    from api.routes import agents as agent_routes

    class Status:
        value = "idle"

    class Meta:
        name = "assistant"
        status = Status()
        capabilities = []
        description = "Assistant"
        runtime_config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-global",
                "api_key_set": True,
                "source": "global_default",
            }
        }

    class Registry:
        def list_all(self):
            return [Meta()]

    monkeypatch.setattr(agent_routes, "get_agent_registry", lambda: Registry())
    monkeypatch.setattr(agent_routes, "_agent_config_map", lambda: {"assistant": {"name": "assistant"}})

    listed = await agent_routes.list_agents()

    assert listed.status == "ok"
    assert listed.data[0]["model"] == "gpt-global"
    assert listed.data[0]["llm"]["source"] == "global_default"
    assert listed.data[0]["llm"]["api_key_set"] is True


async def test_agent_create_rejects_invalid_mcp_before_saving(monkeypatch):
    from api.routes import agents as agent_routes
    from api.schemas import AgentCreateRequest

    saved = False

    def fail_if_saved(*args, **kwargs):
        nonlocal saved
        saved = True

    monkeypatch.setattr(agent_routes, "load_single_yaml", lambda name: {"agents": []})
    monkeypatch.setattr(agent_routes, "save_yaml_config", fail_if_saved)

    response = await agent_routes.create_agent(AgentCreateRequest(
        name="bad_mcp_agent",
        mcp_servers=[{"name": "fs", "enabled": True}],
    ))

    assert response.status == "error"
    assert "command is required when server is enabled" in response.message
    assert saved is False


async def test_agent_create_rejects_high_risk_tools_before_saving(monkeypatch):
    from api.routes import agents as agent_routes
    from api.schemas import AgentCreateRequest

    saved = False

    async def fail_if_saved(*args, **kwargs):
        nonlocal saved
        saved = True

    monkeypatch.setattr(agent_routes, "load_single_yaml", lambda name: {"agents": []})
    monkeypatch.setattr(agent_routes, "_save_config_and_reload", fail_if_saved)

    response = await agent_routes.create_agent(
        AgentCreateRequest(name="unsafe_agent", tools=["bash"])
    )

    assert response.status == "error"
    assert saved is False


async def test_agent_update_rejects_adding_management_tool(monkeypatch):
    from api.routes import agents as agent_routes
    from api.schemas import AgentUpdateRequest

    async def fail_if_saved(*args, **kwargs):
        raise AssertionError("should not save invalid agent update")

    monkeypatch.setattr(
        agent_routes,
        "load_single_yaml",
        lambda name: {"agents": [{"name": "assistant", "tools": ["memory_search"]}]},
    )
    monkeypatch.setattr(agent_routes, "_save_config_and_reload", fail_if_saved)

    response = await agent_routes.update_agent(
        "assistant",
        AgentUpdateRequest(tools=["memory_search", "apply_agent_config_patch"]),
    )

    assert response.status == "error"
    assert "Agent" in response.message


async def test_agent_create_persists_llm_secret_without_returning_it(monkeypatch):
    from api.routes import agents as agent_routes
    from api.schemas import AgentCreateRequest

    saved = {}

    monkeypatch.setattr(agent_routes, "load_single_yaml", lambda name: {"agents": []})

    async def no_reload(data, previous_data):
        saved.update(data)

    monkeypatch.setattr(agent_routes, "_save_config_and_reload", no_reload)

    response = await agent_routes.create_agent(
        AgentCreateRequest(
            name="model_agent",
            llm={
                "provider": "openai",
                "api_key": "sk-agent",
                "model": "gpt-5.4-mini",
                "openai": {"max_completion_tokens": 1024},
            },
        )
    )

    assert saved["agents"][0]["llm"]["api_key"] == "sk-agent"
    assert saved["agents"][0]["llm"]["openai"]["max_completion_tokens"] == 1024
    assert "api_key" not in response.data["llm"]
    assert response.data["llm"]["api_key_set"] is True


async def test_agent_invoke_drops_untrusted_workspace_root(monkeypatch, tmp_path):
    from api.routes import agents as agent_routes
    from api.schemas import AgentInvokeRequest

    captured = {}

    class Registry:
        def __contains__(self, name):
            return name == "assistant"

        async def execute(self, name, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    monkeypatch.setattr(agent_routes, "get_capability_registry", lambda: Registry())
    monkeypatch.setattr(agent_routes, "_agent_config_map", lambda: {})

    response = await agent_routes.invoke_agent(
        "assistant",
        AgentInvokeRequest(
            data={
                "message": "hello",
                "workspace_root": str(tmp_path),
                "_trusted_workspace_root": str(tmp_path / "trusted"),
            }
        ),
    )

    assert response.status == "ok"
    assert captured["message"] == "hello"
    assert "workspace_root" not in captured
    assert "_trusted_workspace_root" not in captured


def test_agent_config_schemas_accept_scoped_runtime_fields():
    from api.schemas import AgentCreateRequest, AgentInfo, AgentUpdateRequest

    create = AgentCreateRequest(
        name="runtime_agent",
        llm={
            "provider": "anthropic",
            "api_key": "sk-agent",
            "model": "claude-sonnet",
            "temperature": 0.1,
            "stop_sequences": ["END"],
            "anthropic": {"top_k": 3},
        },
        skills={"items": [{"name": "style", "instructions": "Use style."}]},
        mcp_servers=[{"name": "fs", "command": "npx", "args": ["server"], "env": {"A": "B"}}],
    )
    assert create.llm.provider == "anthropic"
    assert create.llm.api_key == "sk-agent"
    assert create.llm.model == "claude-sonnet"
    assert create.llm.stop_sequences == ["END"]
    assert create.llm.anthropic["top_k"] == 3
    assert create.skills.items[0]["name"] == "style"
    assert create.mcp_servers[0].name == "fs"

    update = AgentUpdateRequest(mcp_servers=[], model="gpt-5.4")
    assert update.mcp_servers == []
    assert update.model == "gpt-5.4"

    info = AgentInfo(
        name="runtime_agent",
        status="idle",
        capabilities=[],
        mcp_capability_status={"state": "not_configured"},
        llm={"model": "gpt-5.4-mini", "source": "agent_config"},
    )
    assert info.mcp_capability_status["state"] == "not_configured"
    assert info.llm.model == "gpt-5.4-mini"


def test_create_agents_from_config_uses_agent_specific_model(monkeypatch):
    from api import main as api_main
    from core.capability import CapabilityRegistry

    created = []

    def fake_create_llm_client(provider, api_key, model, base_url=None, generation_config=None):
        client = object()
        created.append(
            {
                "client": client,
                "provider": provider,
                "api_key": api_key,
                "model": model,
                "base_url": base_url,
                "generation_config": generation_config,
            }
        )
        return client

    monkeypatch.setattr(api_main, "create_llm_client", fake_create_llm_client)
    global_client = object()
    agents = api_main._create_agents_from_config(
        [
            {
                "name": "coder",
                "tools": [],
                "llm": {
                    "provider": "anthropic",
                    "api_key": "sk-agent",
                    "model": "claude-sonnet",
                    "base_url": "https://anthropic.example",
                    "temperature": 0.1,
                    "stop_sequences": ["END"],
                    "anthropic": {"top_k": 3},
                },
            },
            {"name": "reviewer", "tools": []},
        ],
        global_client,
        CapabilityRegistry(),
        base_llm_config={
            "provider": "openai",
            "api_key": "sk-global",
            "model": "gpt-global",
            "base_url": "https://proxy.example/v1",
        },
    )

    assert len(created) == 1
    assert created[0]["provider"] == "anthropic"
    assert created[0]["api_key"] == "sk-agent"
    assert created[0]["model"] == "claude-sonnet"
    assert created[0]["base_url"] == "https://anthropic.example"
    assert created[0]["generation_config"]["temperature"] == 0.1
    assert created[0]["generation_config"]["stop_sequences"] == ["END"]
    assert created[0]["generation_config"]["anthropic"]["top_k"] == 3
    assert agents[0].llm is created[0]["client"]
    assert agents[1].llm is global_client
    assert agents[0]._runtime_config["llm"]["source"] == "agent_config"
    assert agents[1]._runtime_config["llm"]["source"] == "global_default"


def test_create_agents_from_config_mounts_mcp_proxy_only_on_owning_agent(monkeypatch):
    from api import main as api_main
    from core.capability import CapabilityRegistry

    monkeypatch.setattr(api_main, "PROJECT_ROOT", Path.cwd())
    global_client = object()
    cap_registry = CapabilityRegistry()
    agents = api_main._create_agents_from_config(
        [
            {
                "name": "assistant",
                "tools": [],
                "mcp_servers": [{"name": "filesystem", "command": "npx"}],
            },
            {"name": "reviewer", "tools": []},
        ],
        global_client,
        cap_registry,
        base_llm_config={},
    )

    assistant_tools = set(agents[0].get_capabilities())
    reviewer_tools = set(agents[1].get_capabilities())

    assert "mcp__assistant__filesystem" in assistant_tools
    assert "mcp__assistant__filesystem" not in reviewer_tools
    assert "mcp__assistant__filesystem" in cap_registry.list_names()
    assert agents[0]._runtime_config["mcp_capability_status"]["state"] in {
        "adapter_unavailable",
        "proxy_available",
    }

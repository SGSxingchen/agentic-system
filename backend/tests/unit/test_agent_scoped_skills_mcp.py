import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.mcp import (
    build_mcp_capability_status,
    format_mcp_servers_for_prompt,
    normalize_agent_mcp_servers,
    validate_agent_mcp_servers_payload,
    validate_mcp_server_payload,
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
    skills = load_agent_skills(agent)
    assert [skill.name for skill in skills] == ["demo"]
    prompt = format_skills_for_prompt(skills)
    assert "Demo skill" in prompt
    assert "Follow demo steps" in prompt

    disabled = {"name": "assistant", "skills": {"directories": [str(tmp_path / "skills")], "disabled": ["demo"]}}
    assert load_agent_skills(disabled) == []


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

    skills = load_agent_skills(agent)

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
    assert "not automatically expose" in prompt
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


def test_mcp_capability_status_explains_configured_not_connected():
    status = build_mcp_capability_status({
        "mcp_servers": [
            {"name": "fs", "command": "npx", "enabled": True},
            {"name": "disabled", "enabled": False},
        ]
    })

    assert status["state"] == "configured_not_connected"
    assert status["enabled_servers"] == 1
    assert status["configured_servers"] == 2
    assert "不会自动启动 MCP 进程" in status["message"]


def test_mcp_capability_status_reports_config_errors():
    status = build_mcp_capability_status({"mcp_servers": [{"name": "bad", "enabled": True}]})

    assert status["state"] == "config_error"
    assert status["enabled_servers"] == 0
    assert status["errors"] == ["MCP server 'bad' 配置无效: command is required when server is enabled"]


async def test_agent_routes_return_scoped_config_and_mcp_status(monkeypatch):
    from api.routes import agents as agent_routes

    class Status:
        value = "idle"

    class Meta:
        name = "assistant"
        status = Status()
        capabilities = ["memory_search"]
        description = "Assistant"

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
        "mcp_servers": [{"name": "fs", "command": "npx", "enabled": True}],
    }
    monkeypatch.setattr(agent_routes, "get_agent_registry", lambda: Registry())
    monkeypatch.setattr(agent_routes, "_agent_config_map", lambda: {"assistant": config})

    listed = await agent_routes.list_agents()
    detail = await agent_routes.get_agent("assistant")

    assert listed.status == "ok"
    assert listed.data[0]["skills"]["items"][0]["name"] == "style"
    assert listed.data[0]["mcp_servers"][0]["name"] == "fs"
    assert listed.data[0]["mcp_capability_status"]["state"] == "configured_not_connected"
    assert detail.data["mcp_capability_status"]["enabled_servers"] == 1


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
    assert "MCP server 'fs' 配置无效: command is required when server is enabled" in response.message
    assert saved is False


def test_agent_config_schemas_accept_scoped_runtime_fields():
    from api.schemas import AgentCreateRequest, AgentInfo, AgentUpdateRequest

    create = AgentCreateRequest(
        name="runtime_agent",
        skills={"items": [{"name": "style", "instructions": "Use style."}]},
        mcp_servers=[{"name": "fs", "command": "npx", "args": ["server"], "env": {"A": "B"}}],
    )
    assert create.skills.items[0]["name"] == "style"
    assert create.mcp_servers[0].name == "fs"

    update = AgentUpdateRequest(mcp_servers=[])
    assert update.mcp_servers == []

    info = AgentInfo(
        name="runtime_agent",
        status="idle",
        capabilities=[],
        mcp_capability_status={"state": "not_configured"},
    )
    assert info.mcp_capability_status["state"] == "not_configured"

"""能力库（catalog）API 集成测试。

覆盖 spec §9 后端测试计划：
- GET /api/catalog/{tools|skills|mcp} 结构正确 + used_by 反映 agents.yaml
- skills 目录解析（临时 SKILL.md 出现在 catalog）
- mcp 模板加载 + env 脱敏
- assemble round-trip（tool / skill / mcp 写入 agent 配置 + 幂等去重）
- 错误：未知 agent / 未知能力 / 非法 MCP env

测试通过 ``AGENTIC_CONFIG_DIR`` / ``AGENTIC_SKILLS_ROOT`` 把读写指向 tmp 目录，
避免污染仓库内的 config/ 与 skills/。装配链路真实落盘到 tmp config + 走 reload。
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.agent import AgentRegistry
from core.capability import CapabilityRegistry
from core.capability.base import CapabilityBase, CapabilitySchema
from api.dependencies import (
    set_agent_registry,
    set_capability_registry,
    set_reload_agent_fn,
)


class _DummyTool(CapabilityBase):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"dummy {self._name}"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self._name,
            description=self.description,
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )

    async def execute(self, **kwargs):
        return {"ok": True}


def _create_test_app():
    from fastapi import FastAPI

    from api.routes import agents_router, catalog_router

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    app = FastAPI(lifespan=_noop_lifespan)
    app.include_router(agents_router)
    app.include_router(catalog_router)
    return app


AGENTS_SEED = [
    {
        "name": "assistant",
        "description": "对话助手",
        "tools": ["read_file", "calculator"],
    },
    {
        "name": "coder",
        "description": "写代码",
        "tools": ["read_file", "write_file"],
        "skills": {"enabled": True, "items": [{"path": "skills/pdf/SKILL.md"}]},
        "mcp_servers": [{"name": "fetch", "command": "npx", "enabled": False}],
    },
]

MCP_SEED = {
    "mcp_servers": [
        {
            "name": "filesystem",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "<ABS_PATH>"],
            "transport": "stdio",
            "enabled": False,
            "description": "fs server",
            "env": {"SECRET_TOKEN": "super-secret"},
        },
        {"name": "git", "command": "npx", "args": [], "transport": "stdio", "enabled": False},
        {"name": "fetch", "command": "npx", "args": [], "transport": "stdio", "enabled": False},
        {"name": "sqlite", "command": "npx", "args": [], "transport": "stdio", "enabled": False},
    ]
}


@pytest.fixture
def catalog_env(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agents.yaml").write_text(yaml.dump({"agents": AGENTS_SEED}), encoding="utf-8")
    (config_dir / "mcp_servers.yaml").write_text(yaml.dump(MCP_SEED), encoding="utf-8")

    skills_root = tmp_path / "skills"
    for slug, name in (("pdf", "pdf"), ("mcp-builder", "mcp-builder")):
        (skills_root / slug).mkdir(parents=True, exist_ok=True)
        (skills_root / slug / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} skill desc\n---\n\n# Body\n"
            + ("x" * 600),
            encoding="utf-8",
        )

    monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AGENTIC_SKILLS_ROOT", str(tmp_path))

    registry = AgentRegistry()
    cap_registry = CapabilityRegistry()
    for tool in ("read_file", "write_file", "calculator"):
        cap_registry.register_native(_DummyTool(tool))

    async def _noop_reload():
        return None

    set_agent_registry(registry)
    set_capability_registry(cap_registry)
    set_reload_agent_fn(_noop_reload)

    yield {"config_dir": config_dir, "skills_root": skills_root}

    set_agent_registry(None)
    set_capability_registry(None)
    set_reload_agent_fn(None)  # type: ignore[arg-type]


@pytest.fixture
async def client(catalog_env):
    app = _create_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _read_agents(config_dir: Path) -> dict:
    data = yaml.safe_load((config_dir / "agents.yaml").read_text(encoding="utf-8"))
    return {a["name"]: a for a in data["agents"]}


# ─── 列目录 ────────────────────────────────────────────────────────


class TestCatalogTools:
    async def test_tools_structure_and_used_by(self, client):
        resp = await client.get("/api/catalog/tools")
        assert resp.status_code == 200
        items = {item["name"]: item for item in resp.json()["data"]}
        assert "read_file" in items
        rf = items["read_file"]
        assert rf["kind"] == "tool"
        assert "parameters" in rf
        assert set(rf["used_by"]) == {"assistant", "coder"}
        assert items["calculator"]["used_by"] == ["assistant"]


class TestCatalogSkills:
    async def test_skills_parsed_from_dir(self, client):
        resp = await client.get("/api/catalog/skills")
        assert resp.status_code == 200
        items = {item["name"]: item for item in resp.json()["data"]}
        assert {"pdf", "mcp-builder"} <= set(items)
        pdf = items["pdf"]
        assert pdf["kind"] == "skill"
        assert pdf["source"] == "skills/pdf/SKILL.md"
        # instructions_preview 截断在 400 字内
        assert len(pdf["instructions_preview"]) <= 401
        # pdf 已被 coder 引用
        assert pdf["used_by"] == ["coder"]
        assert items["mcp-builder"]["used_by"] == []

    async def test_missing_skills_dir_returns_empty(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("AGENTIC_SKILLS_ROOT", str(tmp_path / "nope"))
        resp = await client.get("/api/catalog/skills")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestCatalogMcp:
    async def test_mcp_templates_loaded_and_env_masked(self, client):
        resp = await client.get("/api/catalog/mcp")
        assert resp.status_code == 200
        items = {item["name"]: item for item in resp.json()["data"]}
        assert {"filesystem", "git", "fetch", "sqlite"} == set(items)
        fs = items["filesystem"]
        assert fs["kind"] == "mcp"
        assert fs["enabled"] is False
        # env 脱敏：原始 super-secret 不应出现
        assert fs["env"] == {"SECRET_TOKEN": "********"}
        assert "super-secret" not in str(fs["env"])
        # fetch 已被 coder 引用
        assert items["fetch"]["used_by"] == ["coder"]

    async def test_missing_mcp_file_returns_empty(self, client, catalog_env):
        (catalog_env["config_dir"] / "mcp_servers.yaml").unlink()
        resp = await client.get("/api/catalog/mcp")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


# ─── 装配 round-trip ───────────────────────────────────────────────


class TestAssembleTool:
    async def test_assemble_tool_round_trip_and_idempotent(self, client, catalog_env):
        resp = await client.post(
            "/api/catalog/tools/calculator/assemble", json={"agent_name": "coder"}
        )
        assert resp.status_code == 200, resp.text
        agents = _read_agents(catalog_env["config_dir"])
        assert "calculator" in agents["coder"]["tools"]

        # 再次装配应幂等（不重复）
        resp2 = await client.post(
            "/api/catalog/tools/calculator/assemble", json={"agent_name": "coder"}
        )
        assert resp2.status_code == 200
        agents2 = _read_agents(catalog_env["config_dir"])
        assert agents2["coder"]["tools"].count("calculator") == 1


class TestAssembleSkill:
    async def test_assemble_skill_round_trip_and_idempotent(self, client, catalog_env):
        resp = await client.post(
            "/api/catalog/skills/mcp-builder/assemble", json={"agent_name": "assistant"}
        )
        assert resp.status_code == 200, resp.text
        agents = _read_agents(catalog_env["config_dir"])
        skills = agents["assistant"]["skills"]
        assert skills["enabled"] is True
        paths = [i.get("path") for i in skills["items"]]
        assert "skills/mcp-builder/SKILL.md" in paths

        resp2 = await client.post(
            "/api/catalog/skills/mcp-builder/assemble", json={"agent_name": "assistant"}
        )
        assert resp2.status_code == 200
        agents2 = _read_agents(catalog_env["config_dir"])
        paths2 = [i.get("path") for i in agents2["assistant"]["skills"]["items"]]
        assert paths2.count("skills/mcp-builder/SKILL.md") == 1


class TestAssembleMcp:
    async def test_assemble_mcp_round_trip_with_env(self, client, catalog_env):
        resp = await client.post(
            "/api/catalog/mcp/filesystem/assemble",
            json={"agent_name": "assistant", "env": {"ROOT": "/tmp/data"}},
        )
        assert resp.status_code == 200, resp.text
        agents = _read_agents(catalog_env["config_dir"])
        servers = {s["name"]: s for s in agents["assistant"]["mcp_servers"]}
        assert "filesystem" in servers
        fs = servers["filesystem"]
        assert fs["enabled"] is True
        assert fs["env"]["ROOT"] == "/tmp/data"

        # 幂等：再次装配同名 server 不重复
        resp2 = await client.post(
            "/api/catalog/mcp/filesystem/assemble", json={"agent_name": "assistant"}
        )
        assert resp2.status_code == 200
        agents2 = _read_agents(catalog_env["config_dir"])
        names = [s["name"] for s in agents2["assistant"]["mcp_servers"]]
        assert names.count("filesystem") == 1


# ─── 错误用例 ──────────────────────────────────────────────────────


class TestAssembleErrors:
    async def test_unknown_agent_404(self, client):
        resp = await client.post(
            "/api/catalog/tools/calculator/assemble", json={"agent_name": "ghost"}
        )
        assert resp.status_code == 404

    async def test_unknown_tool_404(self, client):
        resp = await client.post(
            "/api/catalog/tools/no_such_tool/assemble", json={"agent_name": "assistant"}
        )
        assert resp.status_code == 404

    async def test_unknown_skill_404(self, client):
        resp = await client.post(
            "/api/catalog/skills/no_such_skill/assemble", json={"agent_name": "assistant"}
        )
        assert resp.status_code == 404

    async def test_unknown_mcp_404(self, client):
        resp = await client.post(
            "/api/catalog/mcp/no_such_server/assemble", json={"agent_name": "assistant"}
        )
        assert resp.status_code == 404

    async def test_unknown_kind_404(self, client):
        resp = await client.post(
            "/api/catalog/bogus/x/assemble", json={"agent_name": "assistant"}
        )
        assert resp.status_code == 404

    async def test_bad_mcp_env_422(self, client, catalog_env):
        # 写入一个 transport 非法的模板，触发 validate_mcp_server_payload 失败
        bad = yaml.safe_load((catalog_env["config_dir"] / "mcp_servers.yaml").read_text())
        bad["mcp_servers"].append(
            {"name": "broken", "command": "", "transport": "bogus", "enabled": False}
        )
        (catalog_env["config_dir"] / "mcp_servers.yaml").write_text(yaml.dump(bad), encoding="utf-8")
        resp = await client.post(
            "/api/catalog/mcp/broken/assemble", json={"agent_name": "assistant"}
        )
        assert resp.status_code == 422

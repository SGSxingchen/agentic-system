import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.mcp import format_mcp_servers_for_prompt, normalize_agent_mcp_servers, validate_mcp_server_payload
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


def test_agent_config_schemas_accept_scoped_runtime_fields():
    from api.schemas import AgentCreateRequest, AgentUpdateRequest

    create = AgentCreateRequest(
        name="runtime_agent",
        skills={"items": [{"name": "style", "instructions": "Use style."}]},
        mcp_servers=[{"name": "fs", "command": "npx", "args": ["server"], "env": {"A": "B"}}],
    )
    assert create.skills.items[0]["name"] == "style"
    assert create.mcp_servers[0].name == "fs"

    update = AgentUpdateRequest(mcp_servers=[])
    assert update.mcp_servers == []

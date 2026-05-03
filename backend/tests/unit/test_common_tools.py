"""Common assistant tool capability tests."""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from capabilities.tools.calculator import CalculatorCapability
from capabilities.tools.datetime_tool import DateTimeCapability
from capabilities.tools.evolution_config import (
    CreateAgentConfigCapability,
    CreateDynamicToolConfigCapability,
)
from capabilities.tools.file_search import FileSearchCapability
from capabilities.tools.json_tool import JsonToolCapability
from capabilities.tools.persona_evolution import (
    ApplyConfirmedPersonaPatchCapability,
    GeneratePersonaPatchProposalCapability,
    ListPersonaPatchHistoryCapability,
    ReadPersonaDefinitionCapability,
    RecordPersonaFeedbackCapability,
)
from capabilities.tools.persona_management import (
    ManagePersonaBindingCapability,
    ManagePersonaDefinitionCapability,
)
from capabilities.tools.text_processor import TextProcessorCapability
from capabilities.tools.web_fetch import WebFetchCapability
from capabilities.tools._web_safety import validate_public_http_url
from capabilities.tools.web_search import WebSearchCapability
from core.capability.registry import CapabilityRegistry


class FakeHeaders(dict):
    def get_content_charset(self) -> str:
        return "utf-8"


class FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = FakeHeaders({
            "Content-Type": "text/html; charset=utf-8",
        })

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit: int) -> bytes:
        return self._body

    def geturl(self) -> str:
        return "https://example.com/page"


PUBLIC_ADDR = (
    socket.AddressFamily.AF_INET,
    socket.SocketKind.SOCK_STREAM,
    6,
    "",
    ("93.184.216.34", 443),
)
NON_GLOBAL_ADDR = (
    socket.AddressFamily.AF_INET,
    socket.SocketKind.SOCK_STREAM,
    6,
    "",
    ("100.64.0.1", 80),
)


def test_web_safety_rejects_non_global_resolved_addresses():
    with (
        patch("socket.getaddrinfo", return_value=[NON_GLOBAL_ADDR]),
        pytest.raises(PermissionError),
    ):
        validate_public_http_url("http://example.com")


def test_web_safety_rejects_invalid_ports():
    with pytest.raises(PermissionError):
        validate_public_http_url("http://example.com:99999")


class TestCalculatorCapability:
    @pytest.mark.asyncio
    async def test_calculates_safe_expression(self):
        tool = CalculatorCapability()
        result = await tool.execute(expression="sqrt(16) + 2 ** 3")
        assert result["result"] == 12

    @pytest.mark.asyncio
    async def test_blocks_unsupported_expression(self):
        tool = CalculatorCapability()
        result = await tool.execute(expression="__import__('os').system('ls')")
        assert "error" in result


class TestDateTimeCapability:
    @pytest.mark.asyncio
    async def test_returns_timezone_time(self):
        tool = DateTimeCapability()
        result = await tool.execute(timezone="UTC", format="human")
        assert result["timezone"] == "UTC"
        assert "iso" in result
        assert "formatted" in result

    @pytest.mark.asyncio
    async def test_unknown_timezone(self):
        tool = DateTimeCapability()
        result = await tool.execute(timezone="No/SuchZone")
        assert "error" in result


class TestJsonToolCapability:
    @pytest.mark.asyncio
    async def test_pretty_and_query(self):
        tool = JsonToolCapability()
        pretty = await tool.execute(text='{"users":[{"name":"Ada"}]}', operation="pretty")
        queried = await tool.execute(
            text='{"users":[{"name":"Ada"}]}',
            operation="query",
            path="users.0.name",
        )
        assert pretty["valid"] is True
        assert "\n" in pretty["text"]
        assert queried["value"] == "Ada"

    @pytest.mark.asyncio
    async def test_invalid_json(self):
        tool = JsonToolCapability()
        result = await tool.execute(text="{bad")
        assert result["valid"] is False


class TestTextProcessorCapability:
    @pytest.mark.asyncio
    async def test_stats_and_keywords(self):
        tool = TextProcessorCapability()
        stats = await tool.execute(text="Agent tool tool evolution.", operation="stats")
        keywords = await tool.execute(text="Agent tool tool evolution.", operation="keywords")
        assert stats["words"] == 4
        assert keywords["keywords"][0]["term"] == "tool"

    @pytest.mark.asyncio
    async def test_slugify(self):
        tool = TextProcessorCapability()
        result = await tool.execute(text="Hello Agent Tool", operation="slugify")
        assert result["text"] == "hello-agent-tool"


class TestFileSearchCapability:
    @pytest.mark.asyncio
    async def test_searches_workspace_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_WORKSPACE_ROOT", str(tmp_path))
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "idea.txt").write_text(
            "private assistant evolution",
            encoding="utf-8",
        )

        tool = FileSearchCapability()
        result = await tool.execute(query="evolution", glob="*.txt")
        assert result["count"] == 1
        assert result["results"][0]["path"] == "notes/idea.txt"


class TestEvolutionConfigCapabilities:
    @pytest.mark.asyncio
    async def test_creates_dynamic_tool_config(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))
        (config_dir / "capabilities.yaml").write_text("capabilities: []\n", encoding="utf-8")
        (config_dir / "agents.yaml").write_text(
            yaml.dump({"agents": [{"name": "assistant", "tools": []}]}),
            encoding="utf-8",
        )

        tool = CreateDynamicToolConfigCapability()
        result = await tool.execute(
            name="idea_formatter",
            description="Format raw ideas into a concise brief",
            mode="template",
            config={"template": "Brief: {idea}"},
            attach_to_agents=["assistant"],
        )

        assert result["success"] is True
        assert result["requires_reload"] is True
        capabilities = yaml.safe_load((config_dir / "capabilities.yaml").read_text())
        agents = yaml.safe_load((config_dir / "agents.yaml").read_text())
        assert capabilities["capabilities"][0]["name"] == "idea_formatter"
        assert capabilities["capabilities"][0]["type"] == "dynamic"
        assert "idea_formatter" in agents["agents"][0]["tools"]

    @pytest.mark.asyncio
    async def test_creates_agent_config_and_attaches_to_assistant(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setenv("AGENTIC_CONFIG_DIR", str(config_dir))
        (config_dir / "agents.yaml").write_text(
            yaml.dump({"agents": [{"name": "assistant", "tools": []}]}),
            encoding="utf-8",
        )

        tool = CreateAgentConfigCapability()
        result = await tool.execute(
            name="researcher",
            description="Research Agent",
            system_prompt="You research requirements and return concise notes.",
            tools=["web_fetch", "file_search"],
            input_schema={
                "type": "object",
                "properties": {"request": {"type": "string"}},
                "required": ["request"],
            },
        )

        assert result["success"] is True
        assert result["attached_to_assistant"] is True
        agents = yaml.safe_load((config_dir / "agents.yaml").read_text())
        names = [item["name"] for item in agents["agents"]]
        assistant = next(item for item in agents["agents"] if item["name"] == "assistant")
        assert "researcher" in names
        assert "researcher" in assistant["tools"]


class TestPersonaEvolutionCapabilities:
    @pytest.mark.asyncio
    async def test_persona_evolution_tools_create_pending_and_require_approval(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERSONA_STORE_FILE", str(tmp_path / "personas.json"))

        read_tool = ReadPersonaDefinitionCapability()
        listed = await read_tool.execute()
        assert listed["base_persona_id"] == "base-assistant"
        persona_id = listed["personas"][0]["id"]

        feedback_tool = RecordPersonaFeedbackCapability()
        feedback = await feedback_tool.execute(
            persona_id=persona_id,
            feedback="回答过于啰嗦，需要更短。",
            source="feedback",
            session_id="s-tool",
        )
        assert feedback["success"] is True

        proposal_tool = GeneratePersonaPatchProposalCapability()
        proposal = await proposal_tool.execute(
            persona_id=persona_id,
            proposal_text="缩短回答",
            proposed_patch={"style_rules": ["回答更短"]},
            summary="增加简洁规则",
        )
        assert proposal["success"] is True
        assert proposal["proposal"]["status"] == "pending"

        apply_tool = ApplyConfirmedPersonaPatchCapability()
        denied = await apply_tool.execute(
            proposal_id=proposal["proposal"]["id"],
            reviewer="admin",
            admin_approved=False,
        )
        assert denied["permission_denied"] is True

        approved = await apply_tool.execute(
            proposal_id=proposal["proposal"]["id"],
            reviewer="admin",
            admin_approved=True,
        )
        assert approved["success"] is True
        assert approved["persona"]["version"] == 2

        history = await ListPersonaPatchHistoryCapability().execute(persona_id=persona_id)
        assert history["proposals"][0]["status"] == "approved"
        assert history["feedback"][0]["session_id"] == "s-tool"

    @pytest.mark.asyncio
    async def test_apply_persona_patch_requires_admin_token_when_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERSONA_STORE_FILE", str(tmp_path / "personas.json"))
        monkeypatch.setenv("PERSONA_ADMIN_TOKEN", "secret-token")
        persona_id = (await ReadPersonaDefinitionCapability().execute())["personas"][0]["id"]
        proposal = await GeneratePersonaPatchProposalCapability().execute(
            persona_id=persona_id,
            proposal_text="token protected",
            proposed_patch={"behavior_rules": ["需要 token 才能应用"]},
        )

        tool = ApplyConfirmedPersonaPatchCapability()
        denied = await tool.execute(
            proposal_id=proposal["proposal"]["id"],
            reviewer="admin",
            admin_approved=True,
            admin_token="wrong",
        )
        assert denied["permission_denied"] is True

        allowed = await tool.execute(
            proposal_id=proposal["proposal"]["id"],
            reviewer="admin",
            admin_approved=True,
            admin_token="secret-token",
        )
        assert allowed["success"] is True

    @pytest.mark.asyncio
    async def test_persona_management_tools_crud_and_bindings_are_guarded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PERSONA_STORE_FILE", str(tmp_path / "personas.json"))

        definition_tool = ManagePersonaDefinitionCapability()
        listed = await definition_tool.execute(operation="list")
        assert listed["base_persona_id"] == "base-assistant"

        denied = await definition_tool.execute(
            operation="create",
            payload={"name": "猫娘", "persona_prompt": "轻微猫娘语气"},
        )
        assert denied["permission_denied"] is True

        created = await definition_tool.execute(
            operation="create",
            payload={"name": "猫娘", "persona_prompt": "轻微猫娘语气"},
            reviewer="admin",
            admin_approved=True,
        )
        assert created["success"] is True
        persona_id = created["persona"]["id"]

        binding_tool = ManagePersonaBindingCapability()
        bound = await binding_tool.execute(
            operation="bind_agent",
            agent_name="assistant",
            persona_id=persona_id,
            reviewer="admin",
            admin_approved=True,
        )
        assert bound["binding"]["persona_id"] == persona_id

        resolved = await binding_tool.execute(operation="resolve", agent_name="assistant")
        assert resolved["persona"]["id"] == persona_id

        unbound = await binding_tool.execute(
            operation="unbind_agent",
            agent_name="assistant",
            reviewer="admin",
            admin_approved=True,
        )
        assert unbound["binding"]["removed"] is True


class TestWebFetchCapability:
    @pytest.mark.asyncio
    async def test_fetches_and_strips_html(self):
        body = b"<html><title>Example</title><body><h1>Hello</h1><script>x</script></body></html>"
        tool = WebFetchCapability()
        with (
            patch("socket.getaddrinfo", return_value=[PUBLIC_ADDR]),
            patch("urllib.request.OpenerDirector.open", return_value=FakeResponse(body)),
        ):
            result = await tool.execute(url="https://example.com/page")
        assert result["title"] == "Example"
        assert "Hello" in result["text"]
        assert "script" not in result["text"].lower()

    @pytest.mark.asyncio
    async def test_rejects_invalid_url(self):
        tool = WebFetchCapability()
        result = await tool.execute(url="file:///etc/passwd")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_blocks_private_network_targets_before_request(self):
        tool = WebFetchCapability()
        with patch("urllib.request.OpenerDirector.open") as opener_open:
            result = await tool.execute(url="http://127.0.0.1:8001/internal")

        assert "error" in result
        assert "not allowed" in result["error"]
        opener_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_does_not_block_event_loop(self):
        tool = WebFetchCapability()

        def slow_open(*args, **kwargs):
            time.sleep(0.2)
            return FakeResponse(b"<html><title>OK</title><body>done</body></html>")

        with (
            patch("socket.getaddrinfo", return_value=[PUBLIC_ADDR]),
            patch("urllib.request.OpenerDirector.open", side_effect=slow_open),
        ):
            started = time.monotonic()
            first, second = await asyncio.gather(
                tool.execute(url="https://example.com/one"),
                tool.execute(url="https://example.com/two"),
            )
            elapsed = time.monotonic() - started

        assert first["title"] == "OK"
        assert second["title"] == "OK"
        assert elapsed < 0.35, f"expected non-blocking fetches, got {elapsed:.3f}s"


class TestWebSearchCapability:
    @pytest.mark.asyncio
    async def test_search_parses_results(self):
        html = b"""
        <div class="result">
          <h2 class="result__title">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">Example <b>Doc</b></a>
          </h2>
          <a class="result__snippet">A useful result snippet.</a>
        </div></div>
        """
        tool = WebSearchCapability()
        with (
            patch("socket.getaddrinfo", return_value=[PUBLIC_ADDR]),
            patch("urllib.request.OpenerDirector.open", return_value=FakeResponse(html)),
        ):
            result = await tool.execute(query="example doc")

        assert result["count"] == 1
        assert result["provider"] == "duckduckgo"
        assert result["results"][0]["title"] == "Example Doc"
        assert result["results"][0]["url"] == "https://example.com/doc"
        assert result["results"][0]["snippet"] == "A useful result snippet."

    @pytest.mark.asyncio
    async def test_search_default_provider_uses_duckduckgo(self):
        html = b'<a class="result__a" href="https://example.com/">Example</a>'
        opened_urls: list[str] = []

        def fake_open(request, timeout=0):
            opened_urls.append(request.full_url)
            return FakeResponse(html)

        tool = WebSearchCapability()
        with (
            patch.object(tool, "_load_tool_config", return_value={}),
            patch("socket.getaddrinfo", return_value=[PUBLIC_ADDR]),
            patch("urllib.request.OpenerDirector.open", side_effect=fake_open),
        ):
            result = await tool.execute(query="example")

        assert result["provider"] == "duckduckgo"
        assert opened_urls
        assert opened_urls[0].startswith("https://duckduckgo.com/html/")

    @pytest.mark.asyncio
    async def test_search_explicit_brave_provider_still_used(self):
        tool = WebSearchCapability()

        with patch.object(tool, "_load_tool_config", return_value={"provider": "brave"}):
            result = await tool.execute(query="example")

        assert result["error"] == "web_search provider 'brave' requires api_key"

    @pytest.mark.asyncio
    async def test_search_requires_query(self):
        tool = WebSearchCapability()
        result = await tool.execute(query="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_blocks_private_custom_endpoint_before_request(self):
        tool = WebSearchCapability()
        with patch("urllib.request.OpenerDirector.open") as opener_open:
            result = await tool.execute(
                query="agent",
                provider="duckduckgo",
                base_url="http://10.0.0.1/search",
            )

        assert "error" in result
        assert "not allowed" in result["error"]
        opener_open.assert_not_called()


@pytest.mark.asyncio
async def test_common_tools_register_in_capability_registry():
    registry = CapabilityRegistry()
    tools = [
        CalculatorCapability(),
        DateTimeCapability(),
        FileSearchCapability(),
        CreateDynamicToolConfigCapability(),
        CreateAgentConfigCapability(),
        JsonToolCapability(),
        TextProcessorCapability(),
        WebFetchCapability(),
        WebSearchCapability(),
    ]
    for tool in tools:
        registry.register_native(tool)

    assert set(registry.list_names()) == {
        "calculator",
        "datetime_tool",
        "file_search",
        "create_dynamic_tool_config",
        "create_agent_config",
        "json_tool",
        "text_processor",
        "web_fetch",
        "web_search",
    }

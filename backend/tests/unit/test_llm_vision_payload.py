"""Unit tests for LLM vision payload conversion (B1 Plan 3 P3 Task 26).

Image attachments take a separate path from the system-reminder route used
for text/PDF: each provider client must translate a neutral
``[{"type": "text", "text": ...}, {"type": "image", "mime_type": ..., "data": ...}]``
content block into its provider-specific multimodal format.

These tests exercise only the message conversion helpers (`_convert_messages`
on OpenAIClient, the inline branch in AnthropicClient.chat) without dialing
out to any HTTP endpoint.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

# Same convention as the other unit tests: prepend ``backend/src``.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm.openai_client import OpenAIClient  # noqa: E402
from core.llm.anthropic_client import AnthropicClient  # noqa: E402


PNG_BYTES = b"\x89PNG\r\n\x1a\n"  # 8-byte minimal PNG magic prefix
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")


def _user_msg_with_image(text: str = "看这张图") -> dict:
    """Neutral content shape produced by Agent._build_messages."""

    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image", "mime_type": "image/png", "data": PNG_B64},
        ],
    }


# =====================
# OpenAI image_url translation
# =====================


class TestOpenAIVisionConversion:
    def test_neutral_image_block_becomes_image_url_data_uri(self):
        msg = _user_msg_with_image()
        converted = OpenAIClient._convert_messages([msg])
        assert len(converted) == 1
        out = converted[0]
        assert out["role"] == "user"
        assert isinstance(out["content"], list)
        assert out["content"][0] == {"type": "text", "text": "看这张图"}
        image_block = out["content"][1]
        assert image_block["type"] == "image_url"
        assert image_block["image_url"]["url"] == f"data:image/png;base64,{PNG_B64}"

    def test_string_content_passes_through(self):
        plain = {"role": "user", "content": "hello"}
        converted = OpenAIClient._convert_messages([plain])
        assert converted[0]["content"] == "hello"

    def test_image_block_without_data_is_dropped(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "x"},
                {"type": "image", "mime_type": "image/png", "data": ""},
            ],
        }
        converted = OpenAIClient._convert_messages([msg])
        # Only the text part remains.
        assert converted[0]["content"] == [{"type": "text", "text": "x"}]


# =====================
# Anthropic image translation
# =====================


class TestAnthropicVisionConversion:
    def test_neutral_image_block_becomes_anthropic_image(self):
        msg = _user_msg_with_image("describe this")
        converted = AnthropicClient._convert_messages_for_api([msg])
        assert len(converted) == 1
        out = converted[0]
        assert out["role"] == "user"
        parts = out["content"]
        assert parts[0] == {"type": "text", "text": "describe this"}
        assert parts[1] == {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": PNG_B64,
            },
        }

    def test_image_block_with_url_falls_back_to_url_source(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "看链接"},
                {
                    "type": "image",
                    "mime_type": "image/png",
                    "url": "https://example.com/p.png",
                },
            ],
        }
        converted = AnthropicClient._convert_messages_for_api([msg])
        parts = converted[0]["content"]
        assert parts[1]["type"] == "image"
        assert parts[1]["source"]["type"] == "url"
        assert parts[1]["source"]["url"] == "https://example.com/p.png"

    def test_image_without_data_or_url_is_dropped(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "y"},
                {"type": "image", "mime_type": "image/png"},
            ],
        }
        converted = AnthropicClient._convert_messages_for_api([msg])
        assert converted[0]["content"] == [{"type": "text", "text": "y"}]


# =====================
# Agent._build_messages — attaches images to the last user turn
# =====================


class TestAgentBuildMessagesAttachesImages:
    def test_attachment_images_appended_as_multipart_content(self, monkeypatch):
        from core.agent.agent import Agent

        # Skip persona / workspace / memory branches — not under test.
        monkeypatch.setattr(
            "core.agent.agent.format_workspace_system_context",
            lambda prompt, **_: prompt,
        )
        monkeypatch.setattr(
            "core.agent.agent.format_untrusted_memory_context",
            lambda prompt, ctx: prompt,
        )
        monkeypatch.setattr(
            "core.agent.agent.get_effective_persona",
            lambda **_: None,
        )
        monkeypatch.setattr(
            "core.agent.agent.build_persona_prompt_block",
            lambda persona: "",
        )

        agent = Agent(
            name="visiontest",
            llm_client=None,  # unused — only _build_messages is exercised
            system_prompt="ROOT",
        )

        messages = agent._build_messages(
            {
                "message": "look at it",
                "attachment_images": [
                    {"mime_type": "image/png", "data": PNG_B64, "name": "a.png"}
                ],
            }
        )
        # Last message should be the user turn — verify it carries the image.
        last = messages[-1]
        assert last["role"] == "user"
        assert isinstance(last["content"], list)
        kinds = [part.get("type") for part in last["content"]]
        assert "text" in kinds
        assert "image" in kinds
        img = next(p for p in last["content"] if p["type"] == "image")
        assert img["mime_type"] == "image/png"
        assert img["data"] == PNG_B64

    def test_no_images_keeps_string_content(self, monkeypatch):
        from core.agent.agent import Agent

        monkeypatch.setattr(
            "core.agent.agent.format_workspace_system_context",
            lambda prompt, **_: prompt,
        )
        monkeypatch.setattr(
            "core.agent.agent.format_untrusted_memory_context",
            lambda prompt, ctx: prompt,
        )
        monkeypatch.setattr(
            "core.agent.agent.get_effective_persona",
            lambda **_: None,
        )
        monkeypatch.setattr(
            "core.agent.agent.build_persona_prompt_block",
            lambda persona: "",
        )

        agent = Agent(
            name="t",
            llm_client=None,
            system_prompt="ROOT",
        )
        messages = agent._build_messages({"message": "hi"})
        last = messages[-1]
        assert last["role"] == "user"
        assert last["content"] == "hi"

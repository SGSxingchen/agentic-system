"""配置系统补充测试

覆盖:
- ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN 环境变量
- 深度合并边界情况
- 配置模型验证
- 配置优先级链
"""
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import (
    _deep_merge,
    _apply_env_overrides,
    load_yaml_configs,
    load_system_config,
    SystemConfig,
    LLMConfig,
    MemoryConfig,
    BusConfig,
    ContextConfig,
    WorkflowConfig,
    AgentConfig,
)


# =====================
# Anthropic 环境变量测试
# =====================

class TestAnthropicEnvOverrides:

    def test_anthropic_auth_token(self, monkeypatch):
        """ANTHROPIC_AUTH_TOKEN 应覆盖 api_key"""
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ant-token-123")
        raw = {"llm": {"api_key": "old-key"}}
        result = _apply_env_overrides(raw)
        assert result["llm"]["api_key"] == "ant-token-123"

    def test_anthropic_base_url(self, monkeypatch):
        """ANTHROPIC_BASE_URL 应覆盖 base_url"""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8484/code")
        raw = {"llm": {"base_url": ""}}
        result = _apply_env_overrides(raw)
        assert result["llm"]["base_url"] == "http://127.0.0.1:8484/code"

    def test_llm_api_key_takes_priority(self, monkeypatch):
        """LLM_API_KEY 优先于 ANTHROPIC_AUTH_TOKEN"""
        monkeypatch.setenv("LLM_API_KEY", "primary-key")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secondary-key")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["llm"]["api_key"] == "primary-key"

    def test_llm_base_url_takes_priority(self, monkeypatch):
        """LLM_BASE_URL 优先于 ANTHROPIC_BASE_URL"""
        monkeypatch.setenv("LLM_BASE_URL", "http://primary/v1")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://secondary/v1")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["llm"]["base_url"] == "http://primary/v1"

    def test_anthropic_token_alone(self, monkeypatch):
        """只设置 ANTHROPIC_AUTH_TOKEN，不设置 LLM_API_KEY"""
        # 确保 LLM_API_KEY 不存在
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "only-ant-token")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["llm"]["api_key"] == "only-ant-token"

    def test_anthropic_base_url_alone(self, monkeypatch):
        """只设置 ANTHROPIC_BASE_URL，不设置 LLM_BASE_URL"""
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://local:8484/code")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["llm"]["base_url"] == "http://local:8484/code"

    def test_load_system_config_with_anthropic_env(self, tmp_path, monkeypatch):
        """完整流程: 环境变量 → load_system_config"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ant-key-final")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8484/code")

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"provider": "openai", "model": "claude-sonnet-4"},
        }))
        config = load_system_config(config_path)
        assert config.llm.api_key == "ant-key-final"
        assert config.llm.base_url == "http://127.0.0.1:8484/code"


# =====================
# 深度合并边界情况
# =====================

class TestDeepMergeEdgeCases:

    def test_three_level_nested(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"] == 99
        assert result["a"]["b"]["d"] == 2

    def test_override_dict_with_non_dict(self):
        base = {"a": {"nested": True}}
        override = {"a": "replaced"}
        result = _deep_merge(base, override)
        assert result["a"] == "replaced"

    def test_merge_lists_replaced(self):
        """列表不合并，而是整体替换"""
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = _deep_merge(base, override)
        assert result["items"] == [4, 5]

    def test_none_value_override(self):
        base = {"a": 1}
        override = {"a": None}
        result = _deep_merge(base, override)
        assert result["a"] is None

    def test_both_empty(self):
        assert _deep_merge({}, {}) == {}


# =====================
# Pydantic 模型验证
# =====================

class TestConfigModels:

    def test_llm_config_defaults(self):
        config = LLMConfig()
        assert config.provider == "openai"
        assert config.api_key == ""
        assert config.model == "gpt-3.5-turbo"
        assert config.base_url == ""
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_llm_config_custom(self):
        config = LLMConfig(
            provider="anthropic",
            api_key="sk-ant-123",
            model="claude-3-opus",
            base_url="http://proxy:8080",
            temperature=0.3,
            max_tokens=8192,
        )
        assert config.provider == "anthropic"
        assert config.max_tokens == 8192

    def test_memory_config_defaults(self):
        config = MemoryConfig()
        assert config.backend == "memory"

    def test_bus_config_defaults(self):
        config = BusConfig()
        assert config.queue_size == 1000
        assert config.history_size == 500

    def test_system_config_nested_defaults(self):
        config = SystemConfig()
        assert config.llm.provider == "openai"
        assert config.memory.backend == "memory"
        assert config.bus.queue_size == 1000
        assert config.workflow.max_iterations == 10

    def test_agent_config_required_name(self):
        with pytest.raises(Exception):
            AgentConfig()  # name is required

    def test_agent_config_with_name(self):
        config = AgentConfig(name="test_agent")
        assert config.name == "test_agent"
        assert config.type == "builtin"
        assert config.capabilities == []

    def test_system_config_with_agents(self):
        config = SystemConfig(agents=[
            AgentConfig(name="planner", capabilities=["planning"]),
            AgentConfig(name="coder", capabilities=["coding"]),
        ])
        assert len(config.agents) == 2
        assert config.agents[0].name == "planner"


# =====================
# YAML 配置加载边界
# =====================

class TestYamlConfigsEdgeCases:

    def test_malformed_yaml(self, tmp_path):
        """语法错误的 YAML 文件"""
        (tmp_path / "bad.yaml").write_text("key: [invalid yaml\n")
        with pytest.raises(Exception):
            load_yaml_configs(config_dir=tmp_path)

    def test_non_dict_yaml(self, tmp_path):
        """YAML 顶层不是字典"""
        (tmp_path / "list.yaml").write_text(yaml.dump(["a", "b", "c"]))
        # 根据实现，可能会被跳过或报错
        result = load_yaml_configs(config_dir=tmp_path)
        assert isinstance(result, dict)

    def test_multiple_system_fields(self, tmp_path):
        """system.yaml 包含多个顶层字段"""
        (tmp_path / "system.yaml").write_text(yaml.dump({
            "llm": {"model": "gpt-4"},
            "bus": {"queue_size": 2000},
            "memory": {"backend": "chroma"},
        }))
        result = load_yaml_configs(config_dir=tmp_path)
        assert result["llm"]["model"] == "gpt-4"
        assert result["bus"]["queue_size"] == 2000
        assert result["memory"]["backend"] == "chroma"

    def test_load_system_config_empty_file(self, tmp_path):
        """空 YAML 文件返回默认配置"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")
        config = load_system_config(config_path)
        assert config.llm.provider == "openai"

    def test_load_system_config_extra_fields(self, tmp_path):
        """含额外字段的 YAML 不影响已知字段"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"model": "gpt-4"},
            "unknown_section": {"foo": "bar"},
        }))
        config = load_system_config(config_path)
        assert config.llm.model == "gpt-4"


# =====================
# 环境变量集成完整链
# =====================

class TestEnvOverrideIntegration:

    def test_all_env_vars_at_once(self, monkeypatch):
        """同时设置所有环境变量"""
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("LLM_API_KEY", "key-123")
        monkeypatch.setenv("LLM_MODEL", "claude-3")
        monkeypatch.setenv("LLM_BASE_URL", "http://custom:8080")
        monkeypatch.setenv("MEMORY_BACKEND", "chroma")
        monkeypatch.setenv("MEMORY_PERSIST_DIR", "/tmp/data")
        monkeypatch.setenv("BUS_QUEUE_SIZE", "5000")
        monkeypatch.setenv("BUS_HISTORY_SIZE", "2000")

        raw = {}
        result = _apply_env_overrides(raw)

        assert result["llm"]["provider"] == "anthropic"
        assert result["llm"]["api_key"] == "key-123"
        assert result["llm"]["model"] == "claude-3"
        assert result["llm"]["base_url"] == "http://custom:8080"
        assert result["memory"]["backend"] == "chroma"
        assert result["memory"]["persist_dir"] == "/tmp/data"
        assert result["bus"]["queue_size"] == 5000
        assert result["bus"]["history_size"] == 2000

    def test_env_overrides_existing_values(self, monkeypatch):
        """环境变量覆盖已有的配置值"""
        monkeypatch.setenv("LLM_MODEL", "gpt-4-turbo")
        raw = {"llm": {"model": "gpt-3.5-turbo", "provider": "openai"}}
        result = _apply_env_overrides(raw)
        assert result["llm"]["model"] == "gpt-4-turbo"
        assert result["llm"]["provider"] == "openai"  # 未设置环境变量，保留原值

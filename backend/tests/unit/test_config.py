"""配置加载 - 单元测试

测试 load_config(), load_yaml_configs(), load_system_config() 等。
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import (
    load_config,
    load_yaml_configs,
    load_system_config,
    SystemConfig,
    LLMConfig,
    _deep_merge,
    _apply_env_overrides,
)


# ─── _deep_merge ──────────────────────────────────────────


class TestDeepMerge:
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"llm": {"provider": "openai", "model": "gpt-3.5"}}
        override = {"llm": {"model": "gpt-4"}}
        result = _deep_merge(base, override)
        assert result == {"llm": {"provider": "openai", "model": "gpt-4"}}

    def test_override_non_dict_with_dict(self):
        base = {"a": 1}
        override = {"a": {"nested": True}}
        result = _deep_merge(base, override)
        assert result == {"a": {"nested": True}}

    def test_empty_base(self):
        result = _deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_empty_override(self):
        result = _deep_merge({"a": 1}, {})
        assert result == {"a": 1}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        _deep_merge(base, {"b": 2})
        assert base == {"a": 1}


# ─── _apply_env_overrides ─────────────────────────────────


class TestEnvOverrides:
    def test_llm_provider_override(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        raw = {"llm": {"provider": "openai"}}
        result = _apply_env_overrides(raw)
        assert result["llm"]["provider"] == "anthropic"

    def test_llm_api_key_override(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["llm"]["api_key"] == "sk-test-key"

    def test_llm_model_override(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4")
        raw = {"llm": {"model": "gpt-3.5"}}
        result = _apply_env_overrides(raw)
        assert result["llm"]["model"] == "gpt-4"

    def test_bus_queue_size_override(self, monkeypatch):
        monkeypatch.setenv("BUS_QUEUE_SIZE", "2000")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["bus"]["queue_size"] == 2000

    def test_memory_backend_override(self, monkeypatch):
        monkeypatch.setenv("MEMORY_BACKEND", "chroma")
        raw = {}
        result = _apply_env_overrides(raw)
        assert result["memory"]["backend"] == "chroma"

    def test_no_env_vars(self):
        """没有环境变量时不影响配置"""
        raw = {"llm": {"provider": "openai"}}
        # 确保相关环境变量不存在
        for key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL",
                     "MEMORY_BACKEND", "MEMORY_PERSIST_DIR",
                     "BUS_QUEUE_SIZE", "BUS_HISTORY_SIZE"):
            os.environ.pop(key, None)
        result = _apply_env_overrides(raw)
        assert result["llm"]["provider"] == "openai"


# ─── load_yaml_configs ────────────────────────────────────


class TestLoadYamlConfigs:
    def test_loads_system_yaml(self, tmp_path):
        """system.yaml 的内容直接合并到顶层"""
        (tmp_path / "system.yaml").write_text(yaml.dump({
            "llm": {"provider": "openai", "model": "gpt-4"},
            "bus": {"queue_size": 500},
        }))
        result = load_yaml_configs(config_dir=tmp_path)
        assert result["llm"]["provider"] == "openai"
        assert result["llm"]["model"] == "gpt-4"
        assert result["bus"]["queue_size"] == 500

    def test_loads_agents_yaml(self, tmp_path):
        """agents.yaml 用 agents 键合并"""
        agents_data = {"agents": [
            {"name": "planner", "type": "builtin", "capabilities": ["planning"]},
        ]}
        (tmp_path / "agents.yaml").write_text(yaml.dump(agents_data))
        result = load_yaml_configs(config_dir=tmp_path)
        assert "agents" in result
        assert len(result["agents"]) == 1
        assert result["agents"][0]["name"] == "planner"

    def test_loads_multiple_files(self, tmp_path):
        """多个 YAML 文件正确合并"""
        (tmp_path / "system.yaml").write_text(yaml.dump({
            "llm": {"provider": "openai"},
        }))
        (tmp_path / "agents.yaml").write_text(yaml.dump({
            "agents": [{"name": "coder"}],
        }))
        (tmp_path / "pipelines.yaml").write_text(yaml.dump({
            "pipelines": {"default": {"mode": "sequential"}},
        }))
        result = load_yaml_configs(config_dir=tmp_path)
        assert "llm" in result
        assert "agents" in result
        assert "pipelines" in result

    def test_empty_directory(self, tmp_path):
        """空目录返回空 dict"""
        result = load_yaml_configs(config_dir=tmp_path)
        assert result == {}

    def test_nonexistent_directory(self, tmp_path):
        """不存在的目录返回空 dict"""
        result = load_yaml_configs(config_dir=tmp_path / "nonexistent")
        assert result == {}

    def test_empty_yaml_file_skipped(self, tmp_path):
        """空 YAML 文件被跳过"""
        (tmp_path / "empty.yaml").write_text("")
        result = load_yaml_configs(config_dir=tmp_path)
        assert result == {}

    def test_system_yaml_deep_merges(self, tmp_path):
        """system.yaml 的内容能深度合并"""
        (tmp_path / "system.yaml").write_text(yaml.dump({
            "llm": {"provider": "openai"},
            "memory": {"backend": "memory"},
        }))
        result = load_yaml_configs(config_dir=tmp_path)
        assert result["llm"]["provider"] == "openai"
        assert result["memory"]["backend"] == "memory"

    def test_capabilities_yaml(self, tmp_path):
        """capabilities.yaml 正确加载"""
        caps_data = {"capabilities": [
            {"name": "code_parser", "type": "builtin"},
            {"name": "static_analyzer", "type": "builtin"},
        ]}
        (tmp_path / "capabilities.yaml").write_text(yaml.dump(caps_data))
        result = load_yaml_configs(config_dir=tmp_path)
        assert "capabilities" in result
        assert len(result["capabilities"]) == 2

    def test_triggers_yaml(self, tmp_path):
        """triggers.yaml 正确加载"""
        triggers_data = {"triggers": [
            {"name": "on_plan_complete", "event": "plan_completed", "agent": "coder"},
        ]}
        (tmp_path / "triggers.yaml").write_text(yaml.dump(triggers_data))
        result = load_yaml_configs(config_dir=tmp_path)
        assert "triggers" in result
        assert result["triggers"][0]["name"] == "on_plan_complete"

    def test_file_without_matching_key(self, tmp_path):
        """文件名与内容顶层键不匹配时，整个内容用文件名作键"""
        (tmp_path / "custom.yaml").write_text(yaml.dump({
            "setting_a": True,
            "setting_b": 42,
        }))
        result = load_yaml_configs(config_dir=tmp_path)
        assert "custom" in result
        assert result["custom"]["setting_a"] is True

    def test_default_config_dir(self):
        """使用默认 config_dir（项目根目录/config/）"""
        # 这个测试验证不传参数时不报错
        result = load_yaml_configs()
        # 如果项目有 config/ 目录就有内容，否则为空
        assert isinstance(result, dict)


# ─── load_system_config ───────────────────────────────────


class TestLoadSystemConfig:
    def test_default_values(self, tmp_path):
        """没有配置文件时使用默认值"""
        config_path = tmp_path / "config.yaml"
        # 不创建文件
        config = load_system_config(config_path)
        assert isinstance(config, SystemConfig)
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-3.5-turbo"
        assert config.memory.backend == "chroma"

    def test_custom_values(self, tmp_path):
        """自定义配置正确加载"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"provider": "anthropic", "model": "claude-3"},
            "bus": {"queue_size": 2000},
        }))
        config = load_system_config(config_path)
        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-3"
        assert config.bus.queue_size == 2000

    def test_partial_config(self, tmp_path):
        """部分配置 + 默认值补全"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"model": "gpt-4"},
        }))
        config = load_system_config(config_path)
        assert config.llm.model == "gpt-4"
        assert config.llm.provider == "openai"  # 默认值

    def test_env_override_applied(self, tmp_path, monkeypatch):
        """环境变量覆盖生效"""
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "llm": {"provider": "openai"},
        }))
        config = load_system_config(config_path)
        assert config.llm.provider == "anthropic"


# ─── load_config (backward compat) ───────────────────────


class TestLoadConfig:
    def test_returns_dict(self):
        """load_config() 返回 dict"""
        result = load_config()
        assert isinstance(result, dict)

    def test_has_llm_key(self):
        """返回结果至少包含 llm 配置"""
        result = load_config()
        assert "llm" in result

    def test_web_search_defaults_to_duckduckgo_without_user_config(self, tmp_path, monkeypatch):
        """无组件配置、无运行时配置、无环境变量时 Web Search 默认 DuckDuckGo。"""
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        missing_runtime = tmp_path / "missing-config.yaml"
        empty_config_dir = tmp_path / "empty-config"
        empty_config_dir.mkdir()

        result = load_config(config_path=missing_runtime, config_dir=empty_config_dir)

        assert result["tools"]["web_search"]["provider"] == "duckduckgo"

    def test_web_search_explicit_brave_config_still_wins(self, tmp_path, monkeypatch):
        """显式配置为 Brave 时保持 Brave，不被默认值覆盖。"""
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        runtime = tmp_path / "config.yaml"
        runtime.write_text(
            yaml.dump({"tools": {"web_search": {"provider": "brave"}}}),
            encoding="utf-8",
        )

        result = load_config(config_path=runtime, config_dir=tmp_path / "missing-config-dir")

        assert result["tools"]["web_search"]["provider"] == "brave"

    def test_web_search_explicit_brave_env_still_wins(self, tmp_path, monkeypatch):
        """显式环境变量配置为 Brave 时保持 Brave。"""
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "brave")

        result = load_config(config_path=tmp_path / "missing.yaml", config_dir=tmp_path / "missing-dir")

        assert result["tools"]["web_search"]["provider"] == "brave"

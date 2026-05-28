"""A23.2: token_budget 全局默认值 + Pydantic schema + main.py fallback。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import AgentDefaultsConfig, SystemConfig


class TestAgentDefaultsConfig:
    def test_default_token_budget_is_300k(self):
        defaults = AgentDefaultsConfig()
        assert defaults.token_budget == 300000

    def test_token_budget_can_be_overridden(self):
        defaults = AgentDefaultsConfig(token_budget=500000)
        assert defaults.token_budget == 500000

    def test_system_config_includes_agent_defaults(self):
        config = SystemConfig()
        assert isinstance(config.agent_defaults, AgentDefaultsConfig)
        assert config.agent_defaults.token_budget == 300000

    def test_system_config_loads_agent_defaults_from_dict(self):
        config = SystemConfig(agent_defaults={"token_budget": 800000})
        assert config.agent_defaults.token_budget == 800000


class TestTokenBudgetFallbackInAgentInstance:
    """main.py 应在 yaml 未配 token_budget 时回退到 system.yaml.agent_defaults。"""

    def _resolve(self, agent_def_token_budget, system_default=300000):
        """模拟 main.py 中创建 Agent 时解析 token_budget 的逻辑。"""
        from api import main as main_module

        return main_module._resolve_token_budget(agent_def_token_budget, system_default)

    def test_yaml_value_wins_when_present(self):
        assert self._resolve(500000) == 500000

    def test_falls_back_to_system_default_when_missing(self):
        assert self._resolve(None) == 300000

    def test_explicit_zero_falls_back_to_default(self):
        # token_budget=0 在 Agent 内部会被 normalize 成 None；fallback 应触发
        assert self._resolve(0) == 300000

    def test_custom_system_default(self):
        assert self._resolve(None, system_default=800000) == 800000

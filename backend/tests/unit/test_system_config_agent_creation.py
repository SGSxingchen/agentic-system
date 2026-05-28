"""Task 5 — A4 system.yaml escape hatch ``agent_creation.forbidden_tools``.

P1 / A4：删除 create_agent_config 对 HIGH_RISK_TOOLS 的硬拒绝后，仍要给
部署方一个 escape hatch 把特定工具锁死。本测试覆盖：

- 默认 forbidden_tools 为空（即"全放开"）
- yaml 里写 forbidden_tools 后能加载
- SystemConfig.agent_creation 字段类型正确
"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.config import AgentCreationConfig, SystemConfig, load_system_config


def test_agent_creation_default_empty():
    """默认 forbidden_tools 列表为空 — 不锁任何工具。"""
    cfg = SystemConfig()
    assert cfg.agent_creation.forbidden_tools == []


def test_agent_creation_loaded_from_yaml(tmp_path):
    """system.yaml 里写 forbidden_tools 能被 load_system_config 读取。"""
    yaml_file = tmp_path / "system.yaml"
    yaml_file.write_text(
        """
agent_creation:
  forbidden_tools:
    - bash
    - dispatch_agent
""",
        encoding="utf-8",
    )
    cfg = load_system_config(config_path=yaml_file)
    assert cfg.agent_creation.forbidden_tools == ["bash", "dispatch_agent"]


def test_agent_creation_config_is_pydantic_model():
    """AgentCreationConfig 必须是 BaseModel；用列表赋值能被构造。"""
    cfg = AgentCreationConfig(forbidden_tools=["write_file"])
    assert cfg.forbidden_tools == ["write_file"]

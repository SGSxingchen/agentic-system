"""Task 4 — Centralized HIGH_RISK_TOOLS / AGENT_MANAGEMENT_TOOLS constants.

R1 预处理：之前 HIGH_RISK_TOOLS 在 evolution_config.py 与 agent_management.py
两处独立定义，A4 改造时一处删掉另一处仍生效。本测试锁定 single source of
truth = ``core/capability/risk.py``。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.capability.risk import HIGH_RISK_TOOLS, AGENT_MANAGEMENT_TOOLS


def test_high_risk_tools_is_single_source_of_truth():
    """HIGH_RISK_TOOLS 必须包含历史定义里的全部工具。"""
    expected = {
        "bash",
        "write_file",
        "create_agent_config",
        "create_dynamic_tool_config",
        "dispatch_agent",
    }
    assert expected.issubset(set(HIGH_RISK_TOOLS))


def test_agent_management_tools_is_single_source():
    """AGENT_MANAGEMENT_TOOLS 必须列出 A10 后的 read/validate/update 系列。"""
    expected = {
        "read_agent_config",
        "validate_agent_config_patch",
        "update_agent_config",
    }
    assert expected.issubset(set(AGENT_MANAGEMENT_TOOLS))


def test_no_duplicate_high_risk_definitions():
    """grep 项目代码，HIGH_RISK_TOOLS = {...} 赋值必须只出现一次。"""
    src_root = Path(__file__).resolve().parents[2] / "src"
    pattern = re.compile(r"^HIGH_RISK_TOOLS\s*=\s*[\{f]")
    hits = []
    for py in src_root.rglob("*.py"):
        with py.open(encoding="utf-8") as f:
            for line in f:
                if pattern.match(line):
                    hits.append(str(py))
                    break
    assert len(hits) == 1, f"HIGH_RISK_TOOLS defined in multiple files: {hits}"
    assert hits[0].endswith("risk.py"), f"HIGH_RISK_TOOLS lives in {hits[0]}, expected risk.py"


def test_no_duplicate_agent_management_tools_definitions():
    src_root = Path(__file__).resolve().parents[2] / "src"
    pattern = re.compile(r"^AGENT_MANAGEMENT_TOOLS\s*=\s*[\{f]")
    hits = []
    for py in src_root.rglob("*.py"):
        with py.open(encoding="utf-8") as f:
            for line in f:
                if pattern.match(line):
                    hits.append(str(py))
                    break
    assert len(hits) == 1, f"AGENT_MANAGEMENT_TOOLS defined in multiple files: {hits}"
    assert hits[0].endswith("risk.py")

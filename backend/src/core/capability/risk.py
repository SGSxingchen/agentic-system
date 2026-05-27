"""High-risk capability identifiers used by capability gating logic.

Centralized definitions to avoid duplicate constants in tool files.
After A4/A10, these are advisory — actual gating moves to ``system.yaml``
``agent_creation.forbidden_tools`` and ``dispatch.max_depth`` knobs.

Single source of truth: do not redeclare these sets in capability tool
modules; ``import`` from here instead.
"""

from __future__ import annotations


HIGH_RISK_TOOLS = frozenset({
    "bash",
    "write_file",
    "create_agent_config",
    "create_dynamic_tool_config",
    "dispatch_agent",
})


AGENT_MANAGEMENT_TOOLS = frozenset({
    "read_agent_config",
    "validate_agent_config_patch",
    "propose_agent_config_patch",
    "apply_agent_config_patch",
})


__all__ = ["HIGH_RISK_TOOLS", "AGENT_MANAGEMENT_TOOLS"]

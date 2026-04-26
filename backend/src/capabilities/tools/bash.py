"""Shell capability guarded for trusted local development only."""

from __future__ import annotations

import asyncio
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema

from ._safety import ensure_shell_tool_enabled, resolve_workspace_cwd


class BashCapability(CapabilityBase):
    """Execute shell commands with opt-in and workspace restrictions."""

    _BLOCKED_PATTERNS = (
        "rm -rf /",
        "rm -rf *",
        "mkfs",
        "dd if=",
        ":(){",
        "shutdown",
        "reboot",
        "halt",
        "format ",
        "del /f /s /q",
        "rd /s /q",
    )

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command inside the workspace. Disabled by default and intended only for trusted local development."
        )

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds, defaults to 30.",
                        "default": 30,
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory inside the workspace.",
                    },
                },
                "required": ["command"],
            },
            returns="Shell stdout, stderr, and return code.",
        )

    async def execute(self, **kwargs: Any) -> Any:
        command = (kwargs.get("command", "") or "").strip()
        configured_timeout = 30
        try:
            from core.config import get_tool_runtime_config

            configured_timeout = float(
                get_tool_runtime_config("shell").get("timeout", 30)
            )
        except Exception:
            configured_timeout = 30

        timeout = float(kwargs.get("timeout", configured_timeout) or configured_timeout)
        cwd = kwargs.get("cwd")

        if not command:
            return {"error": "command is required"}

        try:
            ensure_shell_tool_enabled()
            resolved_cwd = resolve_workspace_cwd(cwd)
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Invalid shell configuration: {str(exc)}"}

        lowered = command.lower()
        for pattern in self._BLOCKED_PATTERNS:
            if pattern in lowered:
                return {"error": f"Command blocked for safety: contains '{pattern}'"}

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": process.returncode,
                "cwd": str(resolved_cwd),
            }
        except asyncio.TimeoutError:
            if process is not None:
                process.kill()
                await process.communicate()
            return {"error": f"Command timed out after {timeout} seconds"}
        except Exception as exc:
            return {"error": f"Command execution failed: {str(exc)}"}

"""Shell capability guarded for trusted local development only."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

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
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 Shell 命令（在工作区内运行）",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "超时时间秒数，默认 30",
                        "default": 30,
                    },
                    "cwd": {
                        "type": "string",
                        "description": "可选工作目录，必须位于工作区内",
                    },
                },
                "required": ["command"],
            },
            returns="Shell stdout、stderr 和返回码",
            is_read_only=False,
            is_concurrency_safe=False,
            max_result_size=16000,
        )

    def check_permissions(self, **kwargs: Any) -> dict[str, Any]:
        """Reject obviously destructive commands and shell-disabled environments.

        Runs before execute() so the agent loop can deny without forking a process.
        execute() retains the same checks as defensive backup.
        """
        command = (kwargs.get("command", "") or "").strip()
        if not command:
            return {"decision": "deny", "reason": "command is required"}

        try:
            ensure_shell_tool_enabled()
        except PermissionError as exc:
            return {"decision": "deny", "reason": str(exc)}

        lowered = command.lower()
        for pattern in self._BLOCKED_PATTERNS:
            if pattern in lowered:
                return {
                    "decision": "deny",
                    "reason": f"Command blocked for safety: contains '{pattern}'",
                }

        return {"decision": "allow"}

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

        command_to_run = "cd" if os.name == "nt" and command.casefold() == "pwd" else command
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_shell(
                command_to_run,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
                # POSIX 上独立会话 → 进程组，超时可整组回收子进程；Windows 不支持。
                start_new_session=(os.name != "nt"),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": process.returncode,
                "cwd": str(resolved_cwd),
            }
        except asyncio.TimeoutError:
            await self._terminate(process)
            return {"error": f"Command timed out after {timeout} seconds"}
        except Exception as exc:
            return {"error": f"Command execution failed: {str(exc)}"}

    @staticmethod
    async def _terminate(process: "asyncio.subprocess.Process | None") -> None:
        """超时后杀掉整棵进程树，并限时回收，避免 communicate() 永久挂起。"""
        if process is None:
            return
        try:
            if os.name != "nt":
                import signal

                # 杀整个进程组（含 shell 派生的子进程），而不仅是 shell 本身。
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass
        # 限时收尸：子进程若仍占着管道，communicate() 可能无限阻塞。
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
        except Exception:  # noqa: BLE001
            pass

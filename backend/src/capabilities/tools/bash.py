"""Bash 能力插件 — 执行 shell 命令（带安全限制）"""
import asyncio
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema


class BashCapability(CapabilityBase):
    """执行 shell 命令，带超时和安全限制"""

    # 禁止执行的危险命令前缀
    _BLOCKED_COMMANDS = [
        "rm -rf /",
        "mkfs",
        "dd if=",
        ":(){",
        "fork",
    ]

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "执行 shell 命令并返回输出。带 30 秒超时限制。"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "超时秒数，默认 30",
                        "default": 30,
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录（可选）",
                    },
                },
                "required": ["command"],
            },
            returns="命令输出（stdout + stderr）",
        )

    async def execute(self, **kwargs: Any) -> Any:
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", 30)
        cwd = kwargs.get("cwd", None)

        if not command:
            return {"error": "command is required"}

        # 安全检查
        for blocked in self._BLOCKED_COMMANDS:
            if blocked in command:
                return {"error": f"Command blocked for safety: contains '{blocked}'"}

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )

            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": process.returncode,
            }
        except asyncio.TimeoutError:
            process.kill()
            return {"error": f"Command timed out after {timeout} seconds"}
        except Exception as e:
            return {"error": f"Command execution failed: {str(e)}"}

"""Date and time capability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.capability.base import CapabilityBase, CapabilitySchema


class DateTimeCapability(CapabilityBase):
    """Return current date/time in a requested timezone."""

    @property
    def name(self) -> str:
        return "datetime_tool"

    @property
    def description(self) -> str:
        return "获取当前日期时间，支持 IANA 时区，例如 Asia/Shanghai、Asia/Singapore、UTC"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA 时区名，默认 Asia/Singapore",
                        "default": "Asia/Singapore",
                    },
                    "format": {
                        "type": "string",
                        "description": "返回格式: iso | human | timestamp",
                        "default": "iso",
                    },
                },
            },
            returns="当前时间信息",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=1000,
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        timezone_name = str(kwargs.get("timezone") or "Asia/Singapore")
        output_format = str(kwargs.get("format") or "iso")

        try:
            tz = timezone.utc if timezone_name.upper() == "UTC" else ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return {"error": f"unknown timezone: {timezone_name}"}

        now = datetime.now(tz)
        data: dict[str, Any] = {
            "timezone": timezone_name,
            "iso": now.isoformat(timespec="seconds"),
            "date": now.date().isoformat(),
            "time": now.time().isoformat(timespec="seconds"),
            "weekday": now.strftime("%A"),
            "unix_timestamp": int(now.timestamp()),
        }

        if output_format == "human":
            data["formatted"] = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        elif output_format == "timestamp":
            data["formatted"] = data["unix_timestamp"]
        else:
            data["formatted"] = data["iso"]

        return data

"""Read-only web fetch capability."""

from __future__ import annotations

import html
import re
import asyncio
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description

from ._web_safety import open_public_url, validate_public_http_url


class WebFetchCapability(CapabilityBase):
    """Fetch a public HTTP(S) URL and return a compact text preview."""

    _CONFIG_CACHE: dict[str, Any] = {"loaded_at": 0.0, "config": None}
    _CONFIG_CACHE_TTL = 5.0

    @property
    def name(self) -> str:
        return "web_fetch"

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
                    "url": {
                        "type": "string",
                        "description": "要读取的 http 或 https URL",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "超时时间秒数，默认 10",
                        "default": 10,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "返回正文最大字符数，默认 4000",
                        "default": 4000,
                    },
                },
                "required": ["url"],
            },
            returns="网页标题、正文预览、状态码和内容类型",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=16000,
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        url = str(kwargs.get("url", "")).strip()

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"error": "url must be a valid http(s) URL"}

        try:
            return await asyncio.to_thread(
                self._fetch_sync_with_config,
                url,
                kwargs.get("timeout"),
                kwargs.get("max_chars"),
            )
        except urllib.error.HTTPError as exc:
            return {"error": f"HTTP {exc.code}: {exc.reason}"}
        except urllib.error.URLError as exc:
            return {"error": f"request failed: {exc.reason}"}
        except PermissionError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"web_fetch failed: {str(exc)}"}

    @classmethod
    def _fetch_sync_with_config(
        cls,
        url: str,
        timeout_value: Any,
        max_chars_value: Any,
    ) -> dict[str, Any]:
        """Load runtime config and perform fetch off the event loop.

        ``get_tool_runtime_config`` can touch YAML/env state, so doing it before
        the first await would serialize otherwise concurrent ``execute`` calls.
        """

        config = cls._load_tool_config()
        timeout = float(timeout_value if timeout_value is not None else config.get("timeout", 10) or 10)
        max_chars = int(
            max_chars_value if max_chars_value is not None else config.get("max_chars", 4000) or 4000
        )
        return cls._fetch_sync(url, timeout, max_chars)

    @classmethod
    def _fetch_sync(
        cls,
        url: str,
        timeout: float,
        max_chars: int,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "agentic-system-web-fetch/1.0",
                "Accept": "text/html,text/plain,application/json,*/*;q=0.8",
            },
        )
        with open_public_url(request, timeout=timeout) as response:
            final_url = response.geturl()
            validate_public_http_url(final_url)
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(max(1024, min(max_chars * 4, 2_000_000)))
            charset = response.headers.get_content_charset() or "utf-8"
            decoded = raw.decode(charset, errors="replace")
            text = cls._html_to_text(decoded) if "html" in content_type.lower() else decoded
            text = text[: max(200, min(max_chars, 20000))]
            return {
                "url": final_url,
                "status": response.status,
                "content_type": content_type,
                "title": cls._extract_title(decoded),
                "text": text,
                "chars": len(text),
            }

    @staticmethod
    def _extract_title(content: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S)
        if not match:
            return ""
        return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())

    @staticmethod
    def _html_to_text(content: str) -> str:
        content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", content)
        content = re.sub(r"(?s)<[^>]+>", " ", content)
        content = html.unescape(content)
        return re.sub(r"\s+", " ", content).strip()

    @staticmethod
    def _load_tool_config() -> dict[str, Any]:
        now = time.monotonic()
        cached = WebFetchCapability._CONFIG_CACHE.get("config")
        loaded_at = float(WebFetchCapability._CONFIG_CACHE.get("loaded_at") or 0.0)
        if isinstance(cached, dict) and now - loaded_at < WebFetchCapability._CONFIG_CACHE_TTL:
            return dict(cached)

        try:
            from core.config import get_tool_runtime_config

            config = get_tool_runtime_config("web_fetch")
        except Exception:
            config = {}
        WebFetchCapability._CONFIG_CACHE = {"loaded_at": now, "config": dict(config)}
        return dict(config)


# Pre-warm runtime config at import time.  The config loader can touch YAML/env
# state; warming it before request handling keeps concurrent fetch calls from
# spending their first event-loop slice on synchronous config loading.
WebFetchCapability._load_tool_config()

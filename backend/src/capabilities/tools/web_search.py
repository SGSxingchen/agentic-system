"""Read-only web search capability."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from core.capability.base import CapabilityBase, CapabilitySchema


class WebSearchCapability(CapabilityBase):
    """Search the public web and return compact result snippets."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "搜索公开网页并返回标题、链接和摘要；适合查找最新资料，再配合 web_fetch 读取具体页面"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回结果数，默认 5，最大 10",
                        "default": 5,
                    },
                    "provider": {
                        "type": "string",
                        "description": "可选搜索提供方: duckduckgo | brave | serper，默认使用系统配置",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "超时时间秒数，默认 10",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            returns="搜索结果列表，每项包含 title、url、snippet、source",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        config = self._load_tool_config()
        query = str(kwargs.get("query") or "").strip()
        provider = str(kwargs.get("provider") or config.get("provider") or "duckduckgo").strip().lower()
        base_url = str(kwargs.get("base_url") or config.get("base_url") or "").strip()
        api_key = str(kwargs.get("api_key") or config.get("api_key") or "").strip()
        max_results = int(kwargs.get("max_results", config.get("max_results", 5)) or 5)
        timeout = float(kwargs.get("timeout", config.get("timeout", 10)) or 10)

        if not query:
            return {"error": "query is required"}

        max_results = max(1, min(max_results, 10))
        if provider == "brave":
            return self._search_brave(query, max_results, timeout, api_key, base_url)
        if provider == "serper":
            return self._search_serper(query, max_results, timeout, api_key, base_url)
        if provider not in {"duckduckgo", "duckduckgo_html"}:
            return {"error": "unsupported provider; expected duckduckgo, brave, or serper"}

        endpoint = base_url or "https://duckduckgo.com/html/"
        separator = "&" if "?" in endpoint else "?"
        search_url = f"{endpoint}{separator}q={quote_plus(query)}"
        request = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": "agentic-system-web-search/1.0",
                "Accept": "text/html,*/*;q=0.8",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=max(1, min(timeout, 30))) as response:
                raw = response.read(1_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                content = raw.decode(charset, errors="replace")
                results = self._parse_duckduckgo_html(content, max_results)
                return {
                    "query": query,
                    "provider": "duckduckgo",
                    "count": len(results),
                    "results": results,
                }
        except urllib.error.HTTPError as exc:
            return {"error": f"HTTP {exc.code}: {exc.reason}"}
        except urllib.error.URLError as exc:
            return {"error": f"request failed: {exc.reason}"}
        except Exception as exc:
            return {"error": f"web_search failed: {str(exc)}"}

    @classmethod
    def _parse_duckduckgo_html(cls, content: str, max_results: int) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        blocks = re.findall(
            r'(?is)<div[^>]+class="[^"]*\bresult\b[^"]*"[^>]*>(.*?)</div>\s*</div>',
            content,
        )
        if not blocks:
            blocks = re.findall(
                r'(?is)<a[^>]+class="[^"]*\bresult__a\b[^"]*"[^>]*>.*?(?=<a[^>]+class="[^"]*\bresult__a\b|$)',
                content,
            )

        for block in blocks:
            link_match = re.search(
                r'(?is)<a[^>]+class="[^"]*\bresult__a\b[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                block,
            )
            if not link_match:
                continue

            url = cls._clean_result_url(html.unescape(link_match.group(1)))
            title = cls._strip_html(link_match.group(2))
            snippet_match = re.search(
                r'(?is)<a[^>]+class="[^"]*\bresult__snippet\b[^"]*"[^>]*>(.*?)</a>',
                block,
            ) or re.search(
                r'(?is)<div[^>]+class="[^"]*\bresult__snippet\b[^"]*"[^>]*>(.*?)</div>',
                block,
            )
            snippet = cls._strip_html(snippet_match.group(1)) if snippet_match else ""

            if title and url and urlparse(url).scheme in {"http", "https"}:
                results.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "source": urlparse(url).netloc,
                    }
                )

            if len(results) >= max_results:
                break

        return results

    @staticmethod
    def _clean_result_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                return unquote(target)
        if url.startswith("//"):
            return f"https:{url}"
        return url

    @staticmethod
    def _strip_html(content: str) -> str:
        content = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", content)
        content = re.sub(r"(?s)<[^>]+>", " ", content)
        content = html.unescape(content)
        return re.sub(r"\s+", " ", content).strip()

    @staticmethod
    def _load_tool_config() -> Dict[str, Any]:
        try:
            from core.config import get_tool_runtime_config

            return get_tool_runtime_config("web_search")
        except Exception:
            return {}

    def _search_brave(
        self,
        query: str,
        max_results: int,
        timeout: float,
        api_key: str,
        base_url: str,
    ) -> Dict[str, Any]:
        if not api_key:
            return {"error": "web_search provider 'brave' requires api_key"}

        endpoint = base_url or "https://api.search.brave.com/res/v1/web/search"
        separator = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{separator}q={quote_plus(query)}&count={max_results}"
        data = self._request_json(
            url=url,
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
        )
        if "error" in data:
            return data

        raw_results = data.get("web", {}).get("results", [])[:max_results]
        results = [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": self._strip_html(str(item.get("description") or "")),
                "source": urlparse(str(item.get("url") or "")).netloc,
            }
            for item in raw_results
            if item.get("url")
        ]
        return {"query": query, "provider": "brave", "count": len(results), "results": results}

    def _search_serper(
        self,
        query: str,
        max_results: int,
        timeout: float,
        api_key: str,
        base_url: str,
    ) -> Dict[str, Any]:
        if not api_key:
            return {"error": "web_search provider 'serper' requires api_key"}

        endpoint = base_url or "https://google.serper.dev/search"
        payload = json.dumps({"q": query, "num": max_results}).encode("utf-8")
        data = self._request_json(
            url=endpoint,
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": api_key,
            },
            payload=payload,
        )
        if "error" in data:
            return data

        raw_results = data.get("organic", [])[:max_results]
        results = [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("link") or ""),
                "snippet": self._strip_html(str(item.get("snippet") or "")),
                "source": urlparse(str(item.get("link") or "")).netloc,
            }
            for item in raw_results
            if item.get("link")
        ]
        return {"query": query, "provider": "serper", "count": len(results), "results": results}

    @staticmethod
    def _request_json(
        *,
        url: str,
        timeout: float,
        headers: Dict[str, str],
        payload: bytes | None = None,
    ) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "User-Agent": "agentic-system-web-search/1.0",
                **headers,
            },
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=max(1, min(timeout, 30))) as response:
                raw = response.read(1_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(raw.decode(charset, errors="replace"))
        except urllib.error.HTTPError as exc:
            return {"error": f"HTTP {exc.code}: {exc.reason}"}
        except urllib.error.URLError as exc:
            return {"error": f"request failed: {exc.reason}"}
        except Exception as exc:
            return {"error": f"web_search failed: {str(exc)}"}

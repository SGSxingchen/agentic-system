"""Phase C 支柱 8：`<task-notification>` XML 格式化

子 Agent 完成时，dispatch_agent 把结果以这里的 XML 格式追加到父 Agent 的 messages
（user 角色），父 Agent 在下一轮 LLM 采样时看到。
格式参考 Claude Code coordinator/coordinatorMode.ts 的 task-notification 块。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


_RESULT_MAX_CHARS = 2000


def _safe_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _truncate(text: str, limit: int = _RESULT_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, original {len(text)} chars]"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_task_notification(payload: Dict[str, Any]) -> str:
    """把 dispatch_agent 完成事件序列化为 `<task-notification>` XML 块。

    Recognized keys (其余忽略):
        task_id: str
        subagent_type: str
        status: "completed" | "failed" | "killed"
        summary: str (optional, 默认按 status 自动生成)
        result: Any (会 JSON 化并截断)
        error: str (status != completed 时附带)
        usage: Dict (含 input_tokens / output_tokens / total_tokens / tool_uses / duration_ms)
    """
    task_id = str(payload.get("task_id") or "")
    subagent_type = str(payload.get("subagent_type") or "")
    status = str(payload.get("status") or "completed")
    summary = str(
        payload.get("summary")
        or _default_summary(status, subagent_type, task_id)
    )

    result_raw = _safe_json(payload.get("result"))
    result_block = _xml_escape(_truncate(result_raw)) if result_raw else ""

    error = str(payload.get("error") or "")
    error_block = (
        f"  <error>{_xml_escape(_truncate(error, 1000))}</error>\n"
        if error
        else ""
    )

    usage: Dict[str, Any] = payload.get("usage") or {}

    def _u(key: str) -> int:
        try:
            return int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return (
        "<task-notification>\n"
        f"  <task-id>{_xml_escape(task_id)}</task-id>\n"
        f"  <subagent-type>{_xml_escape(subagent_type)}</subagent-type>\n"
        f"  <status>{_xml_escape(status)}</status>\n"
        f"  <summary>{_xml_escape(summary)}</summary>\n"
        f"  <result>{result_block}</result>\n"
        f"{error_block}"
        "  <usage>\n"
        f"    <total_tokens>{_u('total_tokens')}</total_tokens>\n"
        f"    <input_tokens>{_u('input_tokens')}</input_tokens>\n"
        f"    <output_tokens>{_u('output_tokens')}</output_tokens>\n"
        f"    <tool_uses>{_u('tool_uses')}</tool_uses>\n"
        f"    <duration_ms>{_u('duration_ms')}</duration_ms>\n"
        "  </usage>\n"
        "</task-notification>"
    )


def _default_summary(status: str, subagent_type: str, task_id: str) -> str:
    short = task_id[:8] if task_id else ""
    name = subagent_type or "subagent"
    if status == "completed":
        return f"Sub-agent '{name}' (task {short}) completed."
    if status == "failed":
        return f"Sub-agent '{name}' (task {short}) failed."
    if status == "killed":
        return f"Sub-agent '{name}' (task {short}) was cancelled."
    return f"Sub-agent '{name}' (task {short}) status: {status}."


def make_user_message(payload: Dict[str, Any]) -> Dict[str, str]:
    """快捷函数：把 notification payload 直接打包为 LLM messages 里的一条 user 消息。"""
    return {"role": "user", "content": format_task_notification(payload)}

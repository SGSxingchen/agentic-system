"""TranscriptWriter — 任务事件落盘（v2 Phase B 支柱 5 的副产物）

每个 Task 写一份 JSONL 文件到 data/tasks/{task_id}.jsonl。
事件结构: {ts, type, payload}
- ts: ISO 时间戳
- type: start | step_started | step_completed | step_failed | done | killed | error
- payload: dict，事件具体内容

Phase B 不实装 GC（evict_after），留 Phase D。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    """返回项目根目录（与 capabilities/tools/_safety 的 fallback 一致）。"""
    return Path(__file__).resolve().parents[3]


def _tasks_dir() -> Path:
    """data/tasks/ 目录，按需创建。"""
    env_root = os.getenv("AGENTIC_TASK_DATA_DIR", "").strip()
    base = Path(env_root).expanduser().resolve() if env_root else _project_root() / "data" / "tasks"
    base.mkdir(parents=True, exist_ok=True)
    return base


def transcript_path(task_id: str) -> Path:
    return _tasks_dir() / f"{task_id}.jsonl"


def _now_iso() -> str:
    return datetime.now().isoformat()


class TranscriptWriter:
    """简单的 append-only JSONL writer。每个 task 一份文件。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.path = transcript_path(task_id)
        # touch 文件以保证后续 read_transcript 不会因不存在而抛
        try:
            self.path.touch(exist_ok=True)
        except Exception as exc:  # pragma: no cover — 异常路径
            logger.warning("TranscriptWriter touch failed for %s: %s", task_id, exc)

    def write(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """写一行 JSONL；I/O 失败仅打 warning，不中断业务流。"""
        record = {
            "ts": _now_iso(),
            "type": event_type,
            "payload": payload or {},
        }
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "TranscriptWriter.write failed for %s (%s): %s",
                self.task_id,
                event_type,
                exc,
            )


def read_transcript(task_id: str, *, offset: int = 0) -> List[Dict[str, Any]]:
    """读取整个 transcript（offset 暂留作未来增量拉取，目前总是从头读）。"""
    path = transcript_path(task_id)
    if not path.exists():
        return []

    events: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                if idx < offset:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("malformed transcript line in %s: %s", task_id, line[:120])
    except Exception as exc:  # pragma: no cover
        logger.warning("read_transcript failed for %s: %s", task_id, exc)

    return events

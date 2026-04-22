"""简易调用追踪器

提供轻量级的操作耗时追踪，不依赖 OpenTelemetry。
支持上下文管理器用法和最近追踪记录查询。

Usage::

    tracer = Tracer(max_traces=200)

    async with tracer.trace("agent.process") as span:
        span.set_attribute("agent", "coder")
        result = await do_work()

    recent = tracer.get_traces(limit=10)
"""
import time
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Deque, Dict, Iterator, List, Optional
import uuid


@dataclass
class Span:
    """追踪跨度

    代表一次操作的耗时记录。
    """
    trace_id: str
    operation: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | error
    error: Optional[str] = None

    def set_attribute(self, key: str, value: Any) -> None:
        """设置自定义属性"""
        self.attributes[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "operation": self.operation,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": round(self.duration_ms, 3),
            "attributes": self.attributes,
            "status": self.status,
            "error": self.error,
        }


class Tracer:
    """轻量级调用追踪器

    Args:
        max_traces: 最大保留的追踪记录数（FIFO）
    """

    def __init__(self, max_traces: int = 500) -> None:
        self._traces: Deque[Span] = deque(maxlen=max_traces)

    @asynccontextmanager
    async def trace(self, operation: str) -> AsyncIterator[Span]:
        """异步追踪上下文管理器

        Usage::

            async with tracer.trace("llm.call") as span:
                span.set_attribute("model", "gpt-4")
                result = await call_llm(...)
        """
        span = Span(
            trace_id=str(uuid.uuid4()),
            operation=operation,
            started_at=datetime.now(),
        )
        start = time.monotonic()

        try:
            yield span
            span.status = "ok"
        except Exception as e:
            span.status = "error"
            span.error = str(e)
            raise
        finally:
            span.duration_ms = (time.monotonic() - start) * 1000
            span.completed_at = datetime.now()
            self._traces.append(span)

    @contextmanager
    def trace_sync(self, operation: str) -> Iterator[Span]:
        """同步追踪上下文管理器"""
        span = Span(
            trace_id=str(uuid.uuid4()),
            operation=operation,
            started_at=datetime.now(),
        )
        start = time.monotonic()

        try:
            yield span
            span.status = "ok"
        except Exception as e:
            span.status = "error"
            span.error = str(e)
            raise
        finally:
            span.duration_ms = (time.monotonic() - start) * 1000
            span.completed_at = datetime.now()
            self._traces.append(span)

    def get_traces(
        self,
        limit: int = 50,
        operation: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Span]:
        """获取最近的追踪记录

        Args:
            limit: 返回最多几条
            operation: 按操作名过滤
            status: 按状态过滤 (ok / error)

        Returns:
            Span 列表，最新的在前
        """
        results: List[Span] = []
        for span in reversed(self._traces):
            if operation and span.operation != operation:
                continue
            if status and span.status != status:
                continue
            results.append(span)
            if len(results) >= limit:
                break
        return results

    def clear(self) -> None:
        """清空所有追踪记录"""
        self._traces.clear()

    @property
    def total_traces(self) -> int:
        """已记录的追踪总数"""
        return len(self._traces)

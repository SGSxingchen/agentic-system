"""记忆系统数据类型"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class MemoryType(Enum):
    """记忆类型 - 模拟人类三种记忆"""
    EPISODIC = "episodic"        # 情景记忆：过去发生的事件
    SEMANTIC = "semantic"        # 语义记忆：事实和知识
    PROCEDURAL = "procedural"    # 程序性记忆：技能和模式


@dataclass
class Memory:
    """记忆单元"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MemoryType = MemoryType.EPISODIC
    content: str = ""
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5      # 重要性评分 (0-1)
    access_count: int = 0        # 访问次数
    last_accessed: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Memory":
        """从字典反序列化"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=MemoryType(data.get("type", "episodic")),
            content=data.get("content", ""),
            embedding=data.get("embedding", []),
            metadata=data.get("metadata", {}),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"])
            if "last_accessed" in data
            else datetime.now(),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
        )


@dataclass
class MemoryQuery:
    """记忆查询参数"""
    query: str = ""
    memory_types: Optional[list[MemoryType]] = None
    max_results: int = 5
    min_importance: float = 0.0
    time_range: Optional[tuple[datetime, datetime]] = None
    metadata_filter: Optional[dict[str, Any]] = None

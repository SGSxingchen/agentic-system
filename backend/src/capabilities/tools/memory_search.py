"""MemorySearch 能力插件 — 搜索记忆系统

替代旧版 AssistantAgent 中硬编码的记忆检索逻辑，
使其成为任何 Agent 都可以使用的工具。
"""
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema


class MemorySearchCapability(CapabilityBase):
    """搜索记忆系统，返回相关记忆"""

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "搜索记忆系统，根据查询返回相关的历史记忆信息"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询文本",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最大返回结果数，默认 3",
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
            returns="相关记忆列表",
        )

    async def execute(self, **kwargs: Any) -> Any:
        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 3)

        if not query:
            return {"error": "query is required"}

        try:
            # 延迟导入，避免循环依赖
            from api.dependencies import get_memory_retriever

            retriever = get_memory_retriever()
            if not retriever:
                return {"memories": [], "message": "记忆系统未初始化"}

            memories = await retriever.retrieve(context=query, max_results=limit)

            results = []
            for m in memories:
                results.append(
                    {
                        "type": m.type.value if hasattr(m.type, "value") else str(m.type),
                        "content": m.content,
                        "importance": getattr(m, "importance", 0),
                    }
                )

            return {"memories": results, "count": len(results)}

        except ImportError:
            return {"memories": [], "message": "记忆系统依赖未就绪"}
        except Exception as e:
            return {"memories": [], "error": f"记忆检索失败: {str(e)}"}

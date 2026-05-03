"""MemorySearch 能力插件 — 搜索记忆系统

替代旧版 AssistantAgent 中硬编码的记忆检索逻辑，
使其成为任何 Agent 都可以使用的工具。
"""
from typing import Any

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description


class MemorySearchCapability(CapabilityBase):
    """搜索记忆系统，返回相关记忆"""

    @property
    def name(self) -> str:
        return "memory_search"

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
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
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

            if hasattr(retriever, "retrieve_with_scores"):
                scored = await retriever.retrieve_with_scores(context=query, max_results=limit)
            else:
                scored = [
                    {"memory": memory, "retrieval": {}}
                    for memory in await retriever.retrieve(context=query, max_results=limit)
                ]

            results = []
            for item in scored:
                m = item["memory"]
                metadata = getattr(m, "metadata", {}) or {}
                results.append(
                    {
                        "type": m.type.value if hasattr(m.type, "value") else str(m.type),
                        "content": m.content,
                        "assistant_context": (
                            metadata.get("assistant_context")
                            or metadata.get("canonical_summary")
                            or m.content
                        ),
                        "importance": getattr(m, "importance", 0),
                        "metadata": metadata,
                        "retrieval": item.get("retrieval", {}),
                    }
                )

            return {"memories": results, "count": len(results)}

        except ImportError:
            return {"memories": [], "message": "记忆系统依赖未就绪"}
        except Exception as e:
            return {"memories": [], "error": f"记忆检索失败: {str(e)}"}

"""助手 Agent - 第一个真正的 Agent

支持:
- LLM 对话
- 记忆系统集成（检索相关记忆作为上下文）
"""
from typing import Any, Dict, List, Optional
from core.agent import BaseAgent, AgentMetadata
from core.llm import BaseLLMClient


class AssistantAgent(BaseAgent):
    """助手 Agent - 使用 LLM 处理用户消息，带记忆检索"""

    def __init__(
        self,
        name: str,
        bus,
        llm_client: BaseLLMClient,
        memory_retriever=None,
    ):
        super().__init__(
            name,
            bus,
            description="助手智能体 - 使用 LLM 处理用户消息，支持记忆检索",
            capabilities=["chat", "conversation"],
        )
        self.llm = llm_client
        self.memory_retriever = memory_retriever

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理用户消息"""
        user_message = data.get("message", "")

        # 检索相关记忆
        memory_context = ""
        memories_used = 0
        if self.memory_retriever:
            try:
                memories = await self.memory_retriever.retrieve(
                    context=user_message,
                    max_results=3,
                )
                memories_used = len(memories)
                if memories:
                    memory_lines = []
                    for m in memories:
                        memory_lines.append(f"- [{m.type.value}] {m.content}")
                    memory_context = (
                        "\n\n[相关记忆]\n" + "\n".join(memory_lines) + "\n"
                    )
            except Exception as e:
                print(f"[WARN] 记忆检索失败: {e}")

        # 构建系统提示
        system_prompt = "你是一个友好的AI助手。"
        if memory_context:
            system_prompt += (
                f"\n\n以下是你的相关记忆，可以参考但不要过度依赖:"
                f"{memory_context}"
            )

        # 调用 LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = await self.llm.chat(messages)

        return {
            "response": response,
            "original_message": user_message,
            "memories_used": memories_used,
        }

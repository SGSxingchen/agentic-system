"""WebSocket 连接管理与消息处理

提供:
- ConnectionManager: 管理所有 WebSocket 连接
- websocket_endpoint: WebSocket 路由处理函数
- 直接调用 Agent 能力处理用户消息
"""
import json
from typing import Any

from fastapi import WebSocket

from ..dependencies import get_capability_registry, get_memory_formation


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._connections: list[WebSocket] = []

    @property
    def connections(self) -> list[WebSocket]:
        return list(self._connections)

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        print(f"[WS] WebSocket 已连接 (当前 {self.active_count} 个连接)")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        print(f"[WS] WebSocket 已断开 (当前 {self.active_count} 个连接)")

    async def broadcast(self, message: dict[str, Any]) -> None:
        disconnected = []
        for conn in self._connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

    async def send_to(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


# 全局连接管理器实例
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 端点处理函数

    接收前端消息，直接通过 CapabilityRegistry 调用 assistant Agent，
    广播响应并存入记忆。
    """
    await manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("event_type", "user_message")

            if event_type == "user_message":
                await _handle_user_message(data)
            else:
                # 其他事件类型：广播给所有连接
                await manager.broadcast(
                    {
                        "type": "event",
                        "event_type": event_type,
                        "data": data,
                    }
                )

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)


async def _handle_user_message(data: dict[str, Any]) -> None:
    """处理用户消息：调用 assistant → 广播响应 → 存入记忆"""
    user_message = data.get("text", data.get("message", ""))
    if not user_message:
        return

    cap_registry = get_capability_registry()
    if not cap_registry or "assistant" not in cap_registry:
        await manager.broadcast(
            {
                "type": "assistant_response",
                "data": {
                    "response": "Assistant 未初始化",
                    "original_message": user_message,
                },
            }
        )
        return

    try:
        # 直接调用 assistant Agent
        result = await cap_registry.execute("assistant", message=user_message)
        response_text = result.get("response", str(result))

        # 广播响应给前端
        await broadcast_assistant_response(response_text, user_message)

        # 存入记忆
        formation = get_memory_formation()
        if formation and user_message:
            try:
                await formation.create_episodic(
                    event_description=f"用户说: {user_message}\nAssistant回复: {response_text[:200]}",
                    source="assistant_agent",
                    importance=0.4,
                )
            except Exception:
                pass  # 记忆存储失败不影响响应

    except Exception as e:
        await manager.broadcast(
            {
                "type": "assistant_response",
                "data": {
                    "response": f"处理失败: {str(e)}",
                    "original_message": user_message,
                },
            }
        )


async def broadcast_assistant_response(response_text: str, original_message: str) -> None:
    """广播 Assistant 响应给所有前端连接"""
    await manager.broadcast(
        {
            "type": "assistant_response",
            "data": {
                "response": response_text,
                "original_message": original_message,
            },
        }
    )

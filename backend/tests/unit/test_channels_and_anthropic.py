"""测试消息通道（EventChannel / RequestChannel / BroadcastChannel）和 AnthropicClient

覆盖:
- core/bus/channels.py  — 三种通道类型的完整行为
- core/llm/anthropic_client.py — Anthropic LLM 客户端
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.bus.channels import EventChannel, RequestChannel, BroadcastChannel
from core.bus.types import Event, Message, Request, Response, Subscription, Priority


# ============================================================
# EventChannel 测试
# ============================================================


class TestEventChannel:
    """EventChannel 发布/订阅通道测试"""

    def setup_method(self):
        self.channel = EventChannel()

    # -- 基本订阅和分发 --

    @pytest.mark.asyncio
    async def test_subscribe_and_dispatch(self):
        """订阅后能收到事件"""
        received = []
        handler = AsyncMock(side_effect=lambda e: received.append(e))
        self.channel.subscribe("test_event", handler)

        event = Event(source="src", event_type="test_event", data={"key": "value"})
        count = await self.channel.dispatch(event)

        assert count == 1
        handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_subscribe_returns_subscription(self):
        """subscribe 返回 Subscription 对象"""
        handler = AsyncMock()
        sub = self.channel.subscribe("evt", handler, priority=Priority.HIGH)

        assert isinstance(sub, Subscription)
        assert sub.event_type == "evt"
        assert sub.handler is handler
        assert sub.priority == Priority.HIGH

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """多个订阅者都能收到同一事件"""
        h1 = AsyncMock()
        h2 = AsyncMock()
        self.channel.subscribe("evt", h1)
        self.channel.subscribe("evt", h2)

        event = Event(source="src", event_type="evt")
        count = await self.channel.dispatch(event)

        assert count == 2
        h1.assert_called_once_with(event)
        h2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self):
        """取消订阅后不再收到事件"""
        handler = AsyncMock()
        self.channel.subscribe("evt", handler)
        result = self.channel.unsubscribe("evt", handler)

        assert result is True
        event = Event(source="src", event_type="evt")
        count = await self.channel.dispatch(event)
        assert count == 0
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_returns_false(self):
        """取消不存在的订阅返回 False"""
        handler = AsyncMock()
        result = self.channel.unsubscribe("no_such_event", handler)
        assert result is False

    # -- 过滤函数 --

    @pytest.mark.asyncio
    async def test_filter_function_passes(self):
        """过滤函数返回 True 时处理事件"""
        handler = AsyncMock()
        filter_fn = lambda e: e.data.get("important") is True
        self.channel.subscribe("evt", handler, filter_fn=filter_fn)

        event = Event(source="src", event_type="evt", data={"important": True})
        count = await self.channel.dispatch(event)

        assert count == 1
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_function_rejects(self):
        """过滤函数返回 False 时跳过事件"""
        handler = AsyncMock()
        filter_fn = lambda e: e.data.get("important") is True
        self.channel.subscribe("evt", handler, filter_fn=filter_fn)

        event = Event(source="src", event_type="evt", data={"important": False})
        count = await self.channel.dispatch(event)

        assert count == 0
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_filter_error_skips_handler(self):
        """过滤函数抛出异常时跳过该订阅者"""
        handler = AsyncMock()
        filter_fn = MagicMock(side_effect=RuntimeError("filter boom"))
        self.channel.subscribe("evt", handler, filter_fn=filter_fn)

        event = Event(source="src", event_type="evt")
        count = await self.channel.dispatch(event)

        assert count == 0
        handler.assert_not_called()

    # -- 优先级排序 --

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        """高优先级订阅者先被调用"""
        call_order = []
        h_low = AsyncMock(side_effect=lambda e: call_order.append("low"))
        h_high = AsyncMock(side_effect=lambda e: call_order.append("high"))
        h_normal = AsyncMock(side_effect=lambda e: call_order.append("normal"))

        self.channel.subscribe("evt", h_low, priority=Priority.LOW)
        self.channel.subscribe("evt", h_high, priority=Priority.HIGH)
        self.channel.subscribe("evt", h_normal, priority=Priority.NORMAL)

        event = Event(source="src", event_type="evt")
        await self.channel.dispatch(event)

        assert call_order == ["high", "normal", "low"]

    # -- 异常处理 --

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash(self):
        """处理函数抛出异常不影响其他订阅者"""
        h_bad = AsyncMock(side_effect=RuntimeError("handler boom"))
        h_good = AsyncMock()
        self.channel.subscribe("evt", h_bad, priority=Priority.HIGH)
        self.channel.subscribe("evt", h_good, priority=Priority.NORMAL)

        event = Event(source="src", event_type="evt")
        count = await self.channel.dispatch(event)

        # h_bad 失败不计入 delivered，h_good 成功计入
        assert count == 1
        h_good.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_no_subscribers_returns_zero(self):
        """没有订阅者时返回 0"""
        event = Event(source="src", event_type="unknown_event")
        count = await self.channel.dispatch(event)
        assert count == 0

    # -- 同步 handler --

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        """支持同步处理函数"""
        received = []
        handler = MagicMock(side_effect=lambda e: received.append(e.data))
        self.channel.subscribe("evt", handler)

        event = Event(source="src", event_type="evt", data={"v": 1})
        count = await self.channel.dispatch(event)

        assert count == 1
        assert received == [{"v": 1}]

    # -- 查询方法 --

    def test_get_subscriber_count(self):
        """获取订阅者计数"""
        assert self.channel.get_subscriber_count("evt") == 0
        self.channel.subscribe("evt", AsyncMock())
        self.channel.subscribe("evt", AsyncMock())
        assert self.channel.get_subscriber_count("evt") == 2

    def test_get_subscriber_count_other_event(self):
        """不同事件类型的计数互不干扰"""
        self.channel.subscribe("evt_a", AsyncMock())
        self.channel.subscribe("evt_b", AsyncMock())
        self.channel.subscribe("evt_b", AsyncMock())
        assert self.channel.get_subscriber_count("evt_a") == 1
        assert self.channel.get_subscriber_count("evt_b") == 2

    def test_get_all_event_types(self):
        """获取所有已注册的事件类型"""
        self.channel.subscribe("alpha", AsyncMock())
        self.channel.subscribe("beta", AsyncMock())
        types = self.channel.get_all_event_types()
        assert set(types) == {"alpha", "beta"}

    def test_get_all_event_types_empty(self):
        """初始状态无事件类型"""
        assert self.channel.get_all_event_types() == []


# ============================================================
# RequestChannel 测试
# ============================================================


class TestRequestChannel:
    """RequestChannel 请求/响应通道测试"""

    def setup_method(self):
        self.channel = RequestChannel()

    @pytest.mark.asyncio
    async def test_register_and_send_request_with_response(self):
        """注册处理器后发送请求能收到 Response"""
        async def handler(req):
            return Response(source="agent", target=req.source, data={"result": 42})

        self.channel.register_handler("agent", handler)
        request = Request(source="client", target="agent", data={"query": "x"})
        resp = await self.channel.send_request(request)

        assert isinstance(resp, Response)
        assert resp.data == {"result": 42}

    @pytest.mark.asyncio
    async def test_handler_returning_dict_auto_wrapped(self):
        """处理器返回 dict 时自动包装为 Response"""
        async def handler(req):
            return {"answer": "yes"}

        self.channel.register_handler("svc", handler)
        request = Request(source="cli", target="svc", data={})
        resp = await self.channel.send_request(request)

        assert isinstance(resp, Response)
        assert resp.data == {"answer": "yes"}
        assert resp.source == "svc"
        assert resp.target == "cli"

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        """支持同步处理函数"""
        def handler(req):
            return {"sync": True}

        self.channel.register_handler("sync_svc", handler)
        request = Request(source="c", target="sync_svc", data={})
        resp = await self.channel.send_request(request)

        assert resp.data == {"sync": True}

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self):
        """请求超时抛出 asyncio.TimeoutError"""
        async def slow_handler(req):
            await asyncio.sleep(10)
            return Response(source="slow")

        self.channel.register_handler("slow", slow_handler)
        request = Request(source="cli", target="slow", data={}, timeout=0.05)

        with pytest.raises(asyncio.TimeoutError):
            await self.channel.send_request(request)

    @pytest.mark.asyncio
    async def test_timeout_parameter_overrides_request(self):
        """send_request 的 timeout 参数覆盖 request.timeout"""
        async def slow_handler(req):
            await asyncio.sleep(10)
            return Response()

        self.channel.register_handler("slow", slow_handler)
        request = Request(source="cli", target="slow", data={}, timeout=30.0)

        with pytest.raises(asyncio.TimeoutError):
            await self.channel.send_request(request, timeout=0.05)

    @pytest.mark.asyncio
    async def test_missing_handler_raises_value_error(self):
        """目标未注册处理器时抛出 ValueError"""
        request = Request(source="cli", target="nonexistent", data={})

        with pytest.raises(ValueError, match="No handler registered"):
            await self.channel.send_request(request)

    @pytest.mark.asyncio
    async def test_none_target_raises_value_error(self):
        """target 为 None 时抛出 ValueError"""
        request = Request(source="cli", target=None, data={})

        with pytest.raises(ValueError, match="cannot be None"):
            await self.channel.send_request(request)

    def test_unregister_handler(self):
        """注销已注册的处理器"""
        self.channel.register_handler("agent", AsyncMock())
        assert self.channel.has_handler("agent") is True

        result = self.channel.unregister_handler("agent")
        assert result is True
        assert self.channel.has_handler("agent") is False

    def test_unregister_nonexistent_returns_false(self):
        """注销不存在的处理器返回 False"""
        result = self.channel.unregister_handler("ghost")
        assert result is False

    def test_has_handler(self):
        """检查处理器是否存在"""
        assert self.channel.has_handler("x") is False
        self.channel.register_handler("x", AsyncMock())
        assert self.channel.has_handler("x") is True

    @pytest.mark.asyncio
    async def test_get_pending_count(self):
        """等待中的请求计数"""
        assert self.channel.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_handler_exception_propagated(self):
        """处理器抛出异常时，send_request 也抛出该异常"""
        async def bad_handler(req):
            raise RuntimeError("handler failed")

        self.channel.register_handler("bad", bad_handler)
        request = Request(source="cli", target="bad", data={})

        with pytest.raises(RuntimeError, match="handler failed"):
            await self.channel.send_request(request)

    @pytest.mark.asyncio
    async def test_correlation_id_set_on_response(self):
        """返回的 Response 的 correlation_id 与 Request 一致"""
        async def handler(req):
            return Response(source="svc", data={"ok": True})

        self.channel.register_handler("svc", handler)
        request = Request(source="cli", target="svc", data={})
        resp = await self.channel.send_request(request)

        assert resp.correlation_id == request.correlation_id

    @pytest.mark.asyncio
    async def test_pending_cleaned_after_completion(self):
        """请求完成后 pending 计数归零"""
        async def handler(req):
            return {"done": True}

        self.channel.register_handler("svc", handler)
        request = Request(source="cli", target="svc", data={})
        await self.channel.send_request(request)

        assert self.channel.get_pending_count() == 0

    @pytest.mark.asyncio
    async def test_pending_cleaned_after_timeout(self):
        """请求超时后 pending 也会被清理"""
        async def slow_handler(req):
            await asyncio.sleep(10)
            return Response()

        self.channel.register_handler("slow", slow_handler)
        request = Request(source="cli", target="slow", data={}, timeout=0.05)

        with pytest.raises(asyncio.TimeoutError):
            await self.channel.send_request(request)

        assert self.channel.get_pending_count() == 0


# ============================================================
# BroadcastChannel 测试
# ============================================================


class TestBroadcastChannel:
    """BroadcastChannel 广播通道测试"""

    def setup_method(self):
        self.channel = BroadcastChannel()

    @pytest.mark.asyncio
    async def test_register_and_broadcast(self):
        """注册接收器后能收到广播消息"""
        handler = AsyncMock()
        self.channel.register("comp_a", handler)

        msg = Message(source="system", data={"info": "hello"})
        count = await self.channel.broadcast(msg)

        assert count == 1
        handler.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_multiple_receivers(self):
        """多个接收器都能收到广播"""
        h1 = AsyncMock()
        h2 = AsyncMock()
        h3 = AsyncMock()
        self.channel.register("a", h1)
        self.channel.register("b", h2)
        self.channel.register("c", h3)

        msg = Message(source="sys")
        count = await self.channel.broadcast(msg)

        assert count == 3
        h1.assert_called_once()
        h2.assert_called_once()
        h3.assert_called_once()

    @pytest.mark.asyncio
    async def test_unregister(self):
        """注销接收器后不再收到广播"""
        handler = AsyncMock()
        self.channel.register("comp", handler)
        result = self.channel.unregister("comp")

        assert result is True

        msg = Message(source="sys")
        count = await self.channel.broadcast(msg)
        assert count == 0
        handler.assert_not_called()

    def test_unregister_nonexistent_returns_false(self):
        """注销不存在的接收器返回 False"""
        assert self.channel.unregister("ghost") is False

    @pytest.mark.asyncio
    async def test_handler_error_does_not_crash(self):
        """接收器异常不影响其他接收器"""
        h_bad = AsyncMock(side_effect=RuntimeError("boom"))
        h_good = AsyncMock()
        self.channel.register("bad", h_bad)
        self.channel.register("good", h_good)

        msg = Message(source="sys")
        count = await self.channel.broadcast(msg)

        # h_bad 失败不计入，h_good 成功
        assert count == 1
        h_good.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        """支持同步接收器"""
        received = []
        handler = MagicMock(side_effect=lambda m: received.append(m.data))
        self.channel.register("sync_recv", handler)

        msg = Message(source="sys", data={"v": 99})
        count = await self.channel.broadcast(msg)

        assert count == 1
        assert received == [{"v": 99}]

    @pytest.mark.asyncio
    async def test_broadcast_no_receivers_returns_zero(self):
        """没有接收器时返回 0"""
        msg = Message(source="sys")
        count = await self.channel.broadcast(msg)
        assert count == 0

    def test_get_receiver_count(self):
        """获取接收器数量"""
        assert self.channel.get_receiver_count() == 0
        self.channel.register("a", AsyncMock())
        self.channel.register("b", AsyncMock())
        assert self.channel.get_receiver_count() == 2

    def test_get_receiver_names(self):
        """获取所有接收器名称"""
        self.channel.register("alpha", AsyncMock())
        self.channel.register("beta", AsyncMock())
        names = self.channel.get_receiver_names()
        assert set(names) == {"alpha", "beta"}

    def test_get_receiver_names_empty(self):
        """初始状态无接收器"""
        assert self.channel.get_receiver_names() == []


# ============================================================
# AnthropicClient 测试
# ============================================================


class TestAnthropicClient:
    """AnthropicClient LLM 客户端测试"""

    @patch("core.llm.anthropic_client.AnthropicClient.__init__", return_value=None)
    def _make_client(self, mock_init):
        """创建一个跳过真实 __init__ 的 AnthropicClient 实例"""
        from core.llm.anthropic_client import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client.api_key = "test-key"
        client.model = "claude-3-5-sonnet-20241022"
        client.base_url = None
        client.client = MagicMock()
        return client

    @patch.dict("sys.modules", {"anthropic": MagicMock()})
    def test_init_default_model(self):
        """默认模型为 claude-3-5-sonnet-20241022"""
        from core.llm.anthropic_client import AnthropicClient
        client = AnthropicClient(api_key="sk-test")
        assert client.model == "claude-3-5-sonnet-20241022"
        assert client.api_key == "sk-test"
        assert client.base_url is None

    @patch.dict("sys.modules", {"anthropic": MagicMock()})
    def test_init_custom_model(self):
        """可以指定自定义模型"""
        from core.llm.anthropic_client import AnthropicClient
        client = AnthropicClient(api_key="sk-test", model="claude-3-opus-20240229")
        assert client.model == "claude-3-opus-20240229"

    @patch.dict("sys.modules", {"anthropic": MagicMock()})
    def test_init_with_base_url(self):
        """支持自定义 base_url"""
        from core.llm.anthropic_client import AnthropicClient
        client = AnthropicClient(api_key="sk-test", base_url="https://proxy.example.com")
        assert client.base_url == "https://proxy.example.com"

    @pytest.mark.asyncio
    async def test_chat_extracts_system_message(self):
        """chat 方法正确提取 system 消息"""
        from core.llm.anthropic_client import AnthropicClient
        client = self._make_client()

        # 构造 mock 响应
        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Hello from Claude"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        client.client.messages.create = AsyncMock(return_value=mock_response)

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ]
        result = await client.chat(messages)

        assert result.content == "Hello from Claude"
        client.client.messages.create.assert_called_once()
        call_kwargs = client.client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are helpful"
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hi"}]

    @pytest.mark.asyncio
    async def test_chat_without_system_message(self):
        """没有 system 消息时 system 参数为 None"""
        from core.llm.anthropic_client import AnthropicClient
        client = self._make_client()

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Reply"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        client.client.messages.create = AsyncMock(return_value=mock_response)

        messages = [{"role": "user", "content": "Hello"}]
        result = await client.chat(messages)

        assert result.content == "Reply"
        call_kwargs = client.client.messages.create.call_args[1]
        # 没有 system 消息时不传 system 参数
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hello"}]

    @pytest.mark.asyncio
    async def test_chat_returns_text(self):
        """chat 返回 LLMResponse，content 包含响应文本"""
        from core.llm.anthropic_client import AnthropicClient
        client = self._make_client()

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Exact response text"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        client.client.messages.create = AsyncMock(return_value=mock_response)

        result = await client.chat([{"role": "user", "content": "test"}])
        assert result.content == "Exact response text"
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_chat_passes_model_and_max_tokens(self):
        """chat 传递正确的 model 和 max_tokens"""
        from core.llm.anthropic_client import AnthropicClient
        client = self._make_client()
        client.model = "claude-3-haiku-20240307"

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "ok"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        client.client.messages.create = AsyncMock(return_value=mock_response)

        await client.chat([{"role": "user", "content": "ping"}])

        call_kwargs = client.client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-3-haiku-20240307"
        assert call_kwargs["max_tokens"] == 4096

    @pytest.mark.asyncio
    async def test_chat_filters_system_from_user_messages(self):
        """多条消息中 system 消息被过滤，其余保留"""
        from core.llm.anthropic_client import AnthropicClient
        client = self._make_client()

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "response"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        client.client.messages.create = AsyncMock(return_value=mock_response)

        messages = [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": "Question 2"},
        ]
        await client.chat(messages)

        call_kwargs = client.client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Be concise"
        assert len(call_kwargs["messages"]) == 3
        assert call_kwargs["messages"][0] == {"role": "user", "content": "Question 1"}
        assert call_kwargs["messages"][1] == {"role": "assistant", "content": "Answer 1"}
        assert call_kwargs["messages"][2] == {"role": "user", "content": "Question 2"}

    def test_import_error_without_anthropic(self):
        """未安装 anthropic 包时抛出 ImportError"""
        import importlib
        # 临时移除 anthropic 模块（如果存在）
        with patch.dict("sys.modules", {"anthropic": None}):
            # 重新加载模块以触发 ImportError
            from core.llm.anthropic_client import AnthropicClient
            with pytest.raises(ImportError, match="请安装 anthropic"):
                AnthropicClient(api_key="sk-test")

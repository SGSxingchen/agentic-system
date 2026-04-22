"""统一消息总线测试"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from core.bus import (
    UnifiedBus,
    SimpleBus,
    Event,
    Message,
    Request,
    Response,
    MessageType,
    Priority,
    MessageRouter,
)


# =====================
# 基础生命周期
# =====================

class TestBusLifecycle:
    async def test_start_stop(self):
        bus = UnifiedBus()
        await bus.start()
        assert bus._running is True
        await bus.stop()
        assert bus._running is False

    async def test_simple_bus_alias(self):
        assert SimpleBus is UnifiedBus


# =====================
# 发布/订阅
# =====================

class TestPubSub:
    async def test_publish_subscribe(self):
        bus = UnifiedBus()
        await bus.start()
        received = []

        async def handler(event):
            received.append(event.data)

        bus.subscribe("test_event", handler)
        await bus.publish(Event(source="test", event_type="test_event", data={"msg": "hello"}))
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0]["msg"] == "hello"
        await bus.stop()

    async def test_multiple_subscribers(self):
        bus = UnifiedBus()
        await bus.start()
        results = []

        async def handler_a(event):
            results.append("A")

        async def handler_b(event):
            results.append("B")

        bus.subscribe("multi", handler_a)
        bus.subscribe("multi", handler_b)
        await bus.publish(Event(source="test", event_type="multi", data={}))
        await asyncio.sleep(0.2)

        assert "A" in results
        assert "B" in results
        await bus.stop()

    async def test_unsubscribe(self):
        bus = UnifiedBus()
        await bus.start()
        received = []

        async def handler(event):
            received.append(1)

        bus.subscribe("unsub_test", handler)
        bus.unsubscribe("unsub_test", handler)
        await bus.publish(Event(source="test", event_type="unsub_test", data={}))
        await asyncio.sleep(0.2)

        assert len(received) == 0
        await bus.stop()

    async def test_event_filter(self):
        bus = UnifiedBus()
        await bus.start()
        received = []

        async def handler(event):
            received.append(event.data)

        bus.subscribe(
            "filtered",
            handler,
            filter_fn=lambda e: e.data.get("lang") == "python",
        )

        await bus.publish(Event(source="t", event_type="filtered", data={"lang": "python"}))
        await bus.publish(Event(source="t", event_type="filtered", data={"lang": "java"}))
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0]["lang"] == "python"
        await bus.stop()

    async def test_no_subscribers(self):
        bus = UnifiedBus()
        await bus.start()
        await bus.publish(Event(source="test", event_type="nobody_listens", data={}))
        await asyncio.sleep(0.2)
        # 不应该报错
        await bus.stop()


# =====================
# 请求/响应
# =====================

class TestRequestResponse:
    async def test_request_response(self):
        bus = UnifiedBus()
        await bus.start()

        async def echo_handler(req):
            return Response(
                source="echo",
                data={"echo": req.data.get("msg")},
            )

        bus.handle_request("echo_service", echo_handler)

        msg = Message(source="client", data={"msg": "ping"})
        resp = await bus.request("echo_service", msg, timeout=5.0)

        assert resp.data["echo"] == "ping"
        await bus.stop()

    async def test_request_timeout(self):
        """RequestChannel 处理器执行超时应引发 TimeoutError"""
        bus = UnifiedBus()
        await bus.start()

        # 直接测试 RequestChannel 的超时行为
        async def slow_handler(req):
            # 处理器内部 sleep 超过 timeout
            await asyncio.sleep(10)
            return Response(source="slow", data={})

        bus._request_channel.register_handler("slow_service", slow_handler)

        req = Request(source="client", target="slow_service", data={}, timeout=0.1)
        with pytest.raises(asyncio.TimeoutError):
            await bus._request_channel.send_request(req, timeout=0.1)

        await bus.stop()

    async def test_request_no_handler(self):
        bus = UnifiedBus()
        await bus.start()

        msg = Message(source="client", data={})
        with pytest.raises(ValueError):
            await bus.request("nonexistent", msg, timeout=1.0)

        await bus.stop()


# =====================
# 广播
# =====================

class TestBroadcast:
    async def test_broadcast(self):
        bus = UnifiedBus()
        await bus.start()
        results = []

        async def receiver_a(msg):
            results.append("A")

        async def receiver_b(msg):
            results.append("B")

        bus.register_broadcast_receiver("comp_a", receiver_a)
        bus.register_broadcast_receiver("comp_b", receiver_b)

        await bus.broadcast(Message(source="system", data={"action": "shutdown"}))

        assert "A" in results
        assert "B" in results
        await bus.stop()


# =====================
# 优先级
# =====================

class TestPriority:
    async def test_high_priority_first(self):
        bus = UnifiedBus(queue_size=100, history_size=50)
        # 不启动 process loop，手动入队再检查顺序
        received = []

        async def handler(event):
            received.append(event.data.get("order"))

        bus.subscribe("prio_test", handler)

        # 先入低优先级，再入高优先级
        await bus._queue.put(
            (-Priority.LOW, 1, Event(source="t", event_type="prio_test", data={"order": "low"}, priority=Priority.LOW))
        )
        await bus._queue.put(
            (-Priority.CRITICAL, 2, Event(source="t", event_type="prio_test", data={"order": "critical"}, priority=Priority.CRITICAL))
        )
        await bus._queue.put(
            (-Priority.NORMAL, 3, Event(source="t", event_type="prio_test", data={"order": "normal"}, priority=Priority.NORMAL))
        )

        # 手动取出并分发
        for _ in range(3):
            neg_p, counter, msg = await bus._queue.get()
            await bus._dispatch(msg)

        assert received == ["critical", "normal", "low"]


# =====================
# 消息历史和统计
# =====================

class TestHistoryAndStats:
    async def test_message_history(self):
        bus = UnifiedBus(history_size=10)
        await bus.start()

        async def noop(event):
            pass

        bus.subscribe("hist", noop)

        for i in range(5):
            await bus.publish(Event(source="t", event_type="hist", data={"i": i}))

        await asyncio.sleep(0.3)

        history = bus.get_history(limit=50)
        assert len(history) >= 5
        await bus.stop()

    async def test_stats(self):
        bus = UnifiedBus()
        await bus.start()

        async def noop(event):
            pass

        bus.subscribe("stat_test", noop)
        await bus.publish(Event(source="t", event_type="stat_test", data={}))
        await asyncio.sleep(0.2)

        stats = bus.get_stats()
        assert stats["messages_published"] >= 1
        assert stats["running"] is True
        assert "queue_size" in stats
        await bus.stop()


# =====================
# 消息TTL
# =====================

class TestTTL:
    def test_message_not_expired(self):
        msg = Message(ttl=60)
        assert msg.is_expired() is False

    def test_message_expired(self):
        from datetime import datetime, timedelta
        msg = Message(ttl=1)
        msg.timestamp = datetime.now() - timedelta(seconds=10)
        assert msg.is_expired() is True


# =====================
# 路由
# =====================

class TestRouter:
    async def test_exact_route(self):
        router = MessageRouter()
        received = []

        async def handler(msg):
            received.append(msg.data)

        router.add_route("agent.coder", handler)
        msg = Message(target="agent.coder", data={"task": "code"})
        delivered = await router.route(msg)

        assert delivered == 1
        assert received[0]["task"] == "code"

    async def test_wildcard_route(self):
        router = MessageRouter()
        received = []

        async def handler(msg):
            received.append(msg.target)

        router.add_route("agent.*", handler)

        await router.route(Message(target="agent.coder", data={}))
        await router.route(Message(target="agent.reviewer", data={}))
        await router.route(Message(target="system.health", data={}))

        assert len(received) == 2
        assert "agent.coder" in received
        assert "agent.reviewer" in received

    def test_has_route(self):
        router = MessageRouter()
        router.add_route("test.route", lambda m: None)
        assert router.has_route("test.route") is True
        assert router.has_route("other.route") is False

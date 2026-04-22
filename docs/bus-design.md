# 统一消息总线设计

## 1. 总线架构

```
┌──────────────────────────────────────────────────────┐
│              Unified Message Bus                     │
│                (统一消息总线)                         │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │  Event     │  │  Request   │  │ Broadcast  │    │
│  │  Channel   │  │  Channel   │  │  Channel   │    │
│  └────────────┘  └────────────┘  └────────────┘    │
│                                                      │
│  ┌────────────────────────────────────────────┐     │
│  │         Message Router (消息路由器)         │     │
│  └────────────────────────────────────────────┘     │
│                                                      │
│  ┌────────────────────────────────────────────┐     │
│  │      Message Queue (消息队列)               │     │
│  └────────────────────────────────────────────┘     │
│                                                      │
│  ┌────────────────────────────────────────────┐     │
│  │   Dead Letter Queue (死信队列)              │     │
│  └────────────────────────────────────────────┘     │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## 2. 通信模式

### 2.1 发布/订阅（Pub/Sub）

**用途**：事件驱动，一对多通信

```python
# 发布事件
await bus.publish(Event(
    type="code_generated",
    data={"code": "..."}
))

# 订阅事件
@bus.subscribe("code_generated")
async def on_code_generated(event):
    # 处理事件
    pass
```

### 2.2 请求/响应（Request/Response）

**用途**：同步调用，需要返回值

```python
# 发送请求
response = await bus.request(
    target="reviewer_agent",
    message={"code": "..."}
)

# 处理请求
@bus.handle_request("reviewer_agent")
async def handle_review(request):
    result = await review_code(request.data)
    return Response(data=result)
```

### 2.3 点对点（Point-to-Point）

**用途**：直接消息，一对一通信

```python
# 发送消息
await bus.send(
    target="coder_agent",
    message={"task": "fix_bug"}
)
```

### 2.4 广播（Broadcast）

**用途**：全局通知

```python
# 广播消息
await bus.broadcast(Message(
    type="system_shutdown",
    data={"reason": "maintenance"}
))
```

## 3. 消息格式

```python
@dataclass
class Message:
    """统一消息格式"""
    id: str                      # 消息ID
    type: MessageType            # EVENT, REQUEST, RESPONSE, BROADCAST
    source: str                  # 发送者
    target: Optional[str]        # 接收者（可选）
    data: dict[str, Any]         # 消息数据
    timestamp: datetime          # 时间戳
    correlation_id: str          # 关联ID（追踪）
    reply_to: Optional[str]      # 回复地址
    ttl: Optional[int]           # 生存时间（秒）
    priority: int = 0            # 优先级
```

## 4. 总线特性

### 4.1 消息持久化

```python
class PersistentBus(MessageBus):
    """支持消息持久化的总线"""

    async def publish(self, message: Message):
        # 先持久化
        await self._persist(message)
        # 再发送
        await super().publish(message)
```

### 4.2 消息重试

```python
class RetryPolicy:
    max_retries: int = 3
    backoff: str = "exponential"  # linear, exponential
    initial_delay: float = 1.0
```

### 4.3 死信队列

```python
# 消息处理失败后进入死信队列
if retry_count > max_retries:
    await bus.send_to_dead_letter(message)
```

### 4.4 消息过滤

```python
# 基于条件过滤消息
@bus.subscribe("code_generated", filter="data.language == 'python'")
async def on_python_code(event):
    pass
```

## 5. 总线与其他组件的关系

```
User Input
    ↓
Application Layer
    ↓
┌─────────────────┐
│  Message Bus    │ ← 所有通信的中心
└─────────────────┘
    ↓   ↓   ↓
Agent A  Agent B  Agent C
    ↓       ↓       ↓
Capability Layer
```

## 6. 实现示例

```python
# 创建总线
bus = UnifiedBus()

# Agent 连接到总线
class ReviewerAgent(BaseAgent):
    def __init__(self, bus: UnifiedBus):
        self.bus = bus
        # 订阅事件
        self.bus.subscribe("code_generated", self.on_code_generated)
        # 注册请求处理器
        self.bus.handle_request("review", self.handle_review_request)

    async def on_code_generated(self, event: Event):
        """响应事件"""
        result = await self.review(event.data)
        # 发布新事件
        await self.bus.publish(Event(
            type="review_completed",
            data=result
        ))

    async def handle_review_request(self, request: Message):
        """处理请求"""
        result = await self.review(request.data)
        return Response(data=result)
```

## 7. 配置

```yaml
# config/bus.yaml
bus:
  # 消息队列大小
  queue_size: 10000

  # 持久化
  persistence:
    enabled: true
    backend: "sqlite"  # sqlite, redis, postgres

  # 重试策略
  retry:
    max_retries: 3
    backoff: "exponential"
    initial_delay: 1.0

  # 死信队列
  dead_letter:
    enabled: true
    max_size: 1000

  # 监控
  monitoring:
    enabled: true
    metrics_port: 9090
```

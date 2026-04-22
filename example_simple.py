"""简单示例 - 演示 Agentic System 核心功能

本示例展示:
1. 创建消息总线 (SimpleBus) - Agent 之间通信的核心
2. 创建自定义 Agent - 继承 BaseAgent 实现 process 方法
3. 订阅事件 - Agent 监听感兴趣的事件类型
4. 发布事件 - 通过总线发送消息
5. 请求-响应模式 - Agent 间的同步通信
6. 记忆系统 - 创建和检索记忆
7. 能力插件 - 使用内置代码分析能力

**无需启动后端服务，直接运行即可。**

用法:
    cd /path/to/agentic-system
    python3 example_simple.py
"""
import asyncio
import sys

# 将 backend/src 加入 Python 路径，以便直接导入模块
sys.path.insert(0, "backend/src")

from core.bus import SimpleBus, Event
from core.agent import BaseAgent


# ──────────────────────────────────────────────────────────
# 第一部分: 定义自定义 Agent
# ──────────────────────────────────────────────────────────


class PrinterAgent(BaseAgent):
    """打印 Agent - 收到消息后打印内容

    这是最简单的 Agent 实现，展示了 BaseAgent 的基本用法。
    """

    async def process(self, data):
        msg = data.get("message", str(data))
        print(f"  📝 [{self.name}] 收到: {msg}")
        return {"status": "printed", "content": msg}


class EchoAgent(BaseAgent):
    """回声 Agent - 收到消息后回传原始内容

    展示 Agent 如何返回处理结果。
    """

    async def process(self, data):
        message = data.get("message", "")
        print(f"  🔊 [{self.name}] Echo: {message}")
        return {"echo": message}


class CounterAgent(BaseAgent):
    """计数 Agent - 统计收到的消息数量

    展示 Agent 如何维护内部状态。
    """

    def __init__(self, name, bus, **kwargs):
        super().__init__(name, bus, **kwargs)
        self.count = 0

    async def process(self, data):
        self.count += 1
        print(f"  🔢 [{self.name}] 已处理 {self.count} 条消息")
        return {"count": self.count}


# ──────────────────────────────────────────────────────────
# 第二部分: 演示事件驱动通信
# ──────────────────────────────────────────────────────────


async def demo_event_driven():
    """演示事件发布/订阅模式"""
    print("\n" + "=" * 60)
    print("🚌 演示 1: 事件驱动通信 (Pub/Sub)")
    print("=" * 60)

    # 步骤 1: 创建消息总线
    bus = SimpleBus()
    await bus.start()
    print("✅ 消息总线已启动")

    # 步骤 2: 创建 Agent
    printer = PrinterAgent("printer", bus, description="打印消息的Agent")
    echo = EchoAgent("echo", bus, description="回声Agent")
    counter = CounterAgent("counter", bus, description="计数Agent")
    print("✅ 创建了 3 个 Agent: printer, echo, counter")

    # 步骤 3: 启动 Agent (设置状态为 IDLE)
    await printer.start()
    await echo.start()
    await counter.start()
    print(f"✅ Agent 状态: printer={printer.status.value}, echo={echo.status.value}")

    # 步骤 4: 订阅事件 - 多个 Agent 可以订阅同一个事件类型
    bus.subscribe("chat", printer.on_event)
    bus.subscribe("chat", echo.on_event)
    bus.subscribe("chat", counter.on_event)
    bus.subscribe("system_alert", printer.on_event)
    print("✅ Agent 已订阅事件")

    # 步骤 5: 发布事件 - 所有订阅者都会收到
    print("\n📤 发布 'chat' 事件...")
    await bus.publish(Event(
        source="user",
        event_type="chat",
        data={"message": "Hello, Agents!"},
    ))
    await asyncio.sleep(0.5)

    # 步骤 6: 发布另一个事件
    print("\n📤 发布 'system_alert' 事件 (只有 printer 订阅)...")
    await bus.publish(Event(
        source="system",
        event_type="system_alert",
        data={"message": "⚠️ 磁盘空间不足"},
    ))
    await asyncio.sleep(0.5)

    # 步骤 7: 查看总线统计
    stats = bus.get_stats()
    print(f"\n📊 总线统计: 已发布 {stats['messages_published']} 条消息, "
          f"已投递 {stats['messages_delivered']} 次")

    # 清理
    await printer.stop()
    await echo.stop()
    await counter.stop()
    await bus.stop()
    print("✅ 资源已清理")


# ──────────────────────────────────────────────────────────
# 第三部分: 演示请求-响应模式
# ──────────────────────────────────────────────────────────


async def demo_request_response():
    """演示请求-响应模式"""
    print("\n" + "=" * 60)
    print("🔄 演示 2: 请求-响应模式")
    print("=" * 60)

    bus = SimpleBus()
    await bus.start()

    echo = EchoAgent("echo", bus)
    await echo.start()

    # 注册请求处理器 - echo Agent 处理 "echo_service" 类型的请求
    async def handle_echo(request):
        result = await echo.process(request.data)
        return result

    bus.handle_request("echo_service", handle_echo)
    print("✅ 注册了 echo_service 请求处理器")

    # 发送请求并等待响应
    from core.bus import Request
    print("\n📤 发送请求到 echo_service...")
    response = await bus.request(
        target="echo_service",
        message=Request(
            source="demo",
            target="echo_service",
            data={"message": "ping!"},
        ),
    )
    print(f"📥 收到响应: {response.data if hasattr(response, 'data') else response}")

    await bus.stop()
    print("✅ 完成")


# ──────────────────────────────────────────────────────────
# 第四部分: 演示记忆系统
# ──────────────────────────────────────────────────────────


async def demo_memory():
    """演示记忆系统"""
    print("\n" + "=" * 60)
    print("🧠 演示 3: 记忆系统")
    print("=" * 60)

    from core.memory import InMemoryStore, MemoryFormation, MemoryRetriever, MemoryType

    # 步骤 1: 创建记忆存储（使用内存后端，无需外部依赖）
    store = InMemoryStore()
    formation = MemoryFormation(store)
    retriever = MemoryRetriever(store)
    print("✅ 记忆系统已初始化（内存后端）")

    # 步骤 2: 创建不同类型的记忆
    m1 = await formation.create_memory(
        content="用户喜欢使用 Python 编程",
        memory_type=MemoryType.SEMANTIC,
        importance=0.8,
    )
    print(f"  💾 创建语义记忆: {m1.content} (重要性: {m1.importance})")

    m2 = await formation.create_memory(
        content="今天讨论了消息总线的设计方案",
        memory_type=MemoryType.EPISODIC,
        importance=0.6,
    )
    print(f"  💾 创建情节记忆: {m2.content} (重要性: {m2.importance})")

    m3 = await formation.create_memory(
        content="代码审查步骤: 1.检查语法 2.检查逻辑 3.检查性能",
        memory_type=MemoryType.PROCEDURAL,
        importance=0.9,
    )
    print(f"  💾 创建程序记忆: {m3.content} (重要性: {m3.importance})")

    # 步骤 3: 检索记忆
    print("\n🔍 搜索 'Python' 相关记忆...")
    results = await retriever.retrieve(context="Python 编程", max_results=5)
    for r in results:
        print(f"  📌 [{r.type.value}] {r.content}")

    # 步骤 4: 获取统计
    stats = await formation.get_stats()
    print(f"\n📊 记忆统计: {stats}")


# ──────────────────────────────────────────────────────────
# 第五部分: 演示能力插件
# ──────────────────────────────────────────────────────────


async def demo_capabilities():
    """演示内置能力插件"""
    print("\n" + "=" * 60)
    print("🔧 演示 4: 能力插件 (代码分析)")
    print("=" * 60)

    from capabilities.builtin.code_parser import CodeParserCapability
    from capabilities.builtin.static_analyzer import StaticAnalyzerCapability

    # 步骤 1: 代码解析
    parser = CodeParserCapability()
    sample_code = '''
def fibonacci(n: int) -> int:
    """计算第 n 个斐波那契数"""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

class Calculator:
    """简单计算器"""
    def add(self, a, b):
        return a + b
'''

    result = await parser.execute(code=sample_code)
    print(f"📝 代码解析结果:")
    print(f"  函数: {[f['name'] for f in result.get('functions', [])]}")
    print(f"  类: {[c['name'] for c in result.get('classes', [])]}")
    metrics = result.get("metrics", {})
    print(f"  代码行数: {metrics.get('total_lines', 'N/A')}")

    # 步骤 2: 静态分析
    analyzer = StaticAnalyzerCapability()
    bad_code = '''
import os
import sys
import json

def badNaming():
    x = [1,2,3,4,5,6,7,8,9,10]
    return x
'''

    analysis = await analyzer.execute(code=bad_code)
    issues = analysis.get("issues", [])
    print(f"\n🔍 静态分析发现 {len(issues)} 个问题:")
    for issue in issues[:5]:  # 最多显示 5 个
        print(f"  ⚠️ [{issue.get('severity', 'info')}] 第{issue.get('line', '?')}行: "
              f"{issue.get('message', '')}")


# ──────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────


async def main():
    print("🚀 Agentic System - 核心功能演示")
    print("本示例展示系统的核心组件，无需启动后端服务。")

    # 演示 1: 事件驱动通信
    await demo_event_driven()

    # 演示 2: 请求-响应模式
    await demo_request_response()

    # 演示 3: 记忆系统
    await demo_memory()

    # 演示 4: 能力插件
    await demo_capabilities()

    print("\n" + "=" * 60)
    print("✅ 所有演示完成!")
    print("=" * 60)
    print("\n💡 提示: 要使用 LLM 功能，请在 backend/src/config.yaml 中配置 API Key，")
    print("   然后启动后端服务: cd backend/src && python3 -m uvicorn api.main:app --reload")


if __name__ == "__main__":
    asyncio.run(main())

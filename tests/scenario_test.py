"""场景化集成测试 — 使用真实 LLM 后端

⚠️ 前置条件：
1. 在 backend/src/config.yaml 中配置有效的 LLM API Key
2. 启动后端服务:
   cd backend/src && python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8001
3. 确保 LLM API 可访问

运行方式:
    python3 tests/scenario_test.py              # 直接运行
    python3 -m pytest tests/scenario_test.py -v  # pytest 模式

注意:
- 这些测试调用真实 LLM，每次运行会产生 API 费用
- LLM 响应不确定，测试只验证结构和关键特征
- 超时设为 120 秒以适应真实 LLM 调用延迟
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytest
import requests

# ─── 配置 ─────────────────────────────────────────────────

BASE_URL = "http://localhost:8001"
TIMEOUT = 120  # 秒，LLM 调用可能较慢


# ─── 工具函数 ─────────────────────────────────────────────


def api_post(path: str, data: dict, timeout: int = TIMEOUT) -> requests.Response:
    """发送 POST 请求"""
    return requests.post(
        f"{BASE_URL}{path}",
        json=data,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )


def api_get(path: str, timeout: int = 10) -> requests.Response:
    """发送 GET 请求"""
    return requests.get(f"{BASE_URL}{path}", timeout=timeout)


def check_server() -> bool:
    """检查服务器是否运行"""
    try:
        resp = api_get("/api/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


# ─── 测试前置检查 ─────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def ensure_server_running():
    """确保后端服务已启动"""
    if not check_server():
        pytest.skip(
            "后端服务未启动。请先运行:\n"
            "  cd backend/src && python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8001"
        )


# ─── 场景一：对话助手 ─────────────────────────────────────


class TestScenario1Chat:
    """场景一：基本对话 — 助手 Agent 调用 LLM 回答问题"""

    def test_assistant_chat(self):
        """通过 assistant/invoke 发送对话，验证 LLM 返回有意义的回答"""
        resp = api_post(
            "/api/agents/assistant/invoke",
            {"data": {"message": "请帮我解释什么是设计模式中的观察者模式，用 Python 举一个简单的例子"}},
        )
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["status"] == "ok"

        data = body["data"]
        response_text = data.get("response", "")

        # 验证有意义的回答
        assert len(response_text) > 100, "回答过短，可能 LLM 未正确调用"
        assert "观察者" in response_text or "Observer" in response_text, "回答不包含关键概念"

        # 验证包含代码
        assert "class" in response_text or "def" in response_text, "回答不包含代码示例"

        print(f"✅ 场景一通过 — 回答长度: {len(response_text)} 字符")

    def test_task_submit(self):
        """通过 /api/tasks 提交任务，验证任务创建成功"""
        resp = api_post(
            "/api/tasks",
            {"requirement": "解释 Python 的装饰器", "workflow": "auto"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "task_id" in body["data"]
        assert body["data"]["status"] in ("pending", "planning")

        print(f"✅ 任务提交通过 — task_id: {body['data']['task_id']}")


# ─── 场景二：任务规划 ─────────────────────────────────────


class TestScenario2Planner:
    """场景二：任务规划 — Planner Agent 将需求分解为子任务"""

    def test_planner_invoke(self):
        """调用 Planner，验证返回结构化任务分解"""
        resp = api_post(
            "/api/agents/planner/invoke",
            {
                "data": {
                    "requirement": "我需要开发一个 Python 的 TODO List 命令行应用，支持添加、删除、列表、标记完成功能"
                }
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        data = body["data"]
        plan = data.get("plan")

        # 验证计划不为空
        assert plan is not None, "Planner 未返回计划"
        assert isinstance(plan, list), "计划不是列表格式"
        assert len(plan) >= 3, f"子任务太少 ({len(plan)}个)，期望至少 3 个"

        # 验证子任务结构
        for task in plan:
            assert "name" in task, "子任务缺少 name"
            assert "description" in task, "子任务缺少 description"
            assert "agent" in task, "子任务缺少 agent"
            assert "dependencies" in task, "子任务缺少 dependencies"

        # 验证有依赖关系（不全是空依赖）
        has_deps = any(len(t.get("dependencies", [])) > 0 for t in plan)
        assert has_deps, "子任务之间没有依赖关系"

        print(f"✅ 场景二通过 — {len(plan)} 个子任务，有依赖关系")


# ─── 场景三：代码生成 ─────────────────────────────────────


class TestScenario3Coder:
    """场景三：代码生成 — Coder Agent 生成高质量代码"""

    generated_code: str = ""

    def test_coder_invoke(self):
        """调用 Coder，验证返回可执行的 Python 代码"""
        resp = api_post(
            "/api/agents/coder/invoke",
            {
                "data": {
                    "message": "请用 Python 实现一个简单的栈(Stack)数据结构，支持 push、pop、peek、is_empty、size 方法，并包含完整的类型注解和文档字符串"
                }
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        data = body["data"]
        code = data.get("code", "")

        # 验证代码不为空
        assert len(code) > 50, "生成的代码过短"

        # 验证包含关键结构
        assert "class" in code or "def" in code, "代码不包含类或函数定义"
        assert "push" in code, "代码不包含 push 方法"
        assert "pop" in code, "代码不包含 pop 方法"

        # 验证包含类型注解
        assert "->" in code or ": " in code, "代码缺少类型注解"

        # 保存代码供场景四使用
        TestScenario3Coder.generated_code = code

        print(f"✅ 场景三通过 — 代码长度: {len(code)} 字符, 语言: {data.get('language', 'N/A')}")


# ─── 场景四：代码审查 ─────────────────────────────────────


class TestScenario4Reviewer:
    """场景四：代码审查 — Reviewer Agent 审查代码"""

    def test_reviewer_invoke(self):
        """调用 Reviewer 审查场景三生成的代码"""
        code = TestScenario3Coder.generated_code
        if not code:
            # Fallback: 使用一段固定代码
            code = '''
class Stack:
    def __init__(self):
        self._items = []
    def push(self, item):
        self._items.append(item)
    def pop(self):
        return self._items.pop()
    def peek(self):
        return self._items[-1]
    def is_empty(self):
        return len(self._items) == 0
    def size(self):
        return len(self._items)
'''

        resp = api_post(
            "/api/agents/reviewer/invoke",
            {"data": {"code": code, "language": "python", "message": "请审查以上代码"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        data = body["data"]

        # 验证审查结果结构
        assert "approved" in data, "缺少 approved 字段"
        assert "severity" in data, "缺少 severity 字段"
        assert isinstance(data["approved"], bool), "approved 不是布尔值"
        assert isinstance(data["severity"], int), "severity 不是整数"

        # 验证包含 issues 或 suggestions
        has_feedback = (
            len(data.get("issues", [])) > 0
            or len(data.get("suggestions", [])) > 0
            or data.get("summary", "")
        )
        assert has_feedback, "审查缺少任何反馈"

        print(
            f"✅ 场景四通过 — approved: {data['approved']}, "
            f"severity: {data['severity']}, "
            f"issues: {len(data.get('issues', []))}, "
            f"suggestions: {len(data.get('suggestions', []))}"
        )


# ─── 场景五：完整工作流 ───────────────────────────────────


class TestScenario5Workflow:
    """场景五：完整工作流 — 代码生成→审查流水线"""

    def test_workflow_execute(self):
        """执行 code_generation_and_review 工作流，验证完整流水线"""
        resp = api_post(
            "/api/workflows/execute",
            {
                "template_name": "code_generation_and_review",
                "input": "实现一个 Python 的 LRU Cache，使用 OrderedDict，支持 get 和 put 操作，容量限制为构造参数",
            },
            timeout=300,  # 工作流涉及多次 LLM 调用
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        data = body["data"]
        assert data.get("status") == "completed", f"工作流未完成: {data.get('status')}"

        task_results = data.get("task_results", [])
        assert len(task_results) >= 3, f"工作流步骤不足 ({len(task_results)})"

        # 验证各步骤
        step_names = [tr["task_name"] for tr in task_results]
        assert "plan" in step_names, "缺少 plan 步骤"
        assert "code" in step_names, "缺少 code 步骤"
        assert "review" in step_names, "缺少 review 步骤"

        # 验证 plan 步骤完成
        plan_step = next(tr for tr in task_results if tr["task_name"] == "plan")
        assert plan_step["status"] == "completed", f"plan 步骤失败: {plan_step.get('error')}"

        # 验证 code 步骤完成
        code_step = next(tr for tr in task_results if tr["task_name"] == "code")
        assert code_step["status"] == "completed", f"code 步骤失败: {code_step.get('error')}"
        assert code_step.get("output", {}).get("code"), "code 步骤未生成代码"

        # 验证 review 步骤完成
        review_step = next(tr for tr in task_results if tr["task_name"] == "review")
        assert review_step["status"] == "completed", f"review 步骤失败: {review_step.get('error')}"

        # fix 步骤可能被跳过（如果审查通过）
        fix_step = next((tr for tr in task_results if tr["task_name"] == "fix"), None)
        if fix_step:
            assert fix_step["status"] in ("completed", "skipped"), f"fix 步骤异常: {fix_step['status']}"

        durations = {tr["task_name"]: tr["duration_ms"] for tr in task_results}
        print(
            f"✅ 场景五通过 — 步骤: {step_names}, "
            f"总耗时: {data.get('duration_ms', 0):.0f}ms"
        )


# ─── 场景六：记忆系统 ─────────────────────────────────────


class TestScenario6Memory:
    """场景六：记忆系统 — 创建和检索记忆"""

    def test_memory_create_and_search(self):
        """创建记忆并验证语义检索"""
        # 创建语义记忆
        resp1 = api_post(
            "/api/memory/create",
            {
                "content": "用户偏好使用 Python 3.11+ 和类型注解",
                "type": "semantic",
                "importance": 0.8,
            },
            timeout=10,
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert body1["status"] == "ok"
        assert body1["data"]["type"] == "semantic"

        # 创建情景记忆
        resp2 = api_post(
            "/api/memory/create",
            {
                "content": "上次用户让我实现了一个栈数据结构",
                "type": "episodic",
                "importance": 0.6,
            },
            timeout=10,
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["status"] == "ok"
        assert body2["data"]["type"] == "episodic"

        # 搜索记忆
        resp3 = api_post(
            "/api/memory/search",
            {"query": "用户的编程偏好", "max_results": 5},
            timeout=10,
        )
        assert resp3.status_code == 200
        body3 = resp3.json()
        assert body3["status"] == "ok"

        memories = body3["data"]
        assert len(memories) > 0, "搜索未返回任何记忆"

        # 验证搜索结果包含相关内容
        contents = [m["content"] for m in memories]
        has_relevant = any("偏好" in c or "Python" in c or "用户" in c for c in contents)
        assert has_relevant, f"搜索结果不包含相关记忆: {contents}"

        print(f"✅ 场景六通过 — 搜索返回 {len(memories)} 条记忆")

    def test_memory_stats(self):
        """验证记忆统计"""
        resp = api_get("/api/memory/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        print(f"✅ 记忆统计: {body['data']}")


# ─── 场景七：WebSocket ────────────────────────────────────


class TestScenario7WebSocket:
    """场景七：WebSocket 实时推送"""

    def test_websocket_connection(self):
        """连接 WebSocket，发送消息，验证收到实时推送"""
        try:
            import websockets
        except ImportError:
            pytest.skip("websockets 未安装: pip install websockets")

        async def _test():
            async with websockets.connect(f"ws://localhost:8001/ws") as ws:
                # 发送消息
                msg = {"event_type": "user_message", "message": "WebSocket 测试消息"}
                await ws.send(json.dumps(msg))

                # 接收事件回显
                response = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(response)
                assert data["type"] == "event"
                assert data["event_type"] == "user_message"
                assert "timestamp" in data

                # 接收 LLM 响应
                response2 = await asyncio.wait_for(ws.recv(), timeout=60)
                data2 = json.loads(response2)
                assert data2["type"] == "assistant_response"
                assert len(data2["data"]["response"]) > 0

                return data2["data"]["response"]

        result = asyncio.get_event_loop().run_until_complete(_test())
        print(f"✅ 场景七通过 — WebSocket 响应长度: {len(result)} 字符")


# ─── 场景八：Agent 列表与健康检查 ─────────────────────────


class TestScenario8HealthAndAgents:
    """场景八：系统健康检查与 Agent 状态"""

    def test_health(self):
        """健康检查端点"""
        resp = api_get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        data = body["data"]
        assert data["bus_running"] is True
        assert data["agent_loaded"] is True
        assert data["memory_initialized"] is True
        assert data["agents_registered"] >= 4
        print(f"✅ 健康检查通过 — {data['agents_registered']} 个 Agent 已注册")

    def test_agents_list(self):
        """Agent 列表端点"""
        resp = api_get("/api/agents")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

        agents = body["data"]
        agent_names = [a["name"] for a in agents]
        assert "assistant" in agent_names
        assert "planner" in agent_names
        assert "coder" in agent_names
        assert "reviewer" in agent_names

        for agent in agents:
            assert agent["status"] == "idle"
        print(f"✅ Agent 列表通过 — {agent_names}")


# ─── 主函数（直接运行模式） ───────────────────────────────


def run_all_scenarios():
    """直接运行所有场景测试并输出报告"""
    if not check_server():
        print("❌ 后端服务未启动！")
        print("请先运行: cd backend/src && python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8001")
        sys.exit(1)

    results: List[Dict[str, Any]] = []
    total_start = time.time()

    scenarios = [
        ("场景一：对话助手", TestScenario1Chat, "test_assistant_chat"),
        ("场景一b：任务提交", TestScenario1Chat, "test_task_submit"),
        ("场景二：任务规划", TestScenario2Planner, "test_planner_invoke"),
        ("场景三：代码生成", TestScenario3Coder, "test_coder_invoke"),
        ("场景四：代码审查", TestScenario4Reviewer, "test_reviewer_invoke"),
        ("场景五：完整工作流", TestScenario5Workflow, "test_workflow_execute"),
        ("场景六：记忆系统", TestScenario6Memory, "test_memory_create_and_search"),
        ("场景七：WebSocket", TestScenario7WebSocket, "test_websocket_connection"),
        ("场景八：健康检查", TestScenario8HealthAndAgents, "test_health"),
        ("场景八b：Agent列表", TestScenario8HealthAndAgents, "test_agents_list"),
    ]

    for name, cls, method in scenarios:
        start = time.time()
        try:
            instance = cls()
            getattr(instance, method)()
            duration = time.time() - start
            results.append({"name": name, "status": "PASS", "duration": duration, "error": None})
        except Exception as e:
            duration = time.time() - start
            results.append({"name": name, "status": "FAIL", "duration": duration, "error": str(e)})
            print(f"❌ {name} 失败: {e}")

    total_duration = time.time() - total_start

    # 输出报告
    print("\n" + "=" * 70)
    print("📊 场景化集成测试报告")
    print(f"   时间: {datetime.now().isoformat()}")
    print(f"   总耗时: {total_duration:.1f}s")
    print("=" * 70)

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")

    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {icon} {r['name']:25s} {r['status']:5s}  ({r['duration']:.1f}s)")
        if r["error"]:
            print(f"     └─ {r['error'][:100]}")

    print("-" * 70)
    print(f"  总计: {len(results)} 个场景, {passed} 通过, {failed} 失败")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_scenarios()
    sys.exit(0 if success else 1)

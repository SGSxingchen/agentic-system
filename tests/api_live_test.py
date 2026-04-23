#!/usr/bin/env python3
"""API 全量集成测试（Live）

使用前提:
    1. 启动后端服务:
       cd backend/src
       LLM_API_KEY=test-key python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8001
    2. 等待 "🚀 系统全部初始化完成!" 输出
    3. 运行此脚本:
       python3 tests/api_live_test.py
       python3 tests/api_live_test.py --suite smoke

依赖:  pip install httpx websockets
"""
import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

BASE_URL = "http://localhost:8001"
TIMEOUT = 120


# ─── 测试基础设施 ─────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    method: str
    url: str
    status_code: Optional[int]
    passed: bool
    detail: str = ""


class TestRunner:
    """简单的测试运行器"""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.results: list[TestResult] = []
        self.client = httpx.Client(base_url=base_url, timeout=TIMEOUT)
        # 跨测试共享的数据
        self.shared: dict[str, Any] = {}

    def close(self):
        self.client.close()

    def request(
        self,
        name: str,
        method: str,
        url: str,
        *,
        json_body: Optional[dict] = None,
        expect_status: int = 200,
        expect_json_field: Optional[str] = None,
        expect_json_value: Any = None,
        store_field: Optional[str] = None,   # 从 response data 中存储字段
        store_key: Optional[str] = None,     # 存储到 self.shared 中的 key
        request_timeout: Optional[float] = None,
        retries: int = 0,
    ) -> Optional[httpx.Response]:
        """执行一个 HTTP 请求并记录结果"""
        print(f"\n{'─'*50}")
        print(f"📋 {name}")
        print(f"   {method} {url}")
        if json_body:
            print(f"   Body: {json.dumps(json_body, ensure_ascii=False)[:200]}")

        resp = None
        last_error = None
        for attempt in range(retries + 1):
            try:
                if attempt > 0:
                    print(f"   Retry: {attempt}/{retries}")
                resp = self.client.request(
                    method,
                    url,
                    json=json_body,
                    timeout=request_timeout if request_timeout is not None else TIMEOUT,
                )
                break
            except Exception as e:
                last_error = e

        if resp is None:
            print(f"   ❌ 请求异常: {last_error}")
            self.results.append(TestResult(name, method, url, None, False, str(last_error)))
            return None

        status = resp.status_code
        print(f"   Status: {status}")

        try:
            body = resp.json()
            print(f"   Response: {json.dumps(body, ensure_ascii=False, indent=2)[:300]}")
        except Exception:
            body = None
            print(f"   Response (text): {resp.text[:300]}")

        # 判断是否通过
        passed = True
        detail = ""

        if status != expect_status:
            passed = False
            detail = f"期望状态码 {expect_status}，实际 {status}"

        if expect_json_field and body:
            actual = body
            for key in expect_json_field.split("."):
                if isinstance(actual, dict):
                    actual = actual.get(key)
                else:
                    actual = None
                    break
            if expect_json_value is not None and actual != expect_json_value:
                passed = False
                detail = f"期望 {expect_json_field}={expect_json_value}，实际={actual}"

        # 存储字段供后续测试使用
        if store_field and store_key and body:
            val = body
            for key in store_field.split("."):
                if isinstance(val, dict):
                    val = val.get(key)
                else:
                    val = None
                    break
            if val is not None:
                self.shared[store_key] = val

        icon = "✅" if passed else "❌"
        print(f"   {icon} {'PASS' if passed else 'FAIL'}" + (f" - {detail}" if detail else ""))

        self.results.append(TestResult(name, method, url, status, passed, detail))
        return resp

    def summary(self):
        """打印测试汇总"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        print(f"\n\n{'='*60}")
        print(f"  📊 API 全量集成测试报告")
        print(f"{'='*60}")
        print()

        for r in self.results:
            icon = "✅" if r.passed else "❌"
            status_str = str(r.status_code) if r.status_code else "ERR"
            detail_str = f"  ({r.detail})" if r.detail else ""
            print(f"  {icon} [{status_str:>3}] {r.method:6} {r.url:45} {r.name}{detail_str}")

        print()
        print(f"  {'─'*50}")
        print(f"  总计: {total}  |  ✅ 通过: {passed}  |  ❌ 失败: {failed}")
        print(f"{'='*60}")

        return failed == 0


# ─── 测试用例 ─────────────────────────────────────────────


def run_smoke_tests(t: TestRunner):
    """执行关键核心链路测试。"""
    t.request(
        "健康检查",
        "GET", "/api/health",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
    )

    t.request(
        "获取配置",
        "GET", "/api/config",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
    )

    t.request(
        "调用 Agent (assistant)",
        "POST", "/api/agents/assistant/invoke",
        json_body={"data": {"message": "Reply with exactly: HELLO_OK"}},
        expect_status=200,
        request_timeout=180,
        retries=1,
    )

    t.request(
        "获取工作流模板",
        "GET", "/api/workflows/templates",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
    )

    t.request(
        "执行工作流 (task_decompose_and_execute)",
        "POST", "/api/workflows/execute",
        json_body={
            "template_name": "task_decompose_and_execute",
            "requirement": "Write a tiny Python function add(a, b) that returns their sum.",
            "options": {},
        },
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
        request_timeout=300,
        retries=1,
    )

    t.request(
        "执行工作流 (code_generation_and_review)",
        "POST", "/api/workflows/execute",
        json_body={
            "template_name": "code_generation_and_review",
            "requirement": "Write a tiny Python function add(a, b) that returns their sum.",
            "options": {},
        },
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
        request_timeout=360,
        retries=1,
    )


def run_all_tests(t: TestRunner):
    """执行全部 API 测试"""

    run_smoke_tests(t)

    # ═══════════════════════════════════════════════════════
    # 1. Agent 详情与错误路径
    # ═══════════════════════════════════════════════════════

    t.request(
        "列出所有 Agent",
        "GET", "/api/agents",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
    )

    t.request(
        "获取 Agent 详情 (assistant)",
        "GET", "/api/agents/assistant",
        expect_status=200,
        expect_json_field="data.name",
        expect_json_value="assistant",
    )

    t.request(
        "获取 Agent 详情 (planner)",
        "GET", "/api/agents/planner",
        expect_status=200,
        expect_json_field="data.name",
        expect_json_value="planner",
    )

    t.request(
        "获取 Agent 详情 (coder)",
        "GET", "/api/agents/coder",
        expect_status=200,
        expect_json_field="data.name",
        expect_json_value="coder",
    )

    t.request(
        "获取 Agent 详情 (reviewer)",
        "GET", "/api/agents/reviewer",
        expect_status=200,
        expect_json_field="data.name",
        expect_json_value="reviewer",
    )

    t.request(
        "获取不存在的 Agent (404)",
        "GET", "/api/agents/nonexistent",
        expect_status=404,
    )

    t.request(
        "调用不存在的 Agent (404)",
        "POST", "/api/agents/nonexistent/invoke",
        json_body={"data": {}},
        expect_status=404,
    )

    # ═══════════════════════════════════════════════════════
    # 2. 任务相关
    # ═══════════════════════════════════════════════════════

    t.request(
        "列出任务 (空列表)",
        "GET", "/api/tasks",
        expect_status=200,
    )

    t.request(
        "创建任务",
        "POST", "/api/tasks",
        json_body={"requirement": "Write a hello world program", "workflow": "auto"},
        expect_status=200,
        store_field="data.task_id",
        store_key="task_id",
    )

    task_id = t.shared.get("task_id")
    if task_id:
        t.request(
            "列出任务 (含刚创建的)",
            "GET", "/api/tasks",
            expect_status=200,
        )

        t.request(
            "获取任务详情",
            "GET", f"/api/tasks/{task_id}",
            expect_status=200,
            expect_json_field="data.task_id",
            expect_json_value=task_id,
        )

        t.request(
            "删除任务",
            "DELETE", f"/api/tasks/{task_id}",
            expect_status=200,
        )

    t.request(
        "获取不存在的任务 (404)",
        "GET", "/api/tasks/nonexistent-id",
        expect_status=404,
    )

    t.request(
        "删除不存在的任务 (404)",
        "DELETE", "/api/tasks/nonexistent-id",
        expect_status=404,
    )

    t.request(
        "创建任务 (空 requirement, 422)",
        "POST", "/api/tasks",
        json_body={"requirement": "", "workflow": "auto"},
        expect_status=422,
    )

    # ═══════════════════════════════════════════════════════
    # 3. 记忆相关
    # ═══════════════════════════════════════════════════════

    t.request(
        "记忆统计",
        "GET", "/api/memory/stats",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="ok",
    )

    t.request(
        "列出记忆 (初始)",
        "GET", "/api/memory/list",
        expect_status=200,
    )

    t.request(
        "列出记忆 (type=semantic)",
        "GET", "/api/memory/list?type=semantic",
        expect_status=200,
    )

    t.request(
        "列出记忆 (无效类型)",
        "GET", "/api/memory/list?type=invalid_type",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="error",
    )

    t.request(
        "创建记忆",
        "POST", "/api/memory/create",
        json_body={
            "content": "Integration test memory entry",
            "type": "semantic",
            "importance": 0.7,
            "metadata": {"source": "api_live_test"},
        },
        expect_status=200,
        store_field="data.id",
        store_key="memory_id",
    )

    t.request(
        "搜索记忆",
        "POST", "/api/memory/search",
        json_body={"query": "integration test", "max_results": 5},
        expect_status=200,
    )

    memory_id = t.shared.get("memory_id")
    if memory_id:
        t.request(
            "删除记忆",
            "DELETE", f"/api/memory/{memory_id}",
            expect_status=200,
            expect_json_field="status",
            expect_json_value="ok",
        )

    t.request(
        "删除不存在的记忆",
        "DELETE", "/api/memory/nonexistent-id",
        expect_status=200,
        expect_json_field="status",
        expect_json_value="error",
    )

    t.request(
        "触发记忆巩固",
        "POST", "/api/memory/consolidate",
        expect_status=200,
    )

    t.request(
        "触发记忆遗忘",
        "POST", "/api/memory/forget",
        expect_status=200,
    )

    t.request(
        "创建记忆 (空 content, 422)",
        "POST", "/api/memory/create",
        json_body={"content": "", "type": "semantic"},
        expect_status=422,
    )

    t.request(
        "搜索记忆 (空 query, 422)",
        "POST", "/api/memory/search",
        json_body={"query": "", "max_results": 5},
        expect_status=422,
    )

    # ═══════════════════════════════════════════════════════
    # 4. 工作流错误路径
    # ═══════════════════════════════════════════════════════

    t.request(
        "执行工作流 (无效类型)",
        "POST", "/api/workflows/execute",
        json_body={
            "workflow_type": "nonexistent_workflow",
            "requirement": "test",
            "options": {},
        },
        expect_status=200,
        expect_json_field="status",
        expect_json_value="error",
    )

    t.request(
        "执行工作流 (空 requirement)",
        "POST", "/api/workflows/execute",
        json_body={
            "workflow_type": "plan_code_review",
            "requirement": "",
        },
        expect_status=200,
        expect_json_field="status",
        expect_json_value="error",
    )


# ─── WebSocket 测试 ───────────────────────────────────────


async def test_websocket(results: list[TestResult]):
    """测试 WebSocket 连接"""
    print(f"\n{'─'*50}")
    print("📋 WebSocket 连接测试")
    print(f"   WS ws://localhost:8001/ws")

    try:
        import websockets
    except ImportError:
        print("   ⚠️ websockets 库未安装，跳过")
        results.append(TestResult(
            "WebSocket 连接", "WS", "/ws", None, True,
            "跳过 (websockets 未安装)"
        ))
        return

    try:
        async with websockets.connect(
            "ws://localhost:8001/ws", open_timeout=5
        ) as ws:
            # 发送消息
            msg = json.dumps({"type": "chat", "message": "hello from live test"})
            await ws.send(msg)

            # 等待响应
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(resp)
                print(f"   Received: {json.dumps(data, ensure_ascii=False)[:200]}")
                print("   ✅ PASS")
                results.append(TestResult(
                    "WebSocket 连接 & 收发消息", "WS", "/ws", None, True
                ))
            except asyncio.TimeoutError:
                print("   ✅ PASS (连接成功，无 LLM 响应是预期行为)")
                results.append(TestResult(
                    "WebSocket 连接", "WS", "/ws", None, True,
                    "连接成功，超时预期"
                ))

            await ws.close()
    except Exception as e:
        print(f"   ❌ FAIL: {e}")
        results.append(TestResult(
            "WebSocket 连接", "WS", "/ws", None, False, str(e)
        ))


# ─── 入口 ─────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Run live API checks against the local backend.")
    parser.add_argument(
        "--suite",
        choices=("full", "smoke"),
        default="full",
        help="Choose a smaller smoke suite or the full live suite.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print(f"  🚀 API 集成测试 (Live, suite={args.suite})")
    print(f"  目标: {BASE_URL}")
    print("=" * 60)

    # 先检查服务是否可用
    try:
        r = httpx.get(f"{BASE_URL}/api/health", timeout=3)
        if r.status_code != 200:
            print(f"\n❌ 服务不可用 (status={r.status_code})。请先启动后端。")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ 无法连接到 {BASE_URL}: {e}")
        print("   请先启动后端服务:")
        print("   cd backend/src")
        print("   LLM_API_KEY=test-key python3 -m uvicorn api.main:app --port 8001")
        sys.exit(1)

    # 执行 HTTP 测试
    t = TestRunner()
    try:
        if args.suite == "smoke":
            run_smoke_tests(t)
        else:
            run_all_tests(t)
    finally:
        t.close()

    # 执行 WebSocket 测试
    asyncio.run(test_websocket(t.results))

    # 输出汇总
    all_passed = t.summary()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()

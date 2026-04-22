# 场景测试：Git 仓库分析 CLI 工具

**测试日期：** 2026-03-25
**测试人角色：** DevOps 工程师
**测试目标：** 验证多智能体协作系统能否完成一个完整的 CLI 工具开发需求

---

## 1. 环境准备

### 1.1 配置修改
- **文件：** `backend/src/config.yaml`
- **LLM Provider:** openai (兼容接口)
- **Model:** claude-sonnet-4-20250514
- **Base URL:** http://156.238.228.118:8317/v1

### 1.2 后端启动
```bash
cd backend/src && python3 -m uvicorn api.main:app --port 8005
```
- **状态：** ✅ 成功启动
- **耗时：** ~3 秒

---

## 2. Planner 规划测试

### 请求
```
POST /api/agents/planner/invoke
{
  "data": {
    "requirement": "我需要开发一个 Python CLI 工具来分析 Git 仓库。功能：1) 统计每个作者的提交数和代码行数变化(增/删) 2) 按周/月生成活跃度报告(提交频率热力图) 3) 分析文件修改热度(最常被修改的Top20文件) 4) 检测大文件(>1MB)和潜在敏感信息泄露(API key、密码等正则匹配)。使用 click 做 CLI，gitpython 读取仓库。请分解任务。"
  }
}
```

> **注意：** API 接收 `data.requirement` 字段，而非 `message`。最初用 `{"message": "..."}` 返回了 `{"error": "缺少需求描述"}`，改为正确字段名后成功。

### 响应
- **HTTP 状态：** 200
- **结果：** ✅ 成功
- **生成子任务数：** 13 个
- **耗时：** ~15 秒

### 子任务列表

| # | 任务名 | 分配 Agent | 优先级 | 依赖 |
|---|--------|-----------|--------|------|
| 1 | design_cli_structure | planner | 1 | - |
| 2 | setup_project_structure | coder | 2 | design_cli_structure |
| 3 | implement_git_analyzer_core | coder | 3 | setup_project_structure |
| 4 | implement_author_stats | coder | 4 | implement_git_analyzer_core |
| 5 | implement_activity_reporter | coder | 4 | implement_git_analyzer_core |
| 6 | implement_file_hotness_analyzer | coder | 4 | implement_git_analyzer_core |
| 7 | implement_security_scanner | coder | 4 | implement_git_analyzer_core |
| 8 | implement_cli_commands | coder | 5 | 4个模块 |
| 9 | implement_report_generator | coder | 6 | implement_cli_commands |
| 10 | write_unit_tests | tester | 7 | implement_report_generator |
| 11 | write_integration_tests | tester | 8 | write_unit_tests |
| 12 | code_review_and_optimization | reviewer | 9 | write_integration_tests |
| 13 | create_documentation | coder | 10 | code_review_and_optimization |

**评估：** 任务分解合理，具有正确的依赖关系和优先级层次。将并行可执行的任务（4-7）设置了相同优先级，体现了对执行效率的考量。

---

## 3. Coder 编码测试

### 3.1 Git 数据提取层

**请求任务：** 实现 GitRepoAnalyzer 类（5个方法 + 类型注解 + 错误处理）

**响应：**
- **HTTP 状态：** 200
- **结果：** ✅ 成功
- **输出文件：** `src/git_analyzer/repo_analyzer.py`
- **语言：** Python
- **耗时：** ~20 秒

**代码质量评估：**
- ✅ 完整的类型注解（Dict, List, Optional, Tuple）
- ✅ 详细的 docstring
- ✅ 合理的错误处理（ValueError, InvalidGitRepositoryError, RuntimeError）
- ✅ 合并提交跳过逻辑（`len(commit.parents) > 1`）
- ✅ 二进制文件过滤（`_is_text_file` 辅助方法）
- ✅ 额外附赠 `get_repo_info()` 方法
- ⚠️ `get_commits()` 将全部提交加载到内存，大仓库可能有性能问题

### 3.2 安全扫描模块

**请求任务：** 实现 SecurityScanner 类 + SecurityIssue dataclass + 10+ 正则模式

**响应：**
- **HTTP 状态：** 200
- **结果：** ✅ 成功
- **输出文件：** `src/security/scanner.py`
- **语言：** Python
- **耗时：** ~25 秒

**代码质量评估：**
- ✅ SecurityIssue 使用 @dataclass 装饰器
- ✅ Severity 和 IssueType 使用 Enum
- ✅ 12 种敏感信息检测正则（超出要求的 10 种）
  - AWS Access Key, AWS Secret Key, GitHub Token, Password, Private Key
  - Database URL, API Key, JWT Token, Slack Token, Email Credential, Credit Card
- ✅ 大文件严重程度分级逻辑
- ✅ 文件跳过逻辑（.git, node_modules, __pycache__ 等）
- ✅ 多编码支持（utf-8 → latin-1 fallback）
- ✅ `generate_report()` 综合扫描方法
- ⚠️ 裸 `except` 过于宽泛

### 3.3 CLI 入口

**请求任务：** 用 click 实现 4 个 CLI 命令 + 多格式输出

**响应：**
- **HTTP 状态：** 200
- **结果：** ✅ 成功
- **输出文件：** `git_analyzer/cli.py`
- **语言：** Python
- **耗时：** ~20 秒

**代码质量评估：**
- ✅ 4 个命令完整实现：stats, hotspots, security, report
- ✅ click.DateTime 时间参数支持
- ✅ click.Choice 格式选择
- ✅ report 命令支持 `--include-stats/--no-stats` 等开关
- ✅ 进度条显示（click.progressbar）
- ✅ 安全扫描发现高危问题时设置非零退出码
- ✅ Windows 编码兼容处理
- ⚠️ 命令函数内引用了尚未实现的模块（formatters, report 等）

---

## 4. Reviewer 审查测试

### 请求
将三个模块的精简版代码合并提交审查。

### 响应
- **HTTP 状态：** 200
- **结果：** ✅ 审查完成
- **通过：** ❌ 未通过 (approved: false)
- **严重程度：** 9/10
- **耗时：** ~15 秒

### 发现的问题

| # | 类型 | 严重程度 | 描述 |
|---|------|---------|------|
| 1 | security | critical | 路径遍历攻击防护缺失 |
| 2 | security | major | repo_path 输入验证不足 |
| 3 | bug | critical | SecurityScanner 缺少 _init_secret_patterns() 等方法实现 |
| 4 | bug | critical | GitRepoAnalyzer._is_text_file() 方法未实现 |
| 5 | logic | critical | CLI 命令函数为空实现 |
| 6 | performance | major | get_commits() 全量加载到内存 |
| 7 | style | major | 裸 except 子句掩盖错误信息 |
| 8 | security | major | scan_secrets() 未限制文件大小 |

### 改进建议
1. 实现缺失的方法
2. 添加路径验证防止目录遍历
3. 实现 CLI 命令功能
4. 使用生成器分批处理
5. 改进异常处理
6. 添加文件大小限制
7. 输入参数验证和清理
8. 添加日志记录功能

**评估：** Reviewer 审查非常严谨。问题 3-5 是因为提交了精简版代码（完整实现在 Coder 的原始输出中），属于测试方法局限。问题 1、2、6、7、8 是真实有效的代码质量改进建议。

---

## 5. 工作流测试

### 请求
```
POST /api/workflows/execute
{
  "workflow_type": "full_pipeline",
  "requirement": "用 Python 实现一个 FileWatcher 类，使用 watchdog 库监控指定目录的文件变化（创建/修改/删除），支持文件类型过滤和回调注册，包含去抖动机制（同一文件500ms内多次变化只触发一次）"
}
```

> **注意：** 工作流 API 使用 `workflow_type` + `requirement` 字段，非 `template_name` + `input`。

### 响应
- **HTTP 状态：** 200
- **结果：** ✅ 成功启动
- **Workflow ID：** `38ba6727-b91a-4d61-b14e-f9faa8b0e846`
- **工作流类型：** full_pipeline
- **步骤：** planner → coder → reviewer → tester

**评估：** 工作流以异步方式启动，通过事件总线编排各 Agent 的执行顺序。当前实现为简化版（只发送到第一个 Agent），完整编排需要 WorkflowOrchestrator（标记为 TODO）。

---

## 6. 总结

### 测试结果总览

| 步骤 | 端点 | 状态 | HTTP 码 | 备注 |
|------|------|------|---------|------|
| Planner 规划 | POST /api/agents/planner/invoke | ✅ 成功 | 200 | 生成13个子任务 |
| Coder 编码 #1 | POST /api/agents/coder/invoke | ✅ 成功 | 200 | GitRepoAnalyzer |
| Coder 编码 #2 | POST /api/agents/coder/invoke | ✅ 成功 | 200 | SecurityScanner |
| Coder 编码 #3 | POST /api/agents/coder/invoke | ✅ 成功 | 200 | CLI 入口 |
| Reviewer 审查 | POST /api/agents/reviewer/invoke | ✅ 成功 | 200 | 未通过,8个问题 |
| Workflow 执行 | POST /api/workflows/execute | ✅ 成功 | 200 | 异步启动 |

### 系统表现评价

**优点：**
1. **API 稳定可靠** — 全部 6 次请求均返回 200，无 500 错误
2. **LLM 调用成功率 100%** — 通过 OpenAI 兼容接口调用 Claude Sonnet 无异常
3. **结构化输出质量高** — JSON 解析成功率 100%，未触发容错逻辑
4. **Planner 分解合理** — 13 个子任务有清晰的依赖关系和优先级
5. **Coder 代码质量好** — 类型注解、docstring、错误处理俱全
6. **Reviewer 审查严格** — 能识别安全漏洞、性能问题、代码风格问题
7. **响应时间可接受** — 单次请求 15-25 秒，未超时

**发现的问题：**
1. **API 字段命名需要文档** — `requirement` vs `message` 不直观，需要查看源码才能确定
2. **Coder 各模块独立生成** — 不共享上下文，可能导致接口不一致（如 CLI 引用了不存在的 formatters 模块）
3. **Workflow 编排简化版** — 目前只发送到第一个 Agent，完整流水线编排未实现
4. **缺少状态查询接口** — 异步工作流启动后无法查询执行进度

**改进建议：**
1. 为 Agent invoke 接口添加统一的 `message` 字段支持
2. 实现 Coder 的上下文传递机制（将前序 Coder 输出作为后续上下文）
3. 完成 WorkflowOrchestrator 实现
4. 添加 `GET /api/workflows/{workflow_id}/status` 查询接口
5. 考虑添加 SSE/WebSocket 实时推送工作流进度

---

**测试结论：** ✅ 系统核心功能（Agent 调用、LLM 集成、结构化输出）运行正常，能完成基本的"规划-编码-审查"协作流程。工作流编排和上下文传递机制待完善。

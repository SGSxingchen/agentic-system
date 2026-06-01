# 实测 Bug 修复设计 — 2026-05-28 (Round 2)

> PR #31 合入 main 后，用户在服务器（156.238.228.118:3001）实测聊天室与对话面板，暴露 6 个新问题。本 spec 全部修。

**版本**: v1.0
**日期**: 2026-05-28
**状态**: 设计阶段
**前置**: PR #31 已合入 main

---

## 0. 问题清单

| 编号 | 问题 | 严重度 |
|---|---|---|
| **A22** | `agent_manager` REST 路由层硬保护未拆（A10 漏） | 高 |
| **A23** | `token_budget` 默认 120000 太低，且前端不可改 | 高 |
| **A24** | 没有 `edit_file` 工具，子 Agent 改大文件 blocked | 高 |
| **A25** | TodoBanner 挡住消息流，UI 一坨 | 中 |
| **A26** | 房间内 host 卡住时不会 @ 别人协助 | 中 |
| **A27** | 消息时间排序错乱（用户消息可能显示在 agent 回复下方） | 高 |

---

## 1. A22 — `agent_manager` REST 保护残留

### 1.1 现状
PR #31 A10 拆掉了 `agent_management.py` **工具层**的三段式审批，但 **REST 路由层**还有两道独立硬墙：

- `routes/agents.py:60` `PROTECTED_AGENT_NAMES = {*DEFAULT_BINDABLE_AGENT_ROLES, "agent_manager", "persona_evolution"}` — DELETE 用
- `routes/agents.py:786-787` PUT `/api/agents/agent_manager` 硬编码拒绝："agent_manager 只能通过受控 agent_manager 工具链修改"
- `routes/agents.py:908-909` MCP import 路径同样的拒绝

这违背 A10 的"调用即生效 + 审计代替审批"哲学，是 PR #31 的盲区。

### 1.2 修法
**全部删除**：
- `routes/agents.py:60-64` 删除 `PROTECTED_AGENT_NAMES = {...}` 整段
- `routes/agents.py:786-787` 删除 PUT 里的 `if name == "agent_manager":` 硬拒绝
- `routes/agents.py:908-909` 删除 MCP import 路径同样拒绝
- `routes/agents.py:962` 删除 DELETE 里的 `if name in PROTECTED_AGENT_NAMES:`
- `DEFAULT_BINDABLE_AGENT_ROLES` 含义保留（仅用于"可绑 persona 的 Agent 列表"），不再用于权限拦截

### 1.3 替代审计
保留写操作 `structlog.info("config_change", ...)`（A10 已加），日志可追溯。

### 1.4 测试
- `test_put_agent_manager_no_longer_blocked`：PUT 改 agent_manager prompt 应返回 200
- `test_delete_protected_agent_no_longer_blocked`：DELETE agent_manager 应允许（实际生产中用户不会删，但 API 不该拦）

---

## 2. A23 — `token_budget` 默认值低 + 前端不可改

### 2.1 现状
- `config/agents.yaml:41` planner `token_budget: 120000` — 用户实测就被这个挡住
- `config/agents.yaml:245` 其他 Agent `token_budget: 200000`
- 前端 `AgentPanel.tsx` Agent 编辑表单**没有 token_budget 字段**，用户改不动

### 2.2 修法

**A. 默认值上调**：
- planner: 120000 → 300000（聊天室主持人，需要看长上下文）
- 其他 Agent 维持 200000 或上调到 300000（统一）

**B. 前端 AgentPanel 增加字段**：
- 在 Agent 编辑表单加 `token_budget` 数字输入（min=10000，max=2000000，step=10000）
- 字段说明："单次 Agent 调用的累计 token 预算上限。超出会拒绝继续。聊天室主持人建议 300000+"
- 默认值：从 yaml 读，没有就显示 placeholder "继承全局"

**C. system.yaml 加全局默认**：
```yaml
agent_defaults:
  token_budget: 300000  # 默认值，单 Agent yaml 可覆盖
```
读取时：Agent yaml 有就用 Agent 自己的，没有则取 system.yaml 全局，再没有就 fallback 300000。

### 2.3 测试
- `test_token_budget_default_300k`：未配置 Agent token_budget 时，agent 实例的 `_token_budget=300000`
- `test_token_budget_override_per_agent`：planner.token_budget 改 500000，agent 实例确实是 500000
- 前端：tsc + build 验证表单字段类型

---

## 3. A24 — `edit_file` 工具缺失

### 3.1 现状
当前文件操作工具：
- `read_file`：默认 8000 字节上限
- `write_file`：必须传完整文件内容
- 子 Agent 想改 39KB 文件中的 1 行只能"读全文 → 改 → 写全文"，但 read 截断 → 不敢写 → blocked

### 3.2 修法（Claude Code 范式）

新工具 `edit_file`：

```python
class EditFileCapability(CapabilityBase):
    """精确字符串替换。最适合改大文件中的某段。
    
    什么时候用：
      - 改大文件（>8KB）的某行/某段，避免读全文
      - 你已经知道要替换的精确文本
    
    什么时候不用：
      - 创建新文件 → 用 write_file
      - 全文重写 → 用 write_file
    
    参数：
      old_string: 必须完全匹配（含缩进/换行）。在文件中只能出现一次（除非 replace_all=True）
      new_string: 替换为此字符串
      replace_all: 替换所有匹配（默认 False）
    """
    name = "edit_file"
    parameters = {
        "file_path": {"type": "string", "required": True},
        "old_string": {"type": "string", "required": True},
        "new_string": {"type": "string", "required": True},
        "replace_all": {"type": "boolean", "default": False},
    }
```

实现要点：
- 校验 file_path 在 workspace_root 下（用现有 `_safety.get_workspace_root`）
- old_string 在文件中必须唯一（除非 replace_all=True），否则报错并返回所有出现位置
- new_string 不能等于 old_string
- 失败时返回友好错误："要替换的文本未找到 / 出现 N 次（请加更多上下文使其唯一）"

### 3.3 同时增强 `read_file`
加 `offset` / `limit` 参数（行级），让 Agent 能分段读：
```python
parameters = {
    "file_path": {"type": "string", "required": True},
    "offset": {"type": "integer", "default": 0, "description": "起始行号 (0-based)"},
    "limit": {"type": "integer", "default": 200, "description": "读取行数，默认 200，最大 2000"},
}
```
不传 offset/limit 时维持现有行为（保持向后兼容）。

### 3.4 注册
- 在 capability registry 自动注册
- 默认挂给所有 Agent（基础包，符合 A4 哲学）
- agents.yaml 里 coder/agent_creator 等如果显式列了 tools 就加 `edit_file` 进去

### 3.5 测试
- `test_edit_file_unique_match_replaces`
- `test_edit_file_multiple_matches_errors_unless_replace_all`
- `test_edit_file_outside_workspace_blocked`
- `test_edit_file_old_equals_new_errors`
- `test_read_file_offset_limit_returns_slice`
- `test_read_file_offset_beyond_eof_returns_empty`

---

## 4. A25 — TodoBanner 挡对话

### 4.1 现状
A17 加的 `TodoBanner` 默认展开占据消息流上方大块空间，房间一开始没 todo 也占位。

### 4.2 修法

**A. 默认折叠**：
- 房间无 todo 时 banner 完全 hidden（`todos.length === 0` 直接 `return null`）
- 有 todo 时显示一个 chip：`📋 5 个待办 / 2 进行中 / 8 完成`，点击展开完整列表

**B. 折叠态高度受限**：
- 折叠时高度 ≤ 32px
- 展开时 max-height 200px + 内部滚动

**C. 关闭按钮**：
- 展开态右上角 ✕，点击折叠（保留状态在 useState）

**D. 移到右侧栏（可选，用户决定）**：
- 当前在消息流顶部 banner
- 改成右侧栏一个 panel（与成员列表并列），完全不占消息流空间
- spec 写**两种方案各一段**，用户决定后实施

### 4.3 测试
- `test_TodoBanner_renders_null_when_empty`
- 视觉验证：折叠/展开切换流畅

---

## 5. A26 — host 卡住不会 @ 别人

### 5.1 现状
聊天室里 planner 作为 host 自己卡住或方向错时，不会主动调 `chatroom_dispatch` 让 reviewer/coder 帮看。A14 协作覆盖前缀里"看到事情自己能解决就直接派发"是有的，但**没说"卡住时也要 @ 别人"**。

### 5.2 修法
在 `CHATROOM_COLLABORATION_PROTOCOL` 常量（`core/prompts.py`）里追加：

```
【困境处理】
- 你不确定该怎么回答 → 调 chatroom_dispatch 让相关专家发言（reviewer/coder/research/...）
- 用户的需求超出你的角色 → @ 合适的成员，不要硬撑
- 工具调用失败/被拒绝 → 不要装作没事继续，明确说"我刚才尝试 X 失败了，原因是 Y"
- 看到错误信息 → 直接念出来给用户，不要编造解释

行为示例（卡住时）：
✅ "这个我不确定，让 reviewer 看看代码" → chatroom_dispatch([reviewer])
❌ 自己瞎猜一个答案
```

### 5.3 测试
单元测试不容易写（需要触发"卡住"场景），改用：
- `test_protocol_includes_dilemma_handling`：grep 协作前缀含 "困境处理" / "chatroom_dispatch" 关键词
- 手工验证：在房间里问一个 planner 不擅长的技术细节，观察是否 @ coder

---

## 6. A27 — 消息时间排序错乱

### 6.1 现状
用户报告"我发的消息在回复下面"。grep `frontend/src/components/ChatroomPanel.tsx` 找不到 messages 的 `sort` 调用——意味着 WS 消息事件直接 `push` 进 state 数组，**顺序由到达顺序决定**。

实际场景：
1. 用户 POST 消息 → 后端立即在房间里写 user 消息（含 created_at）
2. 后端立刻派 speaking task → agent placeholder 消息也写入（created_at 略晚）
3. WS 推送 `chatroom_message_added` 时如果**先到 placeholder 后到 user**，前端就显示成 agent 在用户上方
4. 或者后端写 user 消息和 placeholder 是同一毫秒，WS 推送顺序乱

### 6.2 修法

**A. 后端保证 created_at 单调递增**：
- `chatroom.py: ChatroomStore.add_message` 使用 `datetime.utcnow()`，但同一毫秒可能重复
- 改为 `_last_message_time` 跟踪，新消息至少比上一条晚 1ms
- 或用 monotonically increasing `seq` 字段（更稳）

**B. 前端按 created_at 排序**：
- `ChatroomPanel.tsx` 渲染 messages 时 `.sort((a, b) => a.created_at - b.created_at)`
- 也可以按 `seq` 排（更稳）
- 渲染逻辑：`const sortedMessages = useMemo(() => [...messages].sort(byCreatedAt), [messages])`

**C. WS 事件去重**：
- 已有 message_id，dedupe 时按 id 判重，不要按内容
- 收到 `chatroom_message_added` 时如果 id 已存在则忽略（防止重复推送导致顺序错乱）

### 6.3 测试

后端：
- `test_messages_have_strictly_monotonic_created_at`：连续 add_message 三条，断言 t1 < t2 < t3

前端：
- `test_chatroom_messages_sorted_by_created_at`：故意乱序传入 messages props，渲染后 DOM 顺序应正确
- 视觉验证：在房间用户连发 3 条消息夹 agent 回复，顺序对

---

## 7. 实施顺序与依赖

```
Phase A — 后端 (A22 / A23 / A24 / A26 / A27后端)
  ├── A22 删除 PROTECTED_AGENT_NAMES + agent_manager 硬拒绝
  ├── A23 token_budget 默认值 + system.yaml 全局 + Agent 读取 fallback
  ├── A24 edit_file 工具 + read_file offset/limit
  ├── A26 协作前缀加困境处理段
  └── A27.A 后端 monotonic created_at

Phase B — 前端 (A23 / A25 / A27前端)
  ├── A23 AgentPanel 加 token_budget 字段
  ├── A25 TodoBanner 折叠 + 空态隐藏
  └── A27.B 前端按 created_at 排序

Phase C — 测试 + 文档
  └── 各项 unit + 集成 + CLAUDE.md 同步
```

A22/A23/A24 后端独立可并行；A25/A27前端独立可并行。

---

## 8. 红线（保持 PR #31 一致）

- ✅ 不删 / 重命名 agents.yaml 现有条目（修改字段值 OK）
- ✅ 不动 main 分支（在新 feature 分支上）
- ✅ 不绕 git hooks
- ✅ 不加新 Python 依赖

---

**文档完毕。**

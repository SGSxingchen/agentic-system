# Private Assistant Memory Lite 设计

日期: 2026-04-26

## 背景

当前记忆系统已经有 `MemoryStore`、`MemoryFormation`、`MemoryRetriever`、REST API 和前端面板，但主要能力仍是手动创建与简单关键词召回。它可以保存记忆，却还不像私人助理那样从日常对话中自动沉淀长期信息，也缺少可解释的召回、近似去重、摘要来源追踪和稳定的 prompt 注入格式。

AstrBot 的 `livingmemory` 插件提供了有价值的参考：自动对话摘要、检索用摘要与注入用摘要分离、source window、重要性与遗忘、混合检索和去重。但本项目场景不是群聊/人格插件，也不需要 session/persona 隔离。本设计只吸收其中适合私人助理长期记忆层的部分。

## 目标

建设一个项目内置的全局私人助理记忆层，使 Assistant 能自动形成、巩固、检索并注入长期记忆。

核心目标:

- 自动从用户与 Assistant 的对话中提炼值得长期保存的信息。
- 记忆面向“私人助理”，不限于代码写作，可覆盖偏好、事实、项目背景、决策、待办、经验。
- 不做会话隔离。所有记忆进入全局个人记忆池，`session_id` 只作为来源追踪，不参与默认过滤。
- 检索结果可解释，能说明相关性、重要性、最近访问、去重等信号。
- prompt 注入使用简洁的助理上下文，不把原始长对话直接塞回模型。
- 保持实现轻量，复用现有 `MemoryStore`、`MemoryFormation`、`MemoryRetriever`、API 和 MemoryPanel。

非目标:

- 不移植 AstrBot 插件生命周期、群聊解析、persona/session 隔离、SQLite FTS、FAISS、完整 WebUI。
- 不把每条消息都保存成长期记忆。
- 不让记忆系统阻塞主聊天链路；摘要失败时聊天仍正常返回。

## 记忆模型

继续使用现有三类 `MemoryType`:

- `episodic`: 事件、阶段性经历、一次性上下文。
- `semantic`: 长期事实、偏好、稳定约束。
- `procedural`: 可复用经验、工作方式、偏好的处理模式。

在 `metadata` 中新增结构化字段:

| 字段 | 说明 |
|------|------|
| `memory_kind` | `preference` / `fact` / `project_context` / `decision` / `todo` / `experience` / `other` |
| `topics` | 主题列表，用于检索和前端展示 |
| `key_facts` | 从来源对话抽取的关键事实 |
| `canonical_summary` | 面向检索的标准摘要，稳定、去口语化 |
| `assistant_context` | 面向 prompt 注入的简短上下文 |
| `confidence` | 摘要可信度，0-1 |
| `summary_quality` | 摘要质量，0-1 |
| `source_window` | 来源消息范围、消息数量、时间范围 |
| `source` | `chat_reflection` / `manual` / `agent_reflection` 等 |
| `source_agent` | 产生记忆的 Agent 名称，默认 `assistant` |
| `schema_version` | 当前为 `private_memory_v1` |

`content` 优先保存 `canonical_summary`，这样现有 store 和检索逻辑无需大改。`assistant_context` 留在 metadata 中用于注入。

## 数据流

### 1. 聊天前召回

Assistant 收到用户消息后，用用户当前输入检索全局记忆池。召回结果不按 session 过滤，只按相关性、重要性和质量排序。

召回后生成一个简洁的 `[长期记忆]` 块注入系统提示词。每条注入内容使用 `assistant_context`，没有时回退到 `canonical_summary` 或 `content`。注入内容限制条数和字符数，避免 prompt 被记忆挤占。

### 2. 聊天后反思

Assistant 回复完成后，把本轮 `user` 与 `assistant` 内容追加到轻量对话缓冲。缓冲达到阈值后异步触发反思摘要。

摘要窗口记录 `source_window`，包括起止消息索引、起止时间、消息数量和摘要触发原因。摘要成功后推进窗口游标，失败不影响聊天返回。

### 3. 结构化摘要

摘要器接收最近若干轮对话，输出一组候选记忆。每条候选记忆包含:

- `memory_type`
- `memory_kind`
- `canonical_summary`
- `assistant_context`
- `topics`
- `key_facts`
- `importance`
- `confidence`
- `summary_quality`

摘要器优先使用当前 LLM 客户端。LLM 不可用或返回非法 JSON 时，系统记录失败并跳过本次形成，不写入低质量记忆。JSON 解析需要支持去除 markdown fence、从文本中提取 JSON 片段和基本字段校验。

### 4. 记忆形成与巩固

候选记忆通过 `MemoryFormation` 写入 store。写入前先执行轻量去重:

- 标准化摘要完全相同: 合并为已有记忆，提升重要性与访问计数。
- Jaccard 相似度过高且 `memory_kind` 相同: 合并或跳过新记忆。
- 新记忆质量低于阈值: 丢弃。

巩固时保留旧记忆的创建时间，合并 topics/key_facts/source_window，并把重要性缓慢上调到 1.0 上限。

### 5. 检索排序与解释

`MemoryRetriever` 保持轻量实现，不引入 BM25/FAISS。排序使用:

- store 粗筛排名作为基础相关性。
- query 与 `content`、`canonical_summary`、`topics`、`key_facts` 的词面重叠。
- 重要性 `importance`。
- 最近性使用 `max(created_at, last_accessed)`，不是只看创建时间。
- 访问频率使用归一化 `access_count`。
- 近似重复结果使用 Jaccard 去重。

API 和 `memory_search` 工具返回时附带瞬时 `retrieval` 信息:

- `score`
- `breakdown.relevance`
- `breakdown.importance`
- `breakdown.recency`
- `breakdown.frequency`
- `deduped_similar_ids`

这些字段不持久化进 store，避免检索副作用污染长期数据。

### 6. 遗忘策略

现有 `forget()` 保留，但调整为更适合私人助理:

- 低重要性、低质量、长期未访问的记忆可以遗忘。
- 高重要性记忆不因时间久远被直接删除。
- `todo` 类记忆默认不自动遗忘，除非未来显式支持完成状态。

## 组件边界

新增或调整组件:

- `ConversationMemoryBuffer`: 管理全局对话缓冲、窗口游标和摘要触发判断。
- `MemoryProcessor`: 把对话窗口转换为结构化候选记忆，负责 prompt、JSON 解析和字段质量校验。
- `MemoryFormation`: 增加结构化创建与近似去重入口，保留现有手动创建 API。
- `MemoryRetriever`: 增加 metadata-aware 评分、最近访问时间排序、去重与检索解释。
- `AssistantAgent` / WebSocket chat flow: 接入聊天前召回与聊天后反思。
- `MemoryPanel`: 展示 `memory_kind`、topics、summary quality 和检索评分解释。

## 错误处理

- 摘要失败只记录日志，不影响聊天响应。
- LLM 返回非法 JSON 时最多修复一次，仍失败则跳过写入。
- 空摘要、低质量摘要、低置信度事实不写入长期记忆。
- 检索解释只作为响应层字段，不持久化，避免污染 metadata。
- 自动形成记忆需要限制窗口大小与候选数量，避免一次对话生成过多记忆。

## 测试策略

按 TDD 实现，先补失败测试再写生产代码。

单元测试重点:

- `MemoryProcessor` 能解析合法 JSON、剥离 markdown fence，并拒绝低质量候选。
- 结构化记忆写入时保留 `canonical_summary`、`assistant_context`、`source_window` 等 metadata。
- 近似重复记忆被合并或跳过，而不是无限增长。
- `MemoryRetriever` 使用 `last_accessed` 参与最近性评分，返回带 score breakdown 的解释结果。
- 检索去重能过滤高度相似结果。
- 不按 session 过滤: 即使记忆带 `source_window.session_id`，默认召回仍跨来源全局可见。

集成测试重点:

- `/api/memory/search` 返回新增 retrieval 字段。
- Assistant 回复流程能召回并注入已有记忆。
- 聊天后反思失败不影响原始 Assistant 响应。

前端验证:

- `MemoryPanel` 能展示新 metadata。
- 搜索结果能展示评分解释。
- 手动创建、删除、巩固、遗忘原有功能不回退。

## 分阶段落地

Phase 1: 结构化记忆与检索增强

- 增加结构化 metadata helper。
- 改进 `MemoryRetriever` 评分、去重、score breakdown。
- 更新 API/tool 返回格式和前端展示。

Phase 2: 自动形成记忆

- 增加 `ConversationMemoryBuffer` 和 `MemoryProcessor`。
- 接入 WebSocket/REST chat 后反思。
- 保证摘要失败不阻塞聊天。

Phase 3: 助理注入优化

- 统一 memory prompt block 格式。
- Assistant 使用 `assistant_context` 注入。
- 限制注入条数与字符数。

Phase 4: 遗忘与巩固强化

- 改进近似去重、质量阈值和遗忘策略。
- 前端显示记忆类型、来源窗口和质量。

## 论文亮点表述

这不是简单 CRUD 记忆表，而是一个面向私人助理的长期记忆层:

- 自动从自然对话中形成结构化长期记忆。
- 用检索摘要和注入摘要分离，降低 prompt 污染。
- 全局个人记忆池适配私人助理场景，不照搬群聊插件的 session/persona 隔离。
- 可解释召回让系统行为可观察、可调试、可评估。
- 巩固与遗忘机制让记忆规模可控，避免无限堆积。

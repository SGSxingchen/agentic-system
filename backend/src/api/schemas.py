"""Pydantic 请求/响应模型

定义所有 API 端点使用的请求和响应 Schema，
确保类型安全和自动文档生成。
"""
from pydantic import BaseModel, Field, model_validator
from typing import Any, Literal, Optional
from enum import Enum


# ========================
# 通用响应
# ========================


class APIResponse(BaseModel):
    """统一 API 响应格式"""

    status: str  # "ok" | "error"
    message: Optional[str] = None
    data: Optional[Any] = None


# ========================
# 任务相关
# ========================


class TaskStatus(str, Enum):
    """任务状态枚举（v2 Phase B：与 core.task.types.TaskStatus 一致）"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class TaskSubmitRequest(BaseModel):
    """提交任务请求。

    /api/tasks 是 Agent Run 的便捷入口；固定 Pipeline 已移除。
    """

    requirement: str = Field(..., min_length=1, description="用户需求描述")
    agent_name: str = Field(default="assistant", description="auto 模式下使用的 Agent")
    session_id: Optional[str] = Field(default=None, description="可选会话实例 ID")
    workspace_id: Optional[str] = Field(default=None, description="可选工作区实例 ID")
    input: dict[str, Any] = Field(default_factory=dict, description="附加上下文输入")


class AgentRunCreateRequest(BaseModel):
    """创建自主 Agent Run 请求。"""

    goal: str = Field(..., min_length=1, description="本次运行目标")
    agent_name: str = Field(default="assistant", description="负责本次运行的 Agent")
    session_id: Optional[str] = Field(default=None, description="会话实例 ID；仅作为上下文/溯源")
    workspace_id: Optional[str] = Field(default=None, description="工作区实例 ID；为空则自动创建 run- 前缀工作区")
    mode: str = Field(default="autonomous", description="运行语义：autonomous/interactive/compat")
    strategy: str = Field(default="agent_decides", description="调度策略说明；不表达固定步骤")
    max_iterations: int = Field(default=50, ge=1, le=500, description="最大迭代次数")
    completion_criteria: str = Field(default="", description="运行完成标准说明")
    auto_memory: bool = Field(default=True, description="是否自动使用记忆上下文")
    input: dict[str, Any] = Field(default_factory=dict, description="附加上下文输入")
    parent_id: Optional[str] = Field(default=None, description="可选父 run/task ID")


class RunControlRequest(BaseModel):
    """运行控制请求。"""

    action: Literal["pause", "resume", "cancel"] = Field(default="cancel", description="运行控制动作")


class TaskResponse(BaseModel):
    """任务详情响应"""

    task_id: str
    status: TaskStatus
    requirement: str
    plan: Optional[dict] = None
    code: Optional[dict] = None
    review: Optional[dict] = None
    created_at: str
    updated_at: str


# ========================
# Agent 相关
# ========================

class SkillConfigRequest(BaseModel):
    """Agent-scoped skills config. Supports directories and inline/file-backed items."""

    enabled: bool = True
    directories: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)
    strategy: str = Field(default="metadata_and_instructions", description="加载策略标记，当前只注入元数据/说明")


class MCPServerConfigRequest(BaseModel):
    """Agent-scoped MCP server config."""

    name: str = Field(..., min_length=1)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    enabled: bool = True
    description: str = ""
    transport: str = "stdio"
    url: str = ""


class AgentMCPImportRequest(BaseModel):
    """Import common MCP configuration text into one Agent."""

    content: str = Field(..., min_length=1, description="JSON or YAML MCP config text")
    format: Optional[Literal["auto", "json", "yaml", "yml"]] = Field(default=None)
    source: Optional[str] = Field(default=None, description="Optional source filename or label")
    mode: Literal["merge", "replace"] = "merge"
    apply: bool = False

    @model_validator(mode="before")
    @classmethod
    def accept_common_text_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "content" in value:
            return value
        for key in ("config_text", "text", "raw"):
            if key in value:
                normalized = dict(value)
                normalized["content"] = normalized.pop(key)
                return normalized
        return value


class AgentToolMount(BaseModel):
    """Resolved Tool/Agent mount shown on Agent configuration APIs."""

    name: str
    type: Literal["agent", "tool", "unknown"] | str = "unknown"
    configured: bool = True
    available: bool = False
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class AgentSkillMount(BaseModel):
    """Normalized Agent-scoped Skill mount summary."""

    configured: bool = False
    enabled: bool = True
    directories: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)
    strategy: str = "metadata_and_instructions"
    item_count: int = 0


class AgentMCPMount(BaseModel):
    """Normalized Agent-scoped MCP mount summary."""

    name: str
    enabled: bool = True
    transport: str = "stdio"
    command: str = ""
    description: str = ""
    status: Literal["configured_pending_runtime", "disabled", "config_error"] | str = "configured_pending_runtime"
    errors: list[str] = Field(default_factory=list)


class AgentWorkspaceBinding(BaseModel):
    """Default workspace binding configured for an Agent."""

    workspace_id: Optional[str] = None
    workspace_root: Optional[str] = None
    source: Literal["agent_config", "not_configured"] | str = "not_configured"


class AgentLLMConfig(BaseModel):
    """Agent-scoped model selection and generation options."""

    provider: Optional[str] = Field(default=None, description="openai | anthropic；为空则继承全局配置")
    api_key: Optional[str] = Field(default=None, description="可选：该 Agent 独立使用的模型服务密钥；响应不会明文返回")
    api_key_set: Optional[bool] = Field(default=None, description="响应字段：是否已配置独立密钥")
    model: Optional[str] = Field(default=None, description="该 Agent 使用的模型；为空则继承全局模型")
    base_url: Optional[str] = Field(default=None, description="可选：该 Agent 的模型服务地址")
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    top_p: Optional[float] = Field(default=None, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=200000)
    stop_sequences: Optional[list[str]] = None
    openai: dict[str, Any] = Field(default_factory=dict)
    anthropic: dict[str, Any] = Field(default_factory=dict)
    reasoning_effort: Optional[str] = None
    source: Literal["agent_config", "global_default"] | str = "global_default"



class AgentInfo(BaseModel):
    """Agent 信息"""

    name: str
    status: str
    capabilities: list[str]
    description: str = ""
    registered: bool = True
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    llm: Optional[AgentLLMConfig] = None
    tools: list[str] = Field(default_factory=list)
    runtime_tools: list[str] = Field(default_factory=list)
    tool_mounts: list[AgentToolMount] = Field(default_factory=list)
    output_format: Optional[Literal["text", "json"]] = None
    max_iterations: Optional[int] = Field(default=None, ge=1, le=50)
    skills: Optional[SkillConfigRequest] = None
    skill_mount: AgentSkillMount = Field(default_factory=AgentSkillMount)
    mcp_servers: Optional[list[MCPServerConfigRequest]] = None
    mcp_mounts: list[AgentMCPMount] = Field(default_factory=list)
    mcp_capability_status: Optional[dict[str, Any]] = None
    default_workspace_id: Optional[str] = None
    default_workspace_root: Optional[str] = None
    workspace_binding: AgentWorkspaceBinding = Field(default_factory=AgentWorkspaceBinding)


class AgentInvokeRequest(BaseModel):
    """直接调用 Agent 请求"""

    data: dict[str, Any] = Field(default_factory=dict, description="传给 Agent 的数据")

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_flat_payload(cls, value: Any) -> Any:
        """Accept old frontend payloads like {"input": "..."}.

        The documented shape is {"data": {...}}, but earlier UI code posted a
        flat object. Without this compatibility layer the request validated
        successfully while silently invoking the Agent with an empty dict.
        """

        if not isinstance(value, dict) or "data" in value:
            return value
        return {"data": dict(value)}


# ========================
# 配置相关
# ========================


class LLMConfigRequest(BaseModel):
    """LLM 配置更新请求"""

    provider: str
    api_key: Optional[str] = ""
    model: str
    base_url: str = ""
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    top_p: Optional[float] = Field(default=None, ge=0, le=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=200000)
    stop_sequences: list[str] = Field(default_factory=list)
    openai: dict[str, Any] = Field(default_factory=dict)
    anthropic: dict[str, Any] = Field(default_factory=dict)


class WebSearchToolConfigRequest(BaseModel):
    """Web search tool config update request."""

    provider: str = "duckduckgo"
    base_url: str = ""
    api_key: Optional[str] = ""
    max_results: int = Field(default=5, ge=1, le=10)
    timeout: float = Field(default=10, gt=0)


class WebFetchToolConfigRequest(BaseModel):
    """Web fetch tool config update request."""

    timeout: float = Field(default=10, gt=0)
    max_chars: int = Field(default=4000, ge=200, le=20000)


class FileToolConfigRequest(BaseModel):
    """Workspace file tool config update request."""

    workspace_root: str = "./workspace"


class WorkspaceFileEntry(BaseModel):
    """Brief file entry returned by managed workspace detail APIs."""

    path: str
    kind: Literal["file", "directory"]
    size: Optional[int] = None
    modified_at: str


class WorkspaceSummary(BaseModel):
    """Managed workspace summary."""

    id: str
    name: str
    kind: Literal["project", "agent", "session", "run"] | str
    source: str
    root_path: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceDetail(WorkspaceSummary):
    """Managed workspace detail with an optional shallow file listing."""

    files: list[WorkspaceFileEntry] = Field(default_factory=list)
    files_truncated: bool = False


class WorkspaceFileContentUpdateRequest(BaseModel):
    """Text file update request inside a managed workspace."""

    path: str = Field(..., min_length=1, description="工作区内相对路径")
    content: str = Field(default="", description="完整文本内容")
    encoding: str = Field(default="utf-8", description="文本编码")


class ShellToolConfigRequest(BaseModel):
    """Shell tool config update request."""

    enabled: bool = False
    timeout: float = Field(default=30, gt=0)


class CustomToolConfigRequest(BaseModel):
    """Generic config slot for future tools that need URL/key settings."""

    enabled: bool = True
    base_url: str = ""
    api_key: Optional[str] = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class ToolsConfigRequest(BaseModel):
    """Tool runtime config update request."""

    web_search: WebSearchToolConfigRequest = Field(default_factory=WebSearchToolConfigRequest)
    web_fetch: WebFetchToolConfigRequest = Field(default_factory=WebFetchToolConfigRequest)
    file: FileToolConfigRequest = Field(default_factory=FileToolConfigRequest)
    shell: ShellToolConfigRequest = Field(default_factory=ShellToolConfigRequest)
    custom: dict[str, CustomToolConfigRequest] = Field(default_factory=dict)


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""

    llm: LLMConfigRequest
    tools: Optional[ToolsConfigRequest] = None


class ModelListRequest(BaseModel):
    """从 LLM 提供商远端拉取模型列表请求

    所有字段都可选；缺省时回退到 backend/src/config.yaml 的已保存配置。
    api_key 留空表示沿用服务器已保存的密钥（前端密码框未触动时使用）。
    """

    provider: Optional[str] = Field(default=None, description="openai | anthropic")
    base_url: Optional[str] = Field(default=None, description="覆盖 base_url；空字符串表示用 SDK 默认")
    api_key: Optional[str] = Field(default=None, description="覆盖 api_key；留空沿用服务器保存的密钥")


class ConfigResponse(BaseModel):
    """配置响应（不暴露 api_key）"""

    llm: dict


# ========================
# 记忆相关
# ========================


# ========================
# Agent CRUD
# ========================




class AgentCreateRequest(BaseModel):
    """创建智能体请求（全配置化）"""

    name: str = Field(..., min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="智能体名称，只能使用字母、数字和下划线，且不能以数字开头")
    description: str = Field(default="", description="智能体描述")
    system_prompt: str = Field(default="", description="系统提示词")
    tools: list[str] = Field(default_factory=list, description="可用工具名称列表")
    output_format: Literal["text", "json"] = Field(default="text", description="输出格式: text | json")
    max_iterations: int = Field(default=10, ge=1, le=50, description="tool_use 最大循环次数")
    model: Optional[str] = Field(default=None, description="可选：该 Agent 使用的模型名称")
    llm: Optional[AgentLLMConfig] = None
    skills: Optional[SkillConfigRequest] = None
    mcp_servers: list[MCPServerConfigRequest] = Field(default_factory=list)
    default_workspace_id: Optional[str] = Field(default=None, description="Agent 默认工作区 ID")
    default_workspace_root: Optional[str] = Field(default=None, description="Agent 默认工作区根路径")


class AgentUpdateRequest(BaseModel):
    """更新智能体请求（部分更新）"""

    description: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    output_format: Optional[Literal["text", "json"]] = None
    max_iterations: Optional[int] = Field(default=None, ge=1, le=50)
    model: Optional[str] = None
    llm: Optional[AgentLLMConfig] = None
    skills: Optional[SkillConfigRequest] = None
    mcp_servers: Optional[list[MCPServerConfigRequest]] = None
    default_workspace_id: Optional[str] = None
    default_workspace_root: Optional[str] = None


# ========================
# 记忆相关
# ========================


class MemoryCreateRequest(BaseModel):
    """创建记忆请求"""

    content: str = Field(..., min_length=1)
    type: str = Field(default="semantic")
    importance: float = Field(default=0.5, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchRequest(BaseModel):
    """搜索记忆请求"""

    query: str = Field(..., min_length=1)
    max_results: int = Field(default=5, ge=1, le=50)


class MemoryUpdateRequest(BaseModel):
    """更新记忆请求（部分更新）"""

    content: Optional[str] = Field(default=None, min_length=1)
    type: Optional[str] = None
    importance: Optional[float] = Field(default=None, ge=0, le=1)
    metadata: Optional[dict[str, Any]] = None


class MemorySettingsUpdateRequest(BaseModel):
    """记忆系统设置更新请求。"""

    backend: Optional[str] = Field(default=None, description="memory | chroma")
    persist_dir: Optional[str] = None
    collection_name: Optional[str] = None
    auto_reflection_enabled: Optional[bool] = None
    reflection_min_turns: Optional[int] = Field(default=None, ge=1, le=20)
    reflection_max_messages: Optional[int] = Field(default=None, ge=2, le=100)
    recall_max_results: Optional[int] = Field(default=None, ge=1, le=50)
    recall_max_chars: Optional[int] = Field(default=None, ge=200, le=8000)
    recall_score_threshold: Optional[float] = Field(default=None, ge=0, le=1)
    fallback_to_memory_on_error: Optional[bool] = None
    consolidation_threshold: Optional[float] = Field(default=None, ge=0, le=1)
    forget_after_days: Optional[int] = Field(default=None, ge=1, le=3650)
    forget_min_importance: Optional[float] = Field(default=None, ge=0, le=1)


# ========================
# 聊天会话相关
# ========================


class ChatSessionCreateRequest(BaseModel):
    """创建聊天分页/会话请求"""

    workspace_id: Optional[str] = Field(default=None, description="可选：绑定到该会话的工作区 ID")
    title: Optional[str] = Field(default=None, description="可选会话标题")


class ChatSessionUpdateRequest(BaseModel):
    """更新聊天分页/会话请求"""

    workspace_id: Optional[str] = Field(default=None, description="可选：更新会话工作区绑定")
    title: Optional[str] = Field(default=None, description="新的会话标题")


class ChatMessageCreateRequest(BaseModel):
    """追加聊天消息请求"""

    id: Optional[str] = Field(default=None, description="前端生成的消息 ID")
    type: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)
    timestamp: Optional[str] = None
    memoriesUsed: Optional[int] = Field(default=None, ge=0)
    elapsedMs: Optional[float] = Field(default=None, ge=0)
    usage: Optional[dict[str, int]] = None
    toolCalls: Optional[list[dict[str, Any]]] = None
    agent_name: Optional[str] = None
    error: Optional[str] = None
    timeline: Optional[list[dict[str, Any]]] = None
    artifacts: Optional[list[dict[str, Any]]] = None




# ========================
# Artifact / 前端附件相关
# ========================


class ArtifactCreateRequest(BaseModel):
    """创建可被前端预览/下载的 Artifact。"""

    kind: Literal["html", "markdown", "code", "image", "file", "text"] = "file"
    title: str = Field(..., min_length=1, description="Artifact 标题")
    content: str = Field(..., min_length=1, description="文本内容或 base64 文件内容")
    mime_type: str = Field(default="", description="MIME 类型，如 text/html、image/png")
    filename: str = Field(default="", description="下载文件名")
    encoding: str = Field(default="utf-8", description="文本编码")
    content_encoding: Literal["text", "base64"] = "text"
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    source: str = "api"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ========================
# 进化 / 动态能力相关
# ========================


class EvolutionCommandRequest(BaseModel):
    """Generate a concrete system-evolution instruction from a user goal."""

    goal: str = Field(..., min_length=1, description="希望 Agentic System 如何进化的目标")


class DynamicToolCreateRequest(BaseModel):
    """创建动态工具请求"""

    name: str = Field(
        ...,
        min_length=1,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="工具名称，必须是 Python/JSON Schema 友好的标识符",
    )
    description: str = Field(default="", description="工具描述，会暴露给 Agent 作为 tool description")
    mode: str = Field(
        default="template",
        description="动态工具模式: template | checklist | regex_extract",
    )
    input_schema: Optional[dict[str, Any]] = Field(
        default=None,
        description="可选 JSON Schema，不传则按 mode 生成默认 schema",
    )
    config: dict[str, Any] = Field(default_factory=dict, description="工具模式配置")
    attach_to_agents: list[str] = Field(
        default_factory=list,
        description="创建后自动挂载到这些 Agent 的 tools 列表",
    )
    overwrite: bool = Field(default=False, description="同名动态工具存在时是否覆盖")


class ToolPromptUpdateRequest(BaseModel):
    """更新工具提示词请求"""

    prompt: str = Field(
        ...,
        min_length=1,
        description="暴露给 LLM 的 Tool 提示词/描述。JSON Schema 不允许通过该接口修改。",
    )


# ========================
# 聊天室（多 Agent 群聊）
# ========================


class ChatroomDynamicMember(BaseModel):
    """房间内动态创建的 Agent 规格。"""

    name: str = Field(..., min_length=1, description="动态成员名")
    role_prompt: str = Field(default="", description="该成员的系统提示词")
    base_agent: str = Field(default="generic", description="底层基础 Agent 名")


class ChatroomCreateRequest(BaseModel):
    """创建聊天室请求"""

    title: str = Field(..., min_length=1, description="房间名")
    topic: str = Field(default="", description="房间主题（长文本）")
    goal: Optional[str] = Field(default=None, description="当前主要目标（单行）")
    members: list[str] = Field(default_factory=list, description="静态成员名列表")
    dynamic_members: list[ChatroomDynamicMember] = Field(
        default_factory=list, description="动态成员列表"
    )
    workspace_id: Optional[str] = Field(default=None, description="可选绑定的工作区 ID")
    settings: Optional[dict[str, Any]] = Field(
        default=None, description="房间配置覆盖项（auto_host/recent_n 等）"
    )


class ChatroomUpdateRequest(BaseModel):
    """更新聊天室请求（部分更新）"""

    title: Optional[str] = None
    topic: Optional[str] = None
    goal: Optional[str] = None
    members: Optional[list[str]] = None
    dynamic_members: Optional[list[ChatroomDynamicMember]] = None
    workspace_id: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class ChatroomMessageCreateRequest(BaseModel):
    """房间内追加用户消息请求"""

    content: str = Field(..., min_length=1, description="Markdown 文本")


class ChatroomInvokeRequest(BaseModel):
    """手动召唤某成员发言"""

    agent_name: str = Field(..., min_length=1, description="目标 Agent 名")
    prompt: Optional[str] = Field(
        default=None,
        description="可选附加提示词；不填走房间默认上下文",
    )

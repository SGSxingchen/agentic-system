"""Pydantic 请求/响应模型

定义所有 API 端点使用的请求和响应 Schema，
确保类型安全和自动文档生成。
"""
from pydantic import BaseModel, Field
from typing import Any, Optional
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
    """任务状态枚举"""

    PENDING = "pending"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskSubmitRequest(BaseModel):
    """提交任务请求"""

    requirement: str = Field(..., min_length=1, description="用户需求描述")
    workflow: str = Field(default="auto", description="工作流类型")


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


class AgentInfo(BaseModel):
    """Agent 信息"""

    name: str
    status: str
    capabilities: list[str]
    description: str = ""


class AgentInvokeRequest(BaseModel):
    """直接调用 Agent 请求"""

    data: dict[str, Any] = Field(default_factory=dict, description="传给 Agent 的数据")


# ========================
# 工作流相关
# ========================


class WorkflowExecuteRequest(BaseModel):
    """执行工作流请求"""

    workflow_type: str = Field(default="plan_code_review", description="工作流类型")
    template_name: Optional[str] = Field(default=None, description="YAML 工作流模板名称（优先级高于 workflow_type）")
    requirement: str = Field(default="", description="需求描述")
    input: Optional[str] = Field(default=None, description="输入（别名，等价于 requirement）")
    options: dict[str, Any] = Field(default_factory=dict, description="额外选项")


class WorkflowTemplate(BaseModel):
    """工作流模板"""

    name: str
    description: str
    steps: list[str]


# ========================
# 配置相关
# ========================


class LLMConfigRequest(BaseModel):
    """LLM 配置更新请求"""

    provider: str
    api_key: str = ""
    model: str
    base_url: str = ""


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""

    llm: LLMConfigRequest


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

    name: str = Field(..., min_length=1, description="智能体名称")
    description: str = Field(default="", description="智能体描述")
    system_prompt: str = Field(default="", description="系统提示词")
    tools: list[str] = Field(default_factory=list, description="可用工具名称列表")
    output_format: str = Field(default="text", description="输出格式: text | json")
    max_iterations: int = Field(default=10, ge=1, le=50, description="tool_use 最大循环次数")


class AgentUpdateRequest(BaseModel):
    """更新智能体请求（部分更新）"""

    description: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    output_format: Optional[str] = None
    max_iterations: Optional[int] = None


# ========================
# 工作流 CRUD
# ========================


class WorkflowStepSchema(BaseModel):
    """工作流步骤"""

    name: str = Field(..., min_length=1)
    agent: str = Field(..., min_length=1)
    input: Optional[dict[str, Any]] = None
    output_key: Optional[str] = None
    condition: Optional[str] = None
    max_iterations: int = Field(default=1, ge=1)
    timeout: Optional[float] = Field(default=None, gt=0, description="步骤超时秒数")


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""

    name: str = Field(..., min_length=1, description="工作流名称（英文下划线格式）")
    description: str = Field(default="", description="工作流描述")
    mode: str = Field(default="sequential", description="执行模式: sequential | parallel")
    steps: list[WorkflowStepSchema] = Field(default_factory=list, description="步骤列表")


class WorkflowUpdateRequest(BaseModel):
    """更新工作流请求（部分更新）"""

    description: Optional[str] = None
    mode: Optional[str] = None
    steps: Optional[list[WorkflowStepSchema]] = None


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

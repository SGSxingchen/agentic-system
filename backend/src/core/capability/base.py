"""能力基类 - 定义能力的抽象接口和 Schema

每个 Capability 对外暴露 JSON Schema 描述 (CapabilitySchema)，
并实现 execute() 异步执行逻辑。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class CapabilitySchema:
    """能力的 JSON Schema 描述

    Attributes:
        name: 能力名称（唯一标识）
        description: 能力描述
        parameters: JSON Schema 格式的参数定义
        returns: 返回值描述
        is_read_only: 工具是否纯读 / 无副作用（用于审计与并发分组的提示）
        is_concurrency_safe: 同一轮多次调用是否可以并发执行（False 时必须串行）
        max_result_size: 单次执行结果的字符上限（0 表示不限），超出时调度器会截断
    """
    name: str
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    returns: str = ""
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    max_result_size: int = 8000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "is_read_only": self.is_read_only,
            "is_concurrency_safe": self.is_concurrency_safe,
            "max_result_size": self.max_result_size,
        }


class CapabilityBase(ABC):
    """能力抽象基类

    子类需要实现:
    - name, description 属性
    - get_schema() → 返回 JSON Schema 格式的能力描述
    - execute(**kwargs) → 异步执行逻辑
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}

    @property
    @abstractmethod
    def name(self) -> str:
        """能力名称（唯一标识）"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """能力描述"""
        ...

    @abstractmethod
    def get_schema(self) -> CapabilitySchema:
        """返回能力的 JSON Schema 定义"""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """执行能力

        Args:
            **kwargs: 由 get_schema().parameters 定义的参数

        Returns:
            执行结果
        """
        ...

    def validate_input(self, **kwargs: Any) -> bool:
        """验证输入参数

        默认实现：检查 schema 中 required 参数是否提供。
        子类可覆盖以添加更严格的校验。
        """
        schema = self.get_schema()
        required = schema.parameters.get("required", [])
        for param in required:
            if param not in kwargs:
                return False
        return True

    def check_permissions(self, **kwargs: Any) -> Dict[str, Any]:
        """运行时权限校验，由 Agent 调度器在 execute 前调用

        默认放行；有副作用或敏感能力（如 bash / write_file）应覆盖此方法，
        在拒绝时返回 {"decision": "deny", "reason": "..."}。

        Returns:
            {"decision": "allow"} 或 {"decision": "deny", "reason": str}
        """
        return {"decision": "allow"}

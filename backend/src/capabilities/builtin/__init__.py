"""内置能力插件

提供三个开箱即用的能力:
- CodeParserCapability: 深度 Python 代码解析
- StaticAnalyzerCapability: 基于 AST 的静态分析
- TestRunnerCapability: 测试文件结构解析

统一从 core.capability.native 导入，保持两个路径都能访问。
"""
from core.capability.native import (
    CodeParserCapability,
    StaticAnalyzerCapability,
    TestRunnerCapability,
)

__all__ = [
    "CodeParserCapability",
    "StaticAnalyzerCapability",
    "TestRunnerCapability",
]

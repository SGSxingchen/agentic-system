"""StaticAnalyzer 能力插件 - 基于 AST 的静态代码分析

功能:
- 未使用的导入检测
- 过长函数检测
- 命名规范检查 (PEP 8 风格)
- 圈复杂度估算
- 缺失文档字符串检测
- 可变默认参数检测
- 输出结构化问题列表（位置、严重级别、描述）
"""
import ast
import re
from typing import Any, Dict, List, Set, Tuple, Union

from core.capability.base import CapabilityBase, CapabilitySchema


# ─── 问题严重级别 ──────────────────────────────────────────
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITY_HINT = "hint"


class StaticAnalyzerCapability(CapabilityBase):
    """基于 AST 的静态代码分析能力

    检查项:
    - unused_import: 未使用的导入
    - function_too_long: 过长函数 (可配置阈值)
    - line_too_long: 过长行 (可配置阈值)
    - naming_convention: PEP 8 命名规范检查
    - high_complexity: 圈复杂度过高
    - missing_docstring: 缺失文档字符串
    - mutable_default: 可变默认参数
    - syntax_error: 语法错误
    """

    @property
    def name(self) -> str:
        return "static_analyzer"

    @property
    def description(self) -> str:
        return "基于 AST 的静态代码分析：未使用导入、命名规范、复杂度、函数长度等"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python 源代码",
                    },
                    "max_line_length": {
                        "type": "integer",
                        "description": "最大行长度",
                        "default": 120,
                    },
                    "max_function_length": {
                        "type": "integer",
                        "description": "最大函数长度（行）",
                        "default": 50,
                    },
                    "max_complexity": {
                        "type": "integer",
                        "description": "最大圈复杂度",
                        "default": 10,
                    },
                    "checks": {
                        "type": "array",
                        "description": "要执行的检查项列表，默认全部执行",
                        "items": {"type": "string"},
                        "default": None,
                    },
                },
                "required": ["code"],
            },
            returns="包含 issues 列表和 summary 统计的字典",
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """执行静态分析

        Args:
            code: Python 源代码
            max_line_length: 最大行长度 (默认 120)
            max_function_length: 最大函数行数 (默认 50)
            max_complexity: 最大圈复杂度 (默认 10)
            checks: 执行的检查项列表 (默认全部)

        Returns:
            {"issues": [...], "summary": {...}}
        """
        code: str = kwargs["code"]
        max_line_length: int = kwargs.get("max_line_length", 120)
        max_function_length: int = kwargs.get("max_function_length", 50)
        max_complexity: int = kwargs.get("max_complexity", 10)
        checks: list = kwargs.get("checks") or [
            "line_too_long",
            "function_too_long",
            "unused_import",
            "naming_convention",
            "high_complexity",
            "missing_docstring",
            "mutable_default",
        ]

        issues: List[Dict[str, Any]] = []

        # 行长度检查（不需要 AST）
        if "line_too_long" in checks:
            issues.extend(self._check_line_length(code, max_line_length))

        # 解析 AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            issues.append({
                "type": "syntax_error",
                "severity": SEVERITY_ERROR,
                "line": e.lineno,
                "column": e.offset,
                "message": f"SyntaxError: {e.msg}",
            })
            return {"issues": issues, "summary": self._make_summary(issues)}

        if "function_too_long" in checks:
            issues.extend(self._check_function_length(tree, max_function_length))

        if "unused_import" in checks:
            issues.extend(self._check_unused_imports(tree))

        if "naming_convention" in checks:
            issues.extend(self._check_naming_convention(tree))

        if "high_complexity" in checks:
            issues.extend(self._check_complexity(tree, max_complexity))

        if "missing_docstring" in checks:
            issues.extend(self._check_missing_docstring(tree))

        if "mutable_default" in checks:
            issues.extend(self._check_mutable_defaults(tree))

        # 按行号排序
        issues.sort(key=lambda x: (x.get("line") or 0, x.get("column") or 0))

        return {
            "issues": issues,
            "summary": self._make_summary(issues),
        }

    # ─── 检查器实现 ──────────────────────────────────────

    @staticmethod
    def _check_line_length(code: str, max_length: int) -> List[Dict[str, Any]]:
        """检查行长度"""
        issues = []
        for i, line in enumerate(code.splitlines(), 1):
            if len(line) > max_length:
                issues.append({
                    "type": "line_too_long",
                    "severity": SEVERITY_WARNING,
                    "line": i,
                    "column": max_length + 1,
                    "message": f"Line too long ({len(line)} > {max_length})",
                })
        return issues

    @staticmethod
    def _check_function_length(
        tree: ast.Module, max_length: int
    ) -> List[Dict[str, Any]]:
        """检查函数长度"""
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.end_lineno and node.lineno:
                    length = node.end_lineno - node.lineno + 1
                    if length > max_length:
                        issues.append({
                            "type": "function_too_long",
                            "severity": SEVERITY_WARNING,
                            "line": node.lineno,
                            "column": node.col_offset + 1,
                            "message": (
                                f"Function '{node.name}' is too long "
                                f"({length} > {max_length} lines)"
                            ),
                        })
        return issues

    @staticmethod
    def _check_unused_imports(tree: ast.Module) -> List[Dict[str, Any]]:
        """检测未使用的导入"""
        # 收集导入名称
        imported: List[Tuple[str, int]] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported.append((name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                # 跳过 __future__ 导入
                if node.module and node.module.startswith("__future__"):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    name = alias.asname or alias.name
                    imported.append((name, node.lineno))

        # 收集使用的名称
        used_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        issues = []
        for imp_name, lineno in imported:
            # 跳过 _ 前缀（通常是副作用导入）
            if imp_name.startswith("_"):
                continue
            if imp_name not in used_names:
                issues.append({
                    "type": "unused_import",
                    "severity": SEVERITY_INFO,
                    "line": lineno,
                    "column": 1,
                    "message": f"Import '{imp_name}' appears to be unused",
                })
        return issues

    @staticmethod
    def _check_naming_convention(tree: ast.Module) -> List[Dict[str, Any]]:
        """检查 PEP 8 命名规范

        规则:
        - 函数名/方法名: snake_case
        - 类名: PascalCase
        - 常量（模块顶层全大写赋值）: UPPER_SNAKE_CASE (不检查，假定合规)
        - 变量: snake_case
        """
        issues = []

        # snake_case 正则：允许单下划线开头、全小写+数字+下划线
        snake_re = re.compile(r"^_*[a-z][a-z0-9_]*$|^_+$|^__[a-z][a-z0-9_]*__$")
        # PascalCase 正则
        pascal_re = re.compile(r"^_*[A-Z][a-zA-Z0-9]*$")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                # 跳过 dunder 方法
                if name.startswith("__") and name.endswith("__"):
                    continue
                if not snake_re.match(name):
                    issues.append({
                        "type": "naming_convention",
                        "severity": SEVERITY_INFO,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": (
                            f"Function '{name}' should use snake_case naming"
                        ),
                    })

            elif isinstance(node, ast.ClassDef):
                name = node.name
                if not pascal_re.match(name):
                    issues.append({
                        "type": "naming_convention",
                        "severity": SEVERITY_INFO,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": (
                            f"Class '{name}' should use PascalCase naming"
                        ),
                    })

        return issues

    @staticmethod
    def _check_complexity(
        tree: ast.Module, max_complexity: int
    ) -> List[Dict[str, Any]]:
        """估算圈复杂度 (McCabe)

        计算方式: 1 + 每个分支节点 (if/elif/for/while/except/and/or/with/assert)
        """
        issues = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            complexity = 1  # 函数本身算 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.IfExp)):
                    complexity += 1
                elif isinstance(child, (ast.For, ast.AsyncFor)):
                    complexity += 1
                elif isinstance(child, (ast.While,)):
                    complexity += 1
                elif isinstance(child, ast.ExceptHandler):
                    complexity += 1
                elif isinstance(child, ast.BoolOp):
                    # and/or 每个操作符增加 1
                    complexity += len(child.values) - 1
                elif isinstance(child, (ast.With, ast.AsyncWith)):
                    complexity += 1
                elif isinstance(child, ast.Assert):
                    complexity += 1

            if complexity > max_complexity:
                issues.append({
                    "type": "high_complexity",
                    "severity": SEVERITY_WARNING,
                    "line": node.lineno,
                    "column": node.col_offset + 1,
                    "message": (
                        f"Function '{node.name}' has high cyclomatic complexity "
                        f"({complexity} > {max_complexity})"
                    ),
                    "complexity": complexity,
                })

        return issues

    @staticmethod
    def _check_missing_docstring(tree: ast.Module) -> List[Dict[str, Any]]:
        """检查缺失的文档字符串

        检查对象: 公开函数和公开类（不以 _ 开头的）
        """
        issues = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_") and not ast.get_docstring(node):
                    issues.append({
                        "type": "missing_docstring",
                        "severity": SEVERITY_HINT,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": (
                            f"Public function '{node.name}' is missing a docstring"
                        ),
                    })
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_") and not ast.get_docstring(node):
                    issues.append({
                        "type": "missing_docstring",
                        "severity": SEVERITY_HINT,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": (
                            f"Public class '{node.name}' is missing a docstring"
                        ),
                    })

        return issues

    @staticmethod
    def _check_mutable_defaults(tree: ast.Module) -> List[Dict[str, Any]]:
        """检查可变默认参数

        例如: def foo(x=[]) 或 def foo(x={})
        """
        issues = []
        mutable_types = (ast.List, ast.Dict, ast.Set)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for default in node.args.defaults + node.args.kw_defaults:
                if default is None:
                    continue
                if isinstance(default, mutable_types):
                    issues.append({
                        "type": "mutable_default",
                        "severity": SEVERITY_WARNING,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": (
                            f"Function '{node.name}' has a mutable default argument"
                        ),
                    })
                    break  # 每个函数只报一次

        return issues

    # ─── 辅助 ───────────────────────────────────────────

    @staticmethod
    def _make_summary(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成问题统计摘要"""
        summary: Dict[str, Any] = {"total": len(issues)}

        # 按严重级别统计
        for issue in issues:
            severity = issue.get("severity", "unknown")
            summary[severity] = summary.get(severity, 0) + 1

        # 按类型统计
        type_counts: Dict[str, int] = {}
        for issue in issues:
            itype = issue.get("type", "unknown")
            type_counts[itype] = type_counts.get(itype, 0) + 1
        summary["by_type"] = type_counts

        return summary

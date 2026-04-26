"""内置原生能力 - 代码解析、静态分析与测试结构解析

提供三个即用的能力实例:
- CodeParserCapability: 深度解析 Python 代码，提取函数/类/导入/类型注解/嵌套结构
- StaticAnalyzerCapability: 代码质量检查（行长、函数长度、未使用导入、命名规范、复杂度等）
- TestRunnerCapability: 解析测试文件结构，提取测试用例、断言统计、fixture 信息
"""
import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .base import CapabilityBase, CapabilitySchema


# ═══════════════════════════════════════════════════════════
#  CodeParserCapability
# ═══════════════════════════════════════════════════════════


class CodeParserCapability(CapabilityBase):
    """深度 Python 代码解析能力

    解析 Python 代码生成 AST 信息:
    - functions: 函数列表 [{name, args, lineno, docstring, ...}]
    - classes: 类列表 [{name, bases, methods, lineno, docstring, ...}]
    - imports: 导入列表 [{module, names, lineno}]
    - top_level_assignments: 顶层赋值 [{name, lineno}]
    - docstring: 模块级文档字符串
    - metrics: 代码结构指标

    支持嵌套函数/类提取、返回值注解、参数类型注解。
    """

    @property
    def name(self) -> str:
        return "code_parser"

    @property
    def description(self) -> str:
        return "深度解析 Python 代码，提取函数、类、导入、文档字符串等 AST 信息"

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
                    "include_nested": {
                        "type": "boolean",
                        "description": "是否提取嵌套的函数/类定义",
                        "default": True,
                    },
                },
                "required": ["code"],
            },
            returns="包含 functions, classes, imports, docstring, metrics 的字典",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """执行代码解析"""
        code: str = kwargs["code"]
        include_nested: bool = kwargs.get("include_nested", True)

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "error": f"SyntaxError: {e.msg} (line {e.lineno})",
                "functions": [],
                "classes": [],
                "imports": [],
                "docstring": None,
                "metrics": {},
            }

        functions: List[Dict[str, Any]] = []
        classes: List[Dict[str, Any]] = []
        imports: List[Dict[str, Any]] = []
        assignments: List[Dict[str, Any]] = []

        # 模块级文档字符串
        module_docstring = ast.get_docstring(tree)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(self._parse_function(node, include_nested))
            elif isinstance(node, ast.ClassDef):
                classes.append(self._parse_class(node, include_nested))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "type": "import",
                        "module": alias.name,
                        "alias": alias.asname,
                        "lineno": node.lineno,
                    })
            elif isinstance(node, ast.ImportFrom):
                imports.append({
                    "type": "from_import",
                    "module": node.module or "",
                    "names": [
                        {"name": a.name, "alias": a.asname} for a in node.names
                    ],
                    "level": node.level,
                    "lineno": node.lineno,
                })
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assignments.append({
                            "name": target.id,
                            "lineno": node.lineno,
                            "is_constant": target.id.isupper(),
                        })
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    assignments.append({
                        "name": node.target.id,
                        "lineno": node.lineno,
                        "is_constant": node.target.id.isupper(),
                        "annotation": self._annotation_to_str(node.annotation),
                    })

        # 计算代码指标
        metrics = self._compute_metrics(code, tree)

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "top_level_assignments": assignments,
            "docstring": module_docstring,
            "metrics": metrics,
            "total_lines": len(code.splitlines()),
        }

    def _parse_function(
        self,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        include_nested: bool = True,
    ) -> Dict[str, Any]:
        """解析函数定义"""
        # 参数信息
        args_info = []
        for arg in node.args.args:
            arg_data: Dict[str, Any] = {"name": arg.arg}
            if arg.annotation:
                arg_data["annotation"] = self._annotation_to_str(arg.annotation)
            args_info.append(arg_data)

        # 默认值
        defaults = node.args.defaults
        if defaults:
            offset = len(args_info) - len(defaults)
            for i, default in enumerate(defaults):
                args_info[offset + i]["default"] = self._value_to_str(default)

        # 返回值注解
        return_annotation = None
        if node.returns:
            return_annotation = self._annotation_to_str(node.returns)

        # 装饰器
        decorators = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                decorators.append(d.id)
            elif isinstance(d, ast.Attribute):
                decorators.append(self._annotation_to_str(d))
            elif isinstance(d, ast.Call):
                if isinstance(d.func, ast.Name):
                    decorators.append(d.func.id)
                elif isinstance(d.func, ast.Attribute):
                    decorators.append(self._annotation_to_str(d.func))

        result: Dict[str, Any] = {
            "name": node.name,
            "args": args_info,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "docstring": ast.get_docstring(node),
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "decorators": decorators,
            "return_annotation": return_annotation,
        }

        # 嵌套函数/类
        if include_nested:
            nested_functions = []
            nested_classes = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_functions.append(self._parse_function(child, True))
                elif isinstance(child, ast.ClassDef):
                    nested_classes.append(self._parse_class(child, True))
            if nested_functions:
                result["nested_functions"] = nested_functions
            if nested_classes:
                result["nested_classes"] = nested_classes

        return result

    def _parse_class(
        self,
        node: ast.ClassDef,
        include_nested: bool = True,
    ) -> Dict[str, Any]:
        """解析类定义"""
        methods = []
        class_variables = []
        nested_classes = []

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if include_nested:
                    methods.append(self._parse_function(item, include_nested))
                else:
                    methods.append(item.name)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_variables.append({
                            "name": target.id,
                            "lineno": item.lineno,
                        })
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    class_variables.append({
                        "name": item.target.id,
                        "lineno": item.lineno,
                        "annotation": self._annotation_to_str(item.annotation),
                    })
            elif isinstance(item, ast.ClassDef) and include_nested:
                nested_classes.append(self._parse_class(item, include_nested))

        # 基类
        bases = []
        for base in node.bases:
            bases.append(self._annotation_to_str(base))

        # 装饰器
        decorators = []
        for d in node.decorator_list:
            if isinstance(d, ast.Name):
                decorators.append(d.id)
            elif isinstance(d, ast.Call) and isinstance(d.func, ast.Name):
                decorators.append(d.func.id)

        result: Dict[str, Any] = {
            "name": node.name,
            "bases": bases,
            "methods": methods,
            "class_variables": class_variables,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "docstring": ast.get_docstring(node),
            "decorators": decorators,
        }

        if nested_classes:
            result["nested_classes"] = nested_classes

        return result

    def _compute_metrics(self, code: str, tree: ast.Module) -> Dict[str, Any]:
        """计算代码结构指标"""
        lines = code.splitlines()
        total_lines = len(lines)
        blank_lines = sum(1 for line in lines if not line.strip())
        comment_lines = sum(1 for line in lines if line.strip().startswith("#"))
        code_lines = total_lines - blank_lines - comment_lines

        function_count = 0
        class_count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1
            elif isinstance(node, ast.ClassDef):
                class_count += 1

        return {
            "total_lines": total_lines,
            "code_lines": code_lines,
            "blank_lines": blank_lines,
            "comment_lines": comment_lines,
            "function_count": function_count,
            "class_count": class_count,
        }

    @staticmethod
    def _annotation_to_str(node: ast.expr) -> str:
        """将 AST 注解节点转为字符串"""
        try:
            return ast.unparse(node)
        except Exception:
            return ast.dump(node)

    @staticmethod
    def _value_to_str(node: ast.expr) -> str:
        """将 AST 值节点转为字符串"""
        try:
            return ast.unparse(node)
        except Exception:
            return ast.dump(node)


# ═══════════════════════════════════════════════════════════
#  StaticAnalyzerCapability
# ═══════════════════════════════════════════════════════════


# 问题严重级别常量
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
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """执行静态分析"""
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
        imported: List[Tuple[str, int]] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported.append((name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("__future__"):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    name = alias.asname or alias.name
                    imported.append((name, node.lineno))

        used_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        issues = []
        for imp_name, lineno in imported:
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
        """检查 PEP 8 命名规范"""
        issues = []
        snake_re = re.compile(r"^_*[a-z][a-z0-9_]*$|^_+$|^__[a-z][a-z0-9_]*__$")
        pascal_re = re.compile(r"^_*[A-Z][a-zA-Z0-9]*$")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name.startswith("__") and name.endswith("__"):
                    continue
                if not snake_re.match(name):
                    issues.append({
                        "type": "naming_convention",
                        "severity": SEVERITY_INFO,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": f"Function '{name}' should use snake_case naming",
                    })
            elif isinstance(node, ast.ClassDef):
                name = node.name
                if not pascal_re.match(name):
                    issues.append({
                        "type": "naming_convention",
                        "severity": SEVERITY_INFO,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": f"Class '{name}' should use PascalCase naming",
                    })
        return issues

    @staticmethod
    def _check_complexity(
        tree: ast.Module, max_complexity: int
    ) -> List[Dict[str, Any]]:
        """估算圈复杂度 (McCabe)"""
        issues = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            complexity = 1
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.IfExp)):
                    complexity += 1
                elif isinstance(child, (ast.For, ast.AsyncFor)):
                    complexity += 1
                elif isinstance(child, ast.While):
                    complexity += 1
                elif isinstance(child, ast.ExceptHandler):
                    complexity += 1
                elif isinstance(child, ast.BoolOp):
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
        """检查缺失的文档字符串"""
        issues = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_") and not ast.get_docstring(node):
                    issues.append({
                        "type": "missing_docstring",
                        "severity": SEVERITY_HINT,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": f"Public function '{node.name}' is missing a docstring",
                    })
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_") and not ast.get_docstring(node):
                    issues.append({
                        "type": "missing_docstring",
                        "severity": SEVERITY_HINT,
                        "line": node.lineno,
                        "column": node.col_offset + 1,
                        "message": f"Public class '{node.name}' is missing a docstring",
                    })
        return issues

    @staticmethod
    def _check_mutable_defaults(tree: ast.Module) -> List[Dict[str, Any]]:
        """检查可变默认参数"""
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
                        "message": f"Function '{node.name}' has a mutable default argument",
                    })
                    break
        return issues

    @staticmethod
    def _make_summary(issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成问题统计摘要"""
        summary: Dict[str, Any] = {"total": len(issues)}
        for issue in issues:
            severity = issue.get("severity", "unknown")
            summary[severity] = summary.get(severity, 0) + 1
        type_counts: Dict[str, int] = {}
        for issue in issues:
            itype = issue.get("type", "unknown")
            type_counts[itype] = type_counts.get(itype, 0) + 1
        summary["by_type"] = type_counts
        return summary


# ═══════════════════════════════════════════════════════════
#  TestRunnerCapability
# ═══════════════════════════════════════════════════════════


class TestRunnerCapability(CapabilityBase):
    """测试文件结构解析能力

    解析 Python 测试文件（pytest / unittest 风格），提取:
    - 测试函数/方法列表
    - 测试类列表
    - 断言统计
    - fixture 使用情况
    - 参数化信息
    - 标记 (markers) 信息
    """

    __test__ = False  # 防止 pytest 把本类当作测试类收集

    @property
    def name(self) -> str:
        return "test_runner"

    @property
    def description(self) -> str:
        return "解析测试文件结构，提取测试用例、断言统计、fixture 信息"

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python 测试源代码",
                    },
                    "filename": {
                        "type": "string",
                        "description": "文件名（用于报告，可选）",
                        "default": "<test>",
                    },
                },
                "required": ["code"],
            },
            returns="包含 test_cases, test_classes, assertions, fixtures, summary 的字典",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """执行测试文件解析"""
        code: str = kwargs["code"]
        filename: str = kwargs.get("filename", "<test>")

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {
                "error": f"SyntaxError: {e.msg} (line {e.lineno})",
                "filename": filename,
                "test_cases": [],
                "test_classes": [],
                "fixtures": [],
                "summary": {},
            }

        test_cases: List[Dict[str, Any]] = []
        test_classes: List[Dict[str, Any]] = []
        fixtures: List[Dict[str, Any]] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_test_function(node):
                    test_cases.append(self._parse_test_function(node))
                elif self._is_fixture(node):
                    fixtures.append(self._parse_fixture(node))
            elif isinstance(node, ast.ClassDef):
                if self._is_test_class(node):
                    test_classes.append(self._parse_test_class(node))

        all_assertions = self._count_all_assertions(tree)

        total_tests = len(test_cases)
        for tc in test_classes:
            total_tests += tc["test_count"]

        summary = {
            "filename": filename,
            "total_tests": total_tests,
            "test_functions": len(test_cases),
            "test_classes": len(test_classes),
            "fixtures": len(fixtures),
            "total_assertions": all_assertions["total"],
            "assertion_types": all_assertions["by_type"],
        }

        return {
            "filename": filename,
            "test_cases": test_cases,
            "test_classes": test_classes,
            "fixtures": fixtures,
            "summary": summary,
        }

    # ─── 检测辅助 ──────────────────────────────────────

    @staticmethod
    def _is_test_function(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
        return node.name.startswith("test_") or node.name.startswith("test")

    @staticmethod
    def _is_test_class(node: ast.ClassDef) -> bool:
        if node.name.startswith("Test"):
            return True
        for base in node.bases:
            if isinstance(base, ast.Attribute):
                if isinstance(base.value, ast.Name) and base.value.id == "unittest":
                    if base.attr == "TestCase":
                        return True
            elif isinstance(base, ast.Name):
                if base.id == "TestCase":
                    return True
        return False

    @staticmethod
    def _is_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
        """判断是否为 pytest fixture"""
        for d in node.decorator_list:
            if isinstance(d, ast.Attribute):
                if isinstance(d.value, ast.Name) and d.value.id == "pytest":
                    if d.attr == "fixture":
                        return True
            elif isinstance(d, ast.Call):
                if isinstance(d.func, ast.Attribute):
                    if isinstance(d.func.value, ast.Name) and d.func.value.id == "pytest":
                        if d.func.attr == "fixture":
                            return True
            elif isinstance(d, ast.Name) and d.id == "fixture":
                return True
        return False

    # ─── 解析器 ────────────────────────────────────────

    def _parse_test_function(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Dict[str, Any]:
        """解析测试函数"""
        markers = self._extract_markers(node)
        params = self._extract_parametrize(node)
        assertions = self._count_assertions_in_node(node)
        fixture_args = self._extract_fixture_args(node)

        return {
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "docstring": ast.get_docstring(node),
            "markers": markers,
            "parametrize": params,
            "assertions": assertions,
            "fixture_args": fixture_args,
        }

    def _parse_test_class(self, node: ast.ClassDef) -> Dict[str, Any]:
        """解析测试类"""
        methods: List[Dict[str, Any]] = []
        setup_teardown: List[str] = []

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_test_function(item):
                    methods.append(self._parse_test_function(item))
                elif item.name in (
                    "setUp", "tearDown", "setUpClass", "tearDownClass",
                    "setup_method", "teardown_method",
                    "setup_class", "teardown_class",
                    "setup", "teardown",
                ):
                    setup_teardown.append(item.name)

        return {
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno,
            "docstring": ast.get_docstring(node),
            "test_methods": methods,
            "test_count": len(methods),
            "setup_teardown": setup_teardown,
            "bases": [self._node_to_str(base) for base in node.bases],
        }

    def _parse_fixture(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Dict[str, Any]:
        """解析 fixture"""
        scope = "function"
        for d in node.decorator_list:
            if isinstance(d, ast.Call):
                for kw in d.keywords:
                    if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                        scope = kw.value.value
        return {
            "name": node.name,
            "lineno": node.lineno,
            "scope": scope,
            "docstring": ast.get_docstring(node),
        }

    # ─── 标记/参数化提取 ────────────────────────────────

    @staticmethod
    def _extract_markers(
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> List[str]:
        """提取 pytest markers"""
        markers = []
        for d in node.decorator_list:
            if isinstance(d, ast.Attribute):
                if isinstance(d.value, ast.Attribute):
                    if (isinstance(d.value.value, ast.Name) and
                            d.value.value.id == "pytest" and
                            d.value.attr == "mark"):
                        markers.append(d.attr)
            elif isinstance(d, ast.Call):
                func = d.func
                if isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Attribute):
                        if (isinstance(func.value.value, ast.Name) and
                                func.value.value.id == "pytest" and
                                func.value.attr == "mark"):
                            markers.append(func.attr)
        return markers

    @staticmethod
    def _extract_parametrize(
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Optional[Dict[str, Any]]:
        """提取 @pytest.mark.parametrize 信息"""
        for d in node.decorator_list:
            if not isinstance(d, ast.Call):
                continue
            func = d.func
            is_parametrize = False
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Attribute):
                    if (isinstance(func.value.value, ast.Name) and
                            func.value.value.id == "pytest" and
                            func.value.attr == "mark" and
                            func.attr == "parametrize"):
                        is_parametrize = True

            if is_parametrize and d.args:
                param_names = None
                if isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                    param_names = [p.strip() for p in d.args[0].value.split(",")]
                param_count = 0
                if len(d.args) > 1 and isinstance(d.args[1], (ast.List, ast.Tuple)):
                    param_count = len(d.args[1].elts)
                return {
                    "param_names": param_names,
                    "case_count": param_count,
                }
        return None

    @staticmethod
    def _extract_fixture_args(
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> List[str]:
        """提取函数参数中可能的 fixture 名称"""
        skip = {"self", "cls"}
        args = []
        for arg in node.args.args:
            if arg.arg not in skip:
                args.append(arg.arg)
        return args

    # ─── 断言统计 ────────────────────────────────────────

    @staticmethod
    def _count_assertions_in_node(node: ast.AST) -> Dict[str, Any]:
        """统计单个节点内的断言"""
        counts: Dict[str, int] = {}
        total = 0
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                total += 1
                counts["assert"] = counts.get("assert", 0) + 1
            elif isinstance(child, ast.Call):
                func = child.func
                name = None
                if isinstance(func, ast.Attribute):
                    attr = func.attr
                    if attr.startswith("assert"):
                        name = attr
                elif isinstance(func, ast.Name) and func.id.startswith("assert"):
                    name = func.id
                if name:
                    total += 1
                    counts[name] = counts.get(name, 0) + 1
            elif isinstance(child, ast.With):
                for item in child.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Call):
                        if isinstance(ctx.func, ast.Attribute):
                            if (isinstance(ctx.func.value, ast.Name) and
                                    ctx.func.value.id == "pytest" and
                                    ctx.func.attr == "raises"):
                                total += 1
                                counts["pytest.raises"] = counts.get("pytest.raises", 0) + 1
        return {"total": total, "by_type": counts}

    @staticmethod
    def _count_all_assertions(tree: ast.Module) -> Dict[str, Any]:
        """统计整个模块的断言"""
        counts: Dict[str, int] = {}
        total = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                total += 1
                counts["assert"] = counts.get("assert", 0) + 1
            elif isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Attribute):
                    if func.attr.startswith("assert"):
                        name = func.attr
                elif isinstance(func, ast.Name) and func.id.startswith("assert"):
                    name = func.id
                if name:
                    total += 1
                    counts[name] = counts.get(name, 0) + 1
        return {"total": total, "by_type": counts}

    @staticmethod
    def _node_to_str(node: ast.expr) -> str:
        """AST 节点转字符串"""
        try:
            return ast.unparse(node)
        except Exception:
            return ast.dump(node)
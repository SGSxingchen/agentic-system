"""CodeParser 能力插件 - 深度 Python 代码解析

功能:
- 解析 Python 代码生成 AST
- 提取函数/类定义（含嵌套）、导入列表、文档字符串
- 提取装饰器、默认参数、返回值注解
- 输出结构化的代码分析结果
"""
import ast
from typing import Any, Dict, List, Optional, Union

from core.capability.base import CapabilityBase, CapabilitySchema


class CodeParserCapability(CapabilityBase):
    """深度 Python 代码解析能力

    对比 core.capability.native.CodeParserCapability 的增强:
    - 支持嵌套函数/类提取
    - 提取函数返回值注解和参数类型注解
    - 提取全局变量和常量
    - 提取文档字符串（模块级、类级、函数级）
    - 统计代码结构指标（行数、注释数等）
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
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """执行代码解析

        Args:
            code: Python 源代码
            include_nested: 是否包含嵌套定义 (默认 True)

        Returns:
            解析结果字典
        """
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
                    "level": node.level,  # 相对导入层级
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
            # defaults 对齐到参数列表末尾
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

        # 统计各类节点数
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

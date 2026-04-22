"""TestRunner 能力插件 - 测试文件结构解析

功能:
- 解析测试文件中的测试用例结构（不真正执行测试）
- 提取测试函数列表、测试类及其方法
- 统计断言 (assert) 数量和类型
- 检测 pytest fixture 使用、参数化装饰器
- 输出结构化的测试分析报告
"""
import ast
import re
from typing import Any, Dict, List, Optional, Set, Union

from core.capability.base import CapabilityBase, CapabilitySchema


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
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """执行测试文件解析

        Args:
            code: Python 测试源代码
            filename: 文件名（用于报告）

        Returns:
            测试结构分析结果
        """
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

        # 全局断言统计
        all_assertions = self._count_all_assertions(tree)

        # 汇总
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
        """判断是否为测试函数 (test_ 前缀)"""
        return node.name.startswith("test_") or node.name.startswith("test")

    @staticmethod
    def _is_test_class(node: ast.ClassDef) -> bool:
        """判断是否为测试类 (Test 前缀或继承 unittest.TestCase)"""
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
            # @pytest.fixture
            if isinstance(d, ast.Attribute):
                if isinstance(d.value, ast.Name) and d.value.id == "pytest":
                    if d.attr == "fixture":
                        return True
            # @pytest.fixture(...)
            elif isinstance(d, ast.Call):
                if isinstance(d.func, ast.Attribute):
                    if isinstance(d.func.value, ast.Name) and d.func.value.id == "pytest":
                        if d.func.attr == "fixture":
                            return True
            # @fixture (imported directly)
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
            "bases": [
                self._node_to_str(base) for base in node.bases
            ],
        }

    def _parse_fixture(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> Dict[str, Any]:
        """解析 fixture"""
        scope = "function"  # 默认 scope

        # 从装饰器提取 scope 参数
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
            # @pytest.mark.xxx
            if isinstance(d, ast.Attribute):
                if isinstance(d.value, ast.Attribute):
                    if (isinstance(d.value.value, ast.Name) and
                            d.value.value.id == "pytest" and
                            d.value.attr == "mark"):
                        markers.append(d.attr)
            # @pytest.mark.xxx(...)
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
                # 第一个参数是参数名
                param_names = None
                if isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                    param_names = [p.strip() for p in d.args[0].value.split(",")]

                # 第二个参数是参数值列表
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
        """提取函数参数中可能的 fixture 名称

        排除 self, cls, 和常见的非 fixture 参数名
        """
        skip = {"self", "cls"}
        args = []
        for arg in node.args.args:
            if arg.arg not in skip:
                args.append(arg.arg)
        return args

    # ─── 断言统计 ────────────────────────────────────────

    @staticmethod
    def _count_assertions_in_node(
        node: ast.AST,
    ) -> Dict[str, Any]:
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
                # self.assertEqual(...)
                if isinstance(func, ast.Attribute):
                    attr = func.attr
                    if attr.startswith("assert"):
                        name = attr
                # assertEqual(...)  (unlikely but possible)
                elif isinstance(func, ast.Name) and func.id.startswith("assert"):
                    name = func.id

                if name:
                    total += 1
                    counts[name] = counts.get(name, 0) + 1

            # pytest.raises
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

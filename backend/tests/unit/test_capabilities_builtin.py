"""capabilities/builtin/ 模块的综合测试

覆盖:
- CodeParserCapability: AST 解析、函数/类/导入提取、嵌套结构、指标统计
- StaticAnalyzerCapability: 行长度/函数长度/未使用导入/命名/复杂度/文档/可变默认
- TestRunnerCapability: 测试函数/类/fixture/marker/parametrize/断言统计
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

from capabilities.builtin.code_parser import CodeParserCapability
from capabilities.builtin.static_analyzer import StaticAnalyzerCapability
from capabilities.builtin.test_runner import TestRunnerCapability


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def parser():
    return CodeParserCapability()


@pytest.fixture
def analyzer():
    return StaticAnalyzerCapability()


@pytest.fixture
def runner():
    return TestRunnerCapability()


# ══════════════════════════════════════════════════════════
# CodeParserCapability
# ══════════════════════════════════════════════════════════

class TestCodeParserBasic:
    """基本解析功能"""

    @pytest.mark.asyncio
    async def test_parse_simple_function(self, parser):
        code = 'def hello(name):\n    return f"Hello {name}"'
        result = await parser.execute(code=code)
        assert len(result["functions"]) == 1
        fn = result["functions"][0]
        assert fn["name"] == "hello"
        assert fn["is_async"] is False
        assert len(fn["args"]) == 1
        assert fn["args"][0]["name"] == "name"

    @pytest.mark.asyncio
    async def test_parse_async_function(self, parser):
        code = "async def fetch(url):\n    pass"
        result = await parser.execute(code=code)
        assert len(result["functions"]) == 1
        assert result["functions"][0]["is_async"] is True
        assert result["functions"][0]["name"] == "fetch"

    @pytest.mark.asyncio
    async def test_parse_class(self, parser):
        code = (
            "class Animal:\n"
            '    """An animal."""\n'
            "    def speak(self):\n"
            "        pass\n"
        )
        result = await parser.execute(code=code)
        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "Animal"
        assert cls["docstring"] == "An animal."
        assert len(cls["methods"]) == 1

    @pytest.mark.asyncio
    async def test_parse_import(self, parser):
        code = "import os\nimport sys as system"
        result = await parser.execute(code=code)
        assert len(result["imports"]) == 2
        assert result["imports"][0]["type"] == "import"
        assert result["imports"][0]["module"] == "os"
        assert result["imports"][0]["alias"] is None
        assert result["imports"][1]["module"] == "sys"
        assert result["imports"][1]["alias"] == "system"

    @pytest.mark.asyncio
    async def test_parse_from_import(self, parser):
        code = "from os.path import join, exists as ex"
        result = await parser.execute(code=code)
        assert len(result["imports"]) == 1
        imp = result["imports"][0]
        assert imp["type"] == "from_import"
        assert imp["module"] == "os.path"
        assert imp["level"] == 0
        names = imp["names"]
        assert len(names) == 2
        assert names[0]["name"] == "join"
        assert names[0]["alias"] is None
        assert names[1]["name"] == "exists"
        assert names[1]["alias"] == "ex"

    @pytest.mark.asyncio
    async def test_parse_relative_import(self, parser):
        code = "from ..utils import helper"
        result = await parser.execute(code=code)
        imp = result["imports"][0]
        assert imp["type"] == "from_import"
        assert imp["level"] == 2
        assert imp["module"] == "utils"

    @pytest.mark.asyncio
    async def test_syntax_error_handling(self, parser):
        code = "def broken(\n"
        result = await parser.execute(code=code)
        assert "error" in result
        assert "SyntaxError" in result["error"]
        assert result["functions"] == []
        assert result["classes"] == []
        assert result["imports"] == []
        assert result["docstring"] is None
        assert result["metrics"] == {}


class TestCodeParserAdvanced:
    """高级解析功能"""

    @pytest.mark.asyncio
    async def test_decorators(self, parser):
        code = (
            "@staticmethod\n"
            "def my_func():\n"
            "    pass\n"
        )
        result = await parser.execute(code=code)
        fn = result["functions"][0]
        assert "staticmethod" in fn["decorators"]

    @pytest.mark.asyncio
    async def test_return_annotation(self, parser):
        code = "def greet(name: str) -> str:\n    return name"
        result = await parser.execute(code=code)
        fn = result["functions"][0]
        assert fn["return_annotation"] == "str"

    @pytest.mark.asyncio
    async def test_type_annotations(self, parser):
        code = "def add(a: int, b: int = 0) -> int:\n    return a + b"
        result = await parser.execute(code=code)
        fn = result["functions"][0]
        assert fn["args"][0]["annotation"] == "int"
        assert fn["args"][1]["annotation"] == "int"
        assert fn["args"][1]["default"] == "0"

    @pytest.mark.asyncio
    async def test_nested_functions(self, parser):
        code = (
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    return inner\n"
        )
        result = await parser.execute(code=code, include_nested=True)
        fn = result["functions"][0]
        assert fn["name"] == "outer"
        assert "nested_functions" in fn
        assert fn["nested_functions"][0]["name"] == "inner"

    @pytest.mark.asyncio
    async def test_nested_classes(self, parser):
        code = (
            "class Outer:\n"
            "    class Inner:\n"
            "        pass\n"
        )
        result = await parser.execute(code=code, include_nested=True)
        cls = result["classes"][0]
        assert cls["name"] == "Outer"
        assert "nested_classes" in cls
        assert cls["nested_classes"][0]["name"] == "Inner"

    @pytest.mark.asyncio
    async def test_include_nested_false(self, parser):
        code = (
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    return inner\n"
        )
        result = await parser.execute(code=code, include_nested=False)
        fn = result["functions"][0]
        assert "nested_functions" not in fn

    @pytest.mark.asyncio
    async def test_include_nested_false_class_methods_as_strings(self, parser):
        code = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
        )
        result = await parser.execute(code=code, include_nested=False)
        cls = result["classes"][0]
        # When include_nested=False, methods are stored as name strings
        assert cls["methods"] == ["bar"]

    @pytest.mark.asyncio
    async def test_module_docstring(self, parser):
        code = '"""This is a module docstring."""\n\nx = 1'
        result = await parser.execute(code=code)
        assert result["docstring"] == "This is a module docstring."

    @pytest.mark.asyncio
    async def test_no_module_docstring(self, parser):
        code = "x = 1"
        result = await parser.execute(code=code)
        assert result["docstring"] is None

    @pytest.mark.asyncio
    async def test_global_assignments(self, parser):
        code = "MAX_SIZE = 100\nname = 'hello'"
        result = await parser.execute(code=code)
        assigns = result["top_level_assignments"]
        assert len(assigns) == 2
        assert assigns[0]["name"] == "MAX_SIZE"
        assert assigns[0]["is_constant"] is True
        assert assigns[1]["name"] == "name"
        assert assigns[1]["is_constant"] is False

    @pytest.mark.asyncio
    async def test_annotated_assignment(self, parser):
        code = "count: int = 0"
        result = await parser.execute(code=code)
        assigns = result["top_level_assignments"]
        assert len(assigns) == 1
        assert assigns[0]["name"] == "count"
        assert assigns[0]["annotation"] == "int"

    @pytest.mark.asyncio
    async def test_class_with_bases(self, parser):
        code = (
            "class Child(Parent, Mixin):\n"
            "    pass\n"
        )
        result = await parser.execute(code=code)
        cls = result["classes"][0]
        assert cls["bases"] == ["Parent", "Mixin"]

    @pytest.mark.asyncio
    async def test_class_variables(self, parser):
        code = (
            "class Config:\n"
            "    debug: bool = True\n"
            "    name = 'app'\n"
        )
        result = await parser.execute(code=code)
        cls = result["classes"][0]
        var_names = [v["name"] for v in cls["class_variables"]]
        assert "debug" in var_names
        assert "name" in var_names

    @pytest.mark.asyncio
    async def test_class_decorators(self, parser):
        code = (
            "@dataclass\n"
            "class Point:\n"
            "    x: int\n"
            "    y: int\n"
        )
        result = await parser.execute(code=code)
        cls = result["classes"][0]
        assert "dataclass" in cls["decorators"]

    @pytest.mark.asyncio
    async def test_function_docstring(self, parser):
        code = (
            "def hello():\n"
            '    """Say hello."""\n'
            "    pass\n"
        )
        result = await parser.execute(code=code)
        assert result["functions"][0]["docstring"] == "Say hello."

    @pytest.mark.asyncio
    async def test_call_decorator(self, parser):
        code = (
            "@app.route('/home')\n"
            "def home():\n"
            "    pass\n"
        )
        result = await parser.execute(code=code)
        fn = result["functions"][0]
        assert "app.route" in fn["decorators"]


class TestCodeParserMetrics:
    """代码指标计算"""

    @pytest.mark.asyncio
    async def test_metrics_total_lines(self, parser):
        code = "a = 1\nb = 2\nc = 3\n"
        result = await parser.execute(code=code)
        assert result["metrics"]["total_lines"] == 3

    @pytest.mark.asyncio
    async def test_metrics_blank_lines(self, parser):
        code = "a = 1\n\nb = 2\n\n"
        result = await parser.execute(code=code)
        assert result["metrics"]["blank_lines"] == 2

    @pytest.mark.asyncio
    async def test_metrics_comment_lines(self, parser):
        code = "# comment\na = 1\n# another\n"
        result = await parser.execute(code=code)
        assert result["metrics"]["comment_lines"] == 2

    @pytest.mark.asyncio
    async def test_metrics_code_lines(self, parser):
        code = "# comment\na = 1\n\nb = 2\n"
        result = await parser.execute(code=code)
        m = result["metrics"]
        assert m["code_lines"] == m["total_lines"] - m["blank_lines"] - m["comment_lines"]
        assert m["code_lines"] == 2

    @pytest.mark.asyncio
    async def test_metrics_function_count(self, parser):
        code = "def a():\n    pass\ndef b():\n    pass\n"
        result = await parser.execute(code=code)
        assert result["metrics"]["function_count"] == 2

    @pytest.mark.asyncio
    async def test_metrics_class_count(self, parser):
        code = "class A:\n    pass\nclass B:\n    pass\n"
        result = await parser.execute(code=code)
        assert result["metrics"]["class_count"] == 2

    @pytest.mark.asyncio
    async def test_metrics_nested_counted(self, parser):
        """ast.walk counts nested functions/classes too."""
        code = (
            "class Outer:\n"
            "    def method(self):\n"
            "        def inner():\n"
            "            pass\n"
        )
        result = await parser.execute(code=code)
        assert result["metrics"]["function_count"] == 2
        assert result["metrics"]["class_count"] == 1

    @pytest.mark.asyncio
    async def test_schema(self, parser):
        schema = parser.get_schema()
        assert schema.name == "code_parser"
        assert "code" in schema.parameters["properties"]


# ══════════════════════════════════════════════════════════
# StaticAnalyzerCapability
# ══════════════════════════════════════════════════════════

class TestStaticAnalyzerLineLength:

    @pytest.mark.asyncio
    async def test_line_too_long_default(self, analyzer):
        code = "x = " + "'" + "a" * 200 + "'"
        result = await analyzer.execute(code=code, checks=["line_too_long"])
        issues = result["issues"]
        assert len(issues) >= 1
        assert issues[0]["type"] == "line_too_long"
        assert issues[0]["severity"] == "warning"

    @pytest.mark.asyncio
    async def test_line_within_limit(self, analyzer):
        code = "x = 1"
        result = await analyzer.execute(code=code, checks=["line_too_long"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_custom_max_line_length(self, analyzer):
        code = "x = 'hello world'"  # 17 chars
        result = await analyzer.execute(code=code, max_line_length=10, checks=["line_too_long"])
        assert len(result["issues"]) == 1
        assert "17 > 10" in result["issues"][0]["message"]


class TestStaticAnalyzerFunctionLength:

    @pytest.mark.asyncio
    async def test_function_too_long(self, analyzer):
        lines = ["def long_func():"]
        for i in range(60):
            lines.append(f"    x{i} = {i}")
        code = "\n".join(lines)
        result = await analyzer.execute(code=code, max_function_length=50, checks=["function_too_long"])
        assert len(result["issues"]) >= 1
        assert result["issues"][0]["type"] == "function_too_long"

    @pytest.mark.asyncio
    async def test_function_within_limit(self, analyzer):
        code = "def short():\n    pass\n"
        result = await analyzer.execute(code=code, checks=["function_too_long"])
        assert len(result["issues"]) == 0


class TestStaticAnalyzerUnusedImport:

    @pytest.mark.asyncio
    async def test_unused_import_detected(self, analyzer):
        code = "import os\nx = 1"
        result = await analyzer.execute(code=code, checks=["unused_import"])
        issues = result["issues"]
        assert len(issues) == 1
        assert issues[0]["type"] == "unused_import"
        assert "'os'" in issues[0]["message"]

    @pytest.mark.asyncio
    async def test_used_import_not_flagged(self, analyzer):
        code = "import os\npath = os.getcwd()"
        result = await analyzer.execute(code=code, checks=["unused_import"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_from_import_unused(self, analyzer):
        code = "from os.path import join\nx = 1"
        result = await analyzer.execute(code=code, checks=["unused_import"])
        assert len(result["issues"]) == 1
        assert "'join'" in result["issues"][0]["message"]

    @pytest.mark.asyncio
    async def test_underscore_import_skipped(self, analyzer):
        code = "from module import _private\nx = 1"
        result = await analyzer.execute(code=code, checks=["unused_import"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_future_import_skipped(self, analyzer):
        code = "from __future__ import annotations\nx = 1"
        result = await analyzer.execute(code=code, checks=["unused_import"])
        assert len(result["issues"]) == 0


class TestStaticAnalyzerNaming:

    @pytest.mark.asyncio
    async def test_bad_function_name(self, analyzer):
        code = "def BadName():\n    pass"
        result = await analyzer.execute(code=code, checks=["naming_convention"])
        types = [i["type"] for i in result["issues"]]
        assert "naming_convention" in types

    @pytest.mark.asyncio
    async def test_good_function_name(self, analyzer):
        code = "def good_name():\n    pass"
        result = await analyzer.execute(code=code, checks=["naming_convention"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_bad_class_name(self, analyzer):
        code = "class bad_class:\n    pass"
        result = await analyzer.execute(code=code, checks=["naming_convention"])
        assert any(i["type"] == "naming_convention" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_good_class_name(self, analyzer):
        code = "class GoodClass:\n    pass"
        result = await analyzer.execute(code=code, checks=["naming_convention"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_dunder_method_skipped(self, analyzer):
        code = "class A:\n    def __init__(self):\n        pass"
        result = await analyzer.execute(code=code, checks=["naming_convention"])
        func_issues = [i for i in result["issues"] if "Function" in i.get("message", "")]
        assert len(func_issues) == 0


class TestStaticAnalyzerComplexity:

    @pytest.mark.asyncio
    async def test_high_complexity(self, analyzer):
        # Build a function with many branches
        lines = ["def complex_func(x):"]
        for i in range(12):
            lines.append(f"    if x == {i}:")
            lines.append(f"        return {i}")
        lines.append("    return -1")
        code = "\n".join(lines)
        result = await analyzer.execute(code=code, max_complexity=10, checks=["high_complexity"])
        assert any(i["type"] == "high_complexity" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_low_complexity(self, analyzer):
        code = "def simple(x):\n    return x + 1"
        result = await analyzer.execute(code=code, checks=["high_complexity"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_custom_max_complexity(self, analyzer):
        code = (
            "def func(x):\n"
            "    if x > 0:\n"
            "        return 1\n"
            "    return 0\n"
        )
        # complexity = 1 (base) + 1 (if) = 2, threshold = 1
        result = await analyzer.execute(code=code, max_complexity=1, checks=["high_complexity"])
        assert len(result["issues"]) == 1
        assert result["issues"][0]["complexity"] == 2


class TestStaticAnalyzerDocstring:

    @pytest.mark.asyncio
    async def test_missing_docstring(self, analyzer):
        code = "def public_func():\n    pass"
        result = await analyzer.execute(code=code, checks=["missing_docstring"])
        assert any(i["type"] == "missing_docstring" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_has_docstring(self, analyzer):
        code = 'def public_func():\n    """Docstring."""\n    pass'
        result = await analyzer.execute(code=code, checks=["missing_docstring"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_private_func_no_docstring_ok(self, analyzer):
        code = "def _private():\n    pass"
        result = await analyzer.execute(code=code, checks=["missing_docstring"])
        assert len(result["issues"]) == 0

    @pytest.mark.asyncio
    async def test_missing_class_docstring(self, analyzer):
        code = "class Public:\n    pass"
        result = await analyzer.execute(code=code, checks=["missing_docstring"])
        assert any("class" in i["message"].lower() or "Class" in i["message"] for i in result["issues"])


class TestStaticAnalyzerMutableDefault:

    @pytest.mark.asyncio
    async def test_mutable_list_default(self, analyzer):
        code = "def func(x=[]):\n    pass"
        result = await analyzer.execute(code=code, checks=["mutable_default"])
        assert any(i["type"] == "mutable_default" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_mutable_dict_default(self, analyzer):
        code = "def func(x={}):\n    pass"
        result = await analyzer.execute(code=code, checks=["mutable_default"])
        assert any(i["type"] == "mutable_default" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_mutable_set_default(self, analyzer):
        code = "def func(x={1, 2}):\n    pass"
        result = await analyzer.execute(code=code, checks=["mutable_default"])
        assert any(i["type"] == "mutable_default" for i in result["issues"])

    @pytest.mark.asyncio
    async def test_immutable_default_ok(self, analyzer):
        code = "def func(x=None, y=0, z='hello'):\n    pass"
        result = await analyzer.execute(code=code, checks=["mutable_default"])
        assert len(result["issues"]) == 0


class TestStaticAnalyzerGeneral:

    @pytest.mark.asyncio
    async def test_syntax_error(self, analyzer):
        code = "def broken(:\n    pass"
        result = await analyzer.execute(code=code)
        assert any(i["type"] == "syntax_error" for i in result["issues"])
        assert result["summary"]["total"] >= 1

    @pytest.mark.asyncio
    async def test_selective_checks(self, analyzer):
        code = "import os\ndef BadName():\n    pass"
        result = await analyzer.execute(code=code, checks=["unused_import"])
        types = {i["type"] for i in result["issues"]}
        assert "unused_import" in types
        assert "naming_convention" not in types

    @pytest.mark.asyncio
    async def test_summary_statistics(self, analyzer):
        code = (
            "import os\n"
            "import sys\n"
            "def BadName():\n"
            "    pass\n"
        )
        result = await analyzer.execute(code=code, checks=["unused_import", "naming_convention"])
        summary = result["summary"]
        assert summary["total"] >= 2
        assert "by_type" in summary

    @pytest.mark.asyncio
    async def test_clean_code(self, analyzer):
        code = (
            '"""Module doc."""\n'
            "import os\n\n"
            "def get_cwd():\n"
            '    """Get current directory."""\n'
            "    return os.getcwd()\n"
        )
        result = await analyzer.execute(code=code)
        assert result["summary"]["total"] == 0

    @pytest.mark.asyncio
    async def test_issues_sorted_by_line(self, analyzer):
        code = (
            "import zzz\n"
            "import aaa\n"
            "x = 1\n"
        )
        result = await analyzer.execute(code=code, checks=["unused_import"])
        lines = [i["line"] for i in result["issues"]]
        assert lines == sorted(lines)

    @pytest.mark.asyncio
    async def test_schema(self, analyzer):
        schema = analyzer.get_schema()
        assert schema.name == "static_analyzer"
        assert "code" in schema.parameters["properties"]


# ══════════════════════════════════════════════════════════
# TestRunnerCapability
# ══════════════════════════════════════════════════════════

class TestTestRunnerBasic:

    @pytest.mark.asyncio
    async def test_parse_test_functions(self, runner):
        code = (
            "def test_add():\n"
            "    assert 1 + 1 == 2\n\n"
            "def test_sub():\n"
            "    assert 2 - 1 == 1\n"
        )
        result = await runner.execute(code=code)
        assert len(result["test_cases"]) == 2
        assert result["test_cases"][0]["name"] == "test_add"
        assert result["test_cases"][1]["name"] == "test_sub"

    @pytest.mark.asyncio
    async def test_parse_test_class(self, runner):
        code = (
            "class TestMath:\n"
            "    def test_add(self):\n"
            "        assert 1 + 1 == 2\n"
            "    def test_sub(self):\n"
            "        assert 2 - 1 == 1\n"
        )
        result = await runner.execute(code=code)
        assert len(result["test_classes"]) == 1
        tc = result["test_classes"][0]
        assert tc["name"] == "TestMath"
        assert tc["test_count"] == 2

    @pytest.mark.asyncio
    async def test_async_test_function(self, runner):
        code = (
            "async def test_async():\n"
            "    assert True\n"
        )
        result = await runner.execute(code=code)
        assert len(result["test_cases"]) == 1
        assert result["test_cases"][0]["is_async"] is True

    @pytest.mark.asyncio
    async def test_syntax_error(self, runner):
        code = "def test_broken(\n"
        result = await runner.execute(code=code)
        assert "error" in result
        assert "SyntaxError" in result["error"]
        assert result["test_cases"] == []

    @pytest.mark.asyncio
    async def test_filename_in_result(self, runner):
        code = "def test_x():\n    pass"
        result = await runner.execute(code=code, filename="test_example.py")
        assert result["filename"] == "test_example.py"
        assert result["summary"]["filename"] == "test_example.py"

    @pytest.mark.asyncio
    async def test_default_filename(self, runner):
        code = "def test_x():\n    pass"
        result = await runner.execute(code=code)
        assert result["filename"] == "<test>"


class TestTestRunnerFixtures:

    @pytest.mark.asyncio
    async def test_parse_fixture_simple(self, runner):
        code = (
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def sample():\n"
            "    return 42\n"
        )
        result = await runner.execute(code=code)
        assert len(result["fixtures"]) == 1
        assert result["fixtures"][0]["name"] == "sample"
        assert result["fixtures"][0]["scope"] == "function"

    @pytest.mark.asyncio
    async def test_parse_fixture_with_scope(self, runner):
        code = (
            "import pytest\n\n"
            "@pytest.fixture(scope='session')\n"
            "def db():\n"
            "    return 'db'\n"
        )
        result = await runner.execute(code=code)
        assert len(result["fixtures"]) == 1
        assert result["fixtures"][0]["scope"] == "session"

    @pytest.mark.asyncio
    async def test_fixture_args_extracted(self, runner):
        code = (
            "def test_with_fixtures(db, client, tmp_path):\n"
            "    assert db is not None\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_cases"][0]
        assert "db" in tc["fixture_args"]
        assert "client" in tc["fixture_args"]
        assert "tmp_path" in tc["fixture_args"]

    @pytest.mark.asyncio
    async def test_self_cls_excluded_from_fixture_args(self, runner):
        code = (
            "class TestSomething:\n"
            "    def test_method(self, db):\n"
            "        pass\n"
        )
        result = await runner.execute(code=code)
        method = result["test_classes"][0]["test_methods"][0]
        assert "self" not in method["fixture_args"]
        assert "db" in method["fixture_args"]


class TestTestRunnerMarkers:

    @pytest.mark.asyncio
    async def test_detect_skip_marker(self, runner):
        code = (
            "import pytest\n\n"
            "@pytest.mark.skip\n"
            "def test_skipped():\n"
            "    pass\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_cases"][0]
        assert "skip" in tc["markers"]

    @pytest.mark.asyncio
    async def test_detect_marker_with_call(self, runner):
        code = (
            "import pytest\n\n"
            "@pytest.mark.skipif(True, reason='nope')\n"
            "def test_conditional():\n"
            "    pass\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_cases"][0]
        assert "skipif" in tc["markers"]

    @pytest.mark.asyncio
    async def test_no_markers(self, runner):
        code = "def test_plain():\n    pass"
        result = await runner.execute(code=code)
        assert result["test_cases"][0]["markers"] == []


class TestTestRunnerParametrize:

    @pytest.mark.asyncio
    async def test_parametrize_detected(self, runner):
        code = (
            "import pytest\n\n"
            "@pytest.mark.parametrize('x,y', [(1,2), (3,4), (5,6)])\n"
            "def test_add(x, y):\n"
            "    pass\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_cases"][0]
        assert tc["parametrize"] is not None
        assert tc["parametrize"]["param_names"] == ["x", "y"]
        assert tc["parametrize"]["case_count"] == 3

    @pytest.mark.asyncio
    async def test_no_parametrize(self, runner):
        code = "def test_plain():\n    pass"
        result = await runner.execute(code=code)
        assert result["test_cases"][0]["parametrize"] is None


class TestTestRunnerAssertions:

    @pytest.mark.asyncio
    async def test_count_assert_statements(self, runner):
        code = (
            "def test_multi():\n"
            "    assert 1 == 1\n"
            "    assert 2 == 2\n"
            "    assert 3 == 3\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_cases"][0]
        assert tc["assertions"]["total"] == 3
        assert tc["assertions"]["by_type"]["assert"] == 3

    @pytest.mark.asyncio
    async def test_count_self_assert_methods(self, runner):
        code = (
            "class TestCase:\n"
            "    def test_eq(self):\n"
            "        self.assertEqual(1, 1)\n"
            "        self.assertTrue(True)\n"
        )
        result = await runner.execute(code=code)
        method = result["test_classes"][0]["test_methods"][0]
        assert method["assertions"]["total"] == 2
        assert method["assertions"]["by_type"].get("assertEqual") == 1
        assert method["assertions"]["by_type"].get("assertTrue") == 1

    @pytest.mark.asyncio
    async def test_count_pytest_raises(self, runner):
        code = (
            "import pytest\n\n"
            "def test_raises():\n"
            "    with pytest.raises(ValueError):\n"
            "        raise ValueError('x')\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_cases"][0]
        assert tc["assertions"]["total"] >= 1
        assert tc["assertions"]["by_type"].get("pytest.raises") == 1

    @pytest.mark.asyncio
    async def test_global_assertion_count(self, runner):
        code = (
            "def test_a():\n"
            "    assert True\n"
            "def test_b():\n"
            "    assert False\n"
        )
        result = await runner.execute(code=code)
        assert result["summary"]["total_assertions"] == 2


class TestTestRunnerSetupTeardown:

    @pytest.mark.asyncio
    async def test_setup_teardown_detected(self, runner):
        code = (
            "class TestWithSetup:\n"
            "    def setUp(self):\n"
            "        pass\n"
            "    def tearDown(self):\n"
            "        pass\n"
            "    def test_something(self):\n"
            "        assert True\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_classes"][0]
        assert "setUp" in tc["setup_teardown"]
        assert "tearDown" in tc["setup_teardown"]

    @pytest.mark.asyncio
    async def test_pytest_setup_teardown(self, runner):
        code = (
            "class TestPytest:\n"
            "    def setup_method(self):\n"
            "        pass\n"
            "    def teardown_method(self):\n"
            "        pass\n"
            "    def test_x(self):\n"
            "        pass\n"
        )
        result = await runner.execute(code=code)
        tc = result["test_classes"][0]
        assert "setup_method" in tc["setup_teardown"]
        assert "teardown_method" in tc["setup_teardown"]


class TestTestRunnerSummary:

    @pytest.mark.asyncio
    async def test_summary_counts(self, runner):
        code = (
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def data():\n"
            "    return [1,2,3]\n\n"
            "def test_one(data):\n"
            "    assert len(data) == 3\n\n"
            "class TestGroup:\n"
            "    def test_two(self):\n"
            "        assert True\n"
            "    def test_three(self):\n"
            "        assert True\n"
        )
        result = await runner.execute(code=code)
        s = result["summary"]
        assert s["test_functions"] == 1
        assert s["test_classes"] == 1
        assert s["fixtures"] == 1
        assert s["total_tests"] == 3  # 1 function + 2 methods

    @pytest.mark.asyncio
    async def test_empty_file(self, runner):
        code = "# no tests here\nx = 1\n"
        result = await runner.execute(code=code)
        assert result["summary"]["total_tests"] == 0
        assert result["summary"]["test_functions"] == 0
        assert result["summary"]["test_classes"] == 0

    @pytest.mark.asyncio
    async def test_unittest_testcase_detected(self, runner):
        code = (
            "import unittest\n\n"
            "class TestStuff(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertEqual(1, 1)\n"
        )
        result = await runner.execute(code=code)
        assert len(result["test_classes"]) == 1
        assert result["test_classes"][0]["bases"] == ["unittest.TestCase"]

    @pytest.mark.asyncio
    async def test_test_docstring(self, runner):
        code = (
            'def test_documented():\n'
            '    """Test with docs."""\n'
            '    assert True\n'
        )
        result = await runner.execute(code=code)
        assert result["test_cases"][0]["docstring"] == "Test with docs."

    @pytest.mark.asyncio
    async def test_schema(self, runner):
        schema = runner.get_schema()
        assert schema.name == "test_runner"
        assert "code" in schema.parameters["properties"]

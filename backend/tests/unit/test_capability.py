"""能力系统 - 单元测试"""
import sys
from pathlib import Path

import pytest

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.capability.base import CapabilityBase, CapabilitySchema
from core.capability.dynamic import DynamicToolCapability, load_dynamic_capabilities
from core.capability.prompt_override import apply_prompt_override, unwrap_capability
from core.capability.registry import CapabilityRegistry
from core.capability.native import CodeParserCapability, StaticAnalyzerCapability

# 新版能力插件 (capabilities/builtin)
from capabilities.builtin.code_parser import (
    CodeParserCapability as CodeParserV2,
)
from capabilities.builtin.static_analyzer import (
    StaticAnalyzerCapability as StaticAnalyzerV2,
)
from capabilities.builtin.test_runner import TestRunnerCapability


# ─── CapabilitySchema ──────────────────────────────────────


def test_schema_to_dict():
    """Schema to_dict"""
    schema = CapabilitySchema(
        name="test",
        description="A test capability",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        returns="integer",
    )
    d = schema.to_dict()
    assert d["name"] == "test"
    assert d["parameters"]["type"] == "object"


# ─── CapabilityRegistry ───────────────────────────────────


@pytest.fixture
def registry():
    return CapabilityRegistry()


@pytest.fixture
def parser():
    return CodeParserCapability()


@pytest.fixture
def analyzer():
    return StaticAnalyzerCapability()


def test_register_native(registry: CapabilityRegistry, parser: CodeParserCapability):
    """注册原生能力"""
    registry.register_native(parser)
    assert "code_parser" in registry
    assert len(registry) == 1


def test_list_all(registry: CapabilityRegistry, parser, analyzer):
    """列出所有能力"""
    registry.register_native(parser)
    registry.register_native(analyzer)
    schemas = registry.list_all()
    assert len(schemas) == 2
    names = {s.name for s in schemas}
    assert names == {"code_parser", "static_analyzer"}


def test_get(registry: CapabilityRegistry, parser):
    """按名称获取能力"""
    registry.register_native(parser)
    cap = registry.get("code_parser")
    assert cap is parser
    assert registry.get("nonexistent") is None


@pytest.mark.asyncio
async def test_execute_not_found(registry: CapabilityRegistry):
    """执行不存在的能力抛 KeyError"""
    with pytest.raises(KeyError, match="not_registered"):
        await registry.execute("not_registered", code="x")


def test_list_names(registry: CapabilityRegistry):
    """列出所有能力名称"""
    names = registry.list_names()
    assert isinstance(names, list)


# ─── CodeParserCapability ─────────────────────────────────


@pytest.mark.asyncio
async def test_code_parser_basic():
    """解析基本 Python 代码"""
    parser = CodeParserCapability()
    code = '''
import os
from pathlib import Path

class MyClass:
    """A test class"""
    def method(self):
        pass

def hello(name: str):
    """Say hello"""
    return f"Hello, {name}"

async def async_fn():
    pass

MAX_SIZE = 100
'''
    result = await parser.execute(code=code)
    assert len(result["functions"]) == 2  # hello, async_fn
    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "MyClass"
    methods = result["classes"][0]["methods"]
    method_names = [m["name"] if isinstance(m, dict) else m for m in methods]
    assert "method" in method_names
    assert len(result["imports"]) == 2  # os, Path
    assert len(result["top_level_assignments"]) == 1
    assert result["top_level_assignments"][0]["name"] == "MAX_SIZE"


@pytest.mark.asyncio
async def test_code_parser_async_function():
    """识别异步函数"""
    parser = CodeParserCapability()
    result = await parser.execute(code="async def foo(x, y): pass")
    assert result["functions"][0]["is_async"] is True
    args = result["functions"][0]["args"]
    arg_names = [a["name"] if isinstance(a, dict) else a for a in args]
    assert arg_names == ["x", "y"]


@pytest.mark.asyncio
async def test_code_parser_syntax_error():
    """语法错误时返回 error 字段"""
    parser = CodeParserCapability()
    result = await parser.execute(code="def foo(:\n  pass")
    assert "error" in result
    assert "SyntaxError" in result["error"]


@pytest.mark.asyncio
async def test_code_parser_validate_input():
    """验证输入"""
    parser = CodeParserCapability()
    assert parser.validate_input(code="x = 1") is True
    assert parser.validate_input() is False  # 缺少 required 参数 code


@pytest.mark.asyncio
async def test_code_parser_schema():
    """Schema 格式正确"""
    parser = CodeParserCapability()
    schema = parser.get_schema()
    assert schema.name == "code_parser"
    assert "code" in schema.parameters["properties"]
    assert "code" in schema.parameters["required"]


# ─── StaticAnalyzerCapability ─────────────────────────────


@pytest.mark.asyncio
async def test_static_analyzer_line_length():
    """检测过长的行"""
    analyzer = StaticAnalyzerCapability()
    long_line = "x = " + "a" * 200
    result = await analyzer.execute(code=long_line, max_line_length=80)
    issues = result["issues"]
    assert any(i["type"] == "line_too_long" for i in issues)


@pytest.mark.asyncio
async def test_static_analyzer_function_length():
    """检测过长的函数"""
    analyzer = StaticAnalyzerCapability()
    # 生成一个 60 行的函数
    lines = ["def long_func():"]
    for i in range(59):
        lines.append(f"    x_{i} = {i}")
    code = "\n".join(lines)

    result = await analyzer.execute(code=code, max_function_length=30)
    issues = result["issues"]
    assert any(i["type"] == "function_too_long" for i in issues)


@pytest.mark.asyncio
async def test_static_analyzer_unused_import():
    """检测未使用的导入"""
    analyzer = StaticAnalyzerCapability()
    code = "import os\nimport sys\nprint(sys.argv)"
    result = await analyzer.execute(code=code)
    issues = result["issues"]
    unused = [i for i in issues if i["type"] == "unused_import"]
    assert len(unused) == 1
    assert "os" in unused[0]["message"]


@pytest.mark.asyncio
async def test_static_analyzer_clean_code():
    """干净的代码没有问题"""
    analyzer = StaticAnalyzerCapability()
    code = "import os\npath = os.getcwd()\nprint(path)"
    result = await analyzer.execute(code=code)
    assert result["summary"]["total"] == 0


@pytest.mark.asyncio
async def test_static_analyzer_syntax_error():
    """语法错误时报告 syntax_error"""
    analyzer = StaticAnalyzerCapability()
    result = await analyzer.execute(code="def foo(:\n  pass")
    issues = result["issues"]
    assert any(i["type"] == "syntax_error" for i in issues)


@pytest.mark.asyncio
async def test_static_analyzer_summary():
    """摘要统计"""
    analyzer = StaticAnalyzerCapability()
    code = "import os\nimport sys\n" + "a" * 200
    result = await analyzer.execute(code=code, max_line_length=80)
    summary = result["summary"]
    assert "total" in summary
    assert summary["total"] > 0


# ─── Registry execute 集成 ─────────────────────────────────


@pytest.mark.asyncio
async def test_registry_execute():
    """通过 registry 执行能力"""
    registry = CapabilityRegistry()
    registry.register_native(CodeParserCapability())
    result = await registry.execute("code_parser", code="x = 1")
    assert "functions" in result
    assert "imports" in result


# ─── DynamicToolCapability ────────────────────────────────


@pytest.mark.asyncio
async def test_dynamic_template_tool():
    """动态模板工具可渲染输入字段"""
    tool = DynamicToolCapability(
        name="story_tool",
        mode="template",
        config={"template": "需求: {{text}} / 风格: {{style}}"},
    )
    result = await tool.execute(text="创建登录接口", style="简洁")
    assert result["text"] == "需求: 创建登录接口 / 风格: 简洁"


@pytest.mark.asyncio
async def test_dynamic_checklist_tool():
    """动态清单工具返回缺失项和评分"""
    tool = DynamicToolCapability(
        name="requirement_check",
        mode="checklist",
        config={
            "required_terms": ["目标", "输入", "输出"],
            "forbidden_terms": ["随便"],
        },
    )
    result = await tool.execute(text="目标是生成 API，输入为用户信息")
    assert result["passed"] is False
    assert "输出" in result["missing_required"]
    assert result["score"] < 1


@pytest.mark.asyncio
async def test_dynamic_regex_extract_tool():
    """动态正则工具可抽取结构化信息"""
    tool = DynamicToolCapability(
        name="extract_contact",
        mode="regex_extract",
        config={"patterns": {"email": r"[\w.-]+@[\w.-]+"}},
    )
    result = await tool.execute(text="联系 dev@example.com")
    assert result["matches"]["email"] == ["dev@example.com"]
    assert result["summary"]["match_count"] == 1


def test_load_dynamic_capabilities_registers_tools():
    """从配置批量注册动态工具"""
    registry = CapabilityRegistry()
    loaded = load_dynamic_capabilities(
        registry,
        [
            {
                "name": "simple_template",
                "type": "dynamic",
                "mode": "template",
                "config": {"template": "{{text}}"},
            }
        ],
    )
    assert loaded == ["simple_template"]
    assert "simple_template" in registry


def test_prompt_override_changes_schema_only(registry: CapabilityRegistry, parser):
    """工具提示词覆盖只改变 description，不改变执行和 JSON Schema。"""
    registry.register_native(parser)
    before = registry.get("code_parser").get_schema()

    assert apply_prompt_override(registry, "code_parser", "新的 Tool 提示词") is True

    wrapped = registry.get("code_parser")
    after = wrapped.get_schema()
    assert after.description == "新的 Tool 提示词"
    assert after.parameters == before.parameters
    assert unwrap_capability(wrapped) is parser


# ═══════════════════════════════════════════════════════════
#  新版能力插件 (capabilities/builtin) 单元测试
# ═══════════════════════════════════════════════════════════


# ─── CodeParserV2 ──────────────────────────────────────────


@pytest.fixture
def parser_v2():
    return CodeParserV2()


class TestCodeParserV2:
    """CodeParserV2 能力测试"""

    @pytest.mark.asyncio
    async def test_basic_parse(self, parser_v2):
        """解析基本 Python 代码"""
        code = '''
"""Module docstring"""
import os
from pathlib import Path

MAX_SIZE = 100

class MyClass:
    """A test class"""
    class_var: int = 0

    def method(self, x: int = 5) -> str:
        """A method"""
        return str(x)

def hello(name: str) -> str:
    """Say hello"""
    return f"Hello, {name}"

async def async_fn():
    pass
'''
        result = await parser_v2.execute(code=code)
        assert "error" not in result
        assert result["docstring"] == "Module docstring"
        assert len(result["functions"]) == 2  # hello, async_fn
        assert len(result["classes"]) == 1
        assert result["classes"][0]["name"] == "MyClass"
        assert len(result["imports"]) == 2
        assert len(result["top_level_assignments"]) >= 1

    @pytest.mark.asyncio
    async def test_function_details(self, parser_v2):
        """函数的详细信息提取"""
        code = '''
def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone"""
    return f"{greeting}, {name}"
'''
        result = await parser_v2.execute(code=code)
        func = result["functions"][0]
        assert func["name"] == "greet"
        assert func["return_annotation"] == "str"
        assert func["docstring"] == "Greet someone"
        assert func["is_async"] is False
        # 检查参数
        args = func["args"]
        assert len(args) == 2
        assert args[0]["name"] == "name"
        assert args[0]["annotation"] == "str"
        assert args[1]["name"] == "greeting"
        assert args[1]["annotation"] == "str"
        assert args[1]["default"] == "'Hello'"

    @pytest.mark.asyncio
    async def test_async_function(self, parser_v2):
        """异步函数识别"""
        result = await parser_v2.execute(code="async def foo(x, y): pass")
        func = result["functions"][0]
        assert func["is_async"] is True
        assert len(func["args"]) == 2

    @pytest.mark.asyncio
    async def test_nested_functions(self, parser_v2):
        """嵌套函数提取"""
        code = '''
def outer():
    def inner():
        pass
    return inner
'''
        result = await parser_v2.execute(code=code, include_nested=True)
        outer = result["functions"][0]
        assert outer["name"] == "outer"
        assert "nested_functions" in outer
        assert outer["nested_functions"][0]["name"] == "inner"

    @pytest.mark.asyncio
    async def test_nested_disabled(self, parser_v2):
        """禁用嵌套提取"""
        code = '''
def outer():
    def inner():
        pass
'''
        result = await parser_v2.execute(code=code, include_nested=False)
        outer = result["functions"][0]
        assert "nested_functions" not in outer

    @pytest.mark.asyncio
    async def test_class_details(self, parser_v2):
        """类详细信息提取"""
        code = '''
class MyClass(Base, Mixin):
    """Class docstring"""
    x: int = 0
    y = "hello"

    def method_a(self):
        pass

    async def method_b(self):
        pass
'''
        result = await parser_v2.execute(code=code)
        cls = result["classes"][0]
        assert cls["name"] == "MyClass"
        assert "Base" in cls["bases"]
        assert "Mixin" in cls["bases"]
        assert cls["docstring"] == "Class docstring"
        assert len(cls["class_variables"]) == 2
        assert len(cls["methods"]) == 2

    @pytest.mark.asyncio
    async def test_decorator_extraction(self, parser_v2):
        """装饰器提取"""
        code = '''
@staticmethod
def foo():
    pass

@property
def bar(self):
    pass
'''
        result = await parser_v2.execute(code=code)
        assert "staticmethod" in result["functions"][0]["decorators"]
        assert "property" in result["functions"][1]["decorators"]

    @pytest.mark.asyncio
    async def test_import_types(self, parser_v2):
        """不同类型的导入"""
        code = '''
import os
import sys as system
from pathlib import Path
from . import utils
from ..core import base
'''
        result = await parser_v2.execute(code=code)
        imports = result["imports"]
        assert len(imports) == 5
        # import os
        assert imports[0]["type"] == "import"
        assert imports[0]["module"] == "os"
        # import sys as system
        assert imports[1]["type"] == "import"
        assert imports[1]["alias"] == "system"
        # from pathlib import Path
        assert imports[2]["type"] == "from_import"
        assert imports[2]["module"] == "pathlib"
        # 相对导入
        assert imports[3]["level"] == 1
        assert imports[4]["level"] == 2

    @pytest.mark.asyncio
    async def test_syntax_error(self, parser_v2):
        """语法错误处理"""
        result = await parser_v2.execute(code="def foo(:\n  pass")
        assert "error" in result
        assert "SyntaxError" in result["error"]
        assert result["functions"] == []

    @pytest.mark.asyncio
    async def test_metrics(self, parser_v2):
        """代码指标计算"""
        code = '''# Comment line
import os

def foo():
    pass

class Bar:
    def method(self):
        pass
'''
        result = await parser_v2.execute(code=code)
        m = result["metrics"]
        assert m["total_lines"] > 0
        assert m["comment_lines"] >= 1
        assert m["blank_lines"] >= 1
        assert m["function_count"] == 2  # foo + Bar.method
        assert m["class_count"] == 1

    @pytest.mark.asyncio
    async def test_validate_input(self, parser_v2):
        """输入验证"""
        assert parser_v2.validate_input(code="x = 1") is True
        assert parser_v2.validate_input() is False

    @pytest.mark.asyncio
    async def test_schema(self, parser_v2):
        """Schema 格式"""
        schema = parser_v2.get_schema()
        assert schema.name == "code_parser"
        assert "code" in schema.parameters["properties"]
        assert "code" in schema.parameters["required"]

    @pytest.mark.asyncio
    async def test_constants_and_annotations(self, parser_v2):
        """常量和带注解的赋值"""
        code = '''
MAX_SIZE = 100
name: str = "hello"
count: int = 0
'''
        result = await parser_v2.execute(code=code)
        assigns = result["top_level_assignments"]
        assert any(a["name"] == "MAX_SIZE" and a["is_constant"] for a in assigns)
        annotated = [a for a in assigns if a.get("annotation")]
        assert len(annotated) == 2


# ─── StaticAnalyzerV2 ──────────────────────────────────────


@pytest.fixture
def analyzer_v2():
    return StaticAnalyzerV2()


class TestStaticAnalyzerV2:
    """StaticAnalyzerV2 能力测试"""

    @pytest.mark.asyncio
    async def test_line_length(self, analyzer_v2):
        """检测过长行"""
        long_line = "x = " + "a" * 200
        result = await analyzer_v2.execute(code=long_line, max_line_length=80)
        issues = result["issues"]
        assert any(i["type"] == "line_too_long" for i in issues)

    @pytest.mark.asyncio
    async def test_function_length(self, analyzer_v2):
        """检测过长函数"""
        lines = ["def long_func():"]
        for i in range(59):
            lines.append(f"    x_{i} = {i}")
        code = "\n".join(lines)
        result = await analyzer_v2.execute(code=code, max_function_length=30)
        issues = result["issues"]
        assert any(i["type"] == "function_too_long" for i in issues)

    @pytest.mark.asyncio
    async def test_unused_import(self, analyzer_v2):
        """检测未使用的导入"""
        code = "import os\nimport sys\nprint(sys.argv)"
        result = await analyzer_v2.execute(code=code)
        issues = result["issues"]
        unused = [i for i in issues if i["type"] == "unused_import"]
        assert len(unused) >= 1
        assert any("os" in i["message"] for i in unused)

    @pytest.mark.asyncio
    async def test_naming_convention_function(self, analyzer_v2):
        """函数命名规范检查"""
        code = "def BadName():\n    pass"
        result = await analyzer_v2.execute(
            code=code, checks=["naming_convention"]
        )
        issues = result["issues"]
        assert any(
            i["type"] == "naming_convention" and "BadName" in i["message"]
            for i in issues
        )

    @pytest.mark.asyncio
    async def test_naming_convention_class(self, analyzer_v2):
        """类命名规范检查"""
        code = "class bad_class:\n    pass"
        result = await analyzer_v2.execute(
            code=code, checks=["naming_convention"]
        )
        issues = result["issues"]
        assert any(
            i["type"] == "naming_convention" and "bad_class" in i["message"]
            for i in issues
        )

    @pytest.mark.asyncio
    async def test_naming_convention_ok(self, analyzer_v2):
        """正确命名不应触发警告"""
        code = "class MyClass:\n    pass\n\ndef my_func():\n    pass"
        result = await analyzer_v2.execute(
            code=code, checks=["naming_convention"]
        )
        issues = result["issues"]
        assert not any(i["type"] == "naming_convention" for i in issues)

    @pytest.mark.asyncio
    async def test_complexity(self, analyzer_v2):
        """圈复杂度检测"""
        # 生成复杂函数
        code = '''
def complex_func(x):
    if x > 0:
        if x > 10:
            for i in range(x):
                if i % 2 == 0:
                    while i > 0:
                        if i == 5:
                            try:
                                pass
                            except ValueError:
                                pass
                            except TypeError:
                                pass
                        i -= 1
    return x
'''
        result = await analyzer_v2.execute(code=code, max_complexity=3)
        issues = result["issues"]
        complex_issues = [i for i in issues if i["type"] == "high_complexity"]
        assert len(complex_issues) >= 1
        assert complex_issues[0]["complexity"] > 3

    @pytest.mark.asyncio
    async def test_missing_docstring(self, analyzer_v2):
        """缺失文档字符串检测"""
        code = '''
def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    pass

class _PrivateClass:
    pass
'''
        result = await analyzer_v2.execute(
            code=code, checks=["missing_docstring"]
        )
        issues = result["issues"]
        msgs = [i["message"] for i in issues if i["type"] == "missing_docstring"]
        # 只检查公开的
        assert any("public_func" in m for m in msgs)
        assert any("PublicClass" in m for m in msgs)
        assert not any("_private" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_mutable_default(self, analyzer_v2):
        """可变默认参数检测"""
        code = '''
def foo(x=[]):
    pass

def bar(x={}):
    pass

def ok(x=None):
    pass
'''
        result = await analyzer_v2.execute(
            code=code, checks=["mutable_default"]
        )
        issues = result["issues"]
        mutable = [i for i in issues if i["type"] == "mutable_default"]
        assert len(mutable) == 2

    @pytest.mark.asyncio
    async def test_selective_checks(self, analyzer_v2):
        """选择性检查"""
        code = "import os\n" + "a" * 200 + "\ndef BadName():\n    pass"
        result = await analyzer_v2.execute(
            code=code, checks=["unused_import"]
        )
        issues = result["issues"]
        # 只执行了 unused_import，不应有 line_too_long 或 naming
        assert all(i["type"] == "unused_import" for i in issues)

    @pytest.mark.asyncio
    async def test_clean_code(self, analyzer_v2):
        """干净的代码没有问题"""
        code = '''
"""Module doc"""
import os


def get_cwd():
    """Get current working directory."""
    return os.getcwd()
'''
        result = await analyzer_v2.execute(code=code)
        assert result["summary"]["total"] == 0

    @pytest.mark.asyncio
    async def test_syntax_error(self, analyzer_v2):
        """语法错误处理"""
        result = await analyzer_v2.execute(code="def foo(:\n  pass")
        issues = result["issues"]
        assert any(i["type"] == "syntax_error" for i in issues)

    @pytest.mark.asyncio
    async def test_summary_structure(self, analyzer_v2):
        """摘要结构"""
        code = "import os\nimport sys\n" + "a" * 200
        result = await analyzer_v2.execute(code=code, max_line_length=80)
        summary = result["summary"]
        assert "total" in summary
        assert "by_type" in summary
        assert summary["total"] > 0

    @pytest.mark.asyncio
    async def test_schema(self, analyzer_v2):
        """Schema 格式"""
        schema = analyzer_v2.get_schema()
        assert schema.name == "static_analyzer"
        assert "code" in schema.parameters["properties"]

    @pytest.mark.asyncio
    async def test_validate_input(self, analyzer_v2):
        """输入验证"""
        assert analyzer_v2.validate_input(code="x = 1") is True
        assert analyzer_v2.validate_input() is False

    @pytest.mark.asyncio
    async def test_dunder_methods_ok(self, analyzer_v2):
        """dunder 方法不应触发命名警告"""
        code = '''
class Foo:
    def __init__(self):
        pass

    def __repr__(self):
        return "Foo"
'''
        result = await analyzer_v2.execute(
            code=code, checks=["naming_convention"]
        )
        issues = result["issues"]
        assert not any(
            i["type"] == "naming_convention" and "__" in i["message"]
            for i in issues
        )


# ─── TestRunnerCapability ──────────────────────────────────


@pytest.fixture
def test_runner():
    return TestRunnerCapability()


class TestTestRunnerCapability:
    """TestRunnerCapability 能力测试"""

    @pytest.mark.asyncio
    async def test_basic_test_extraction(self, test_runner):
        """提取基本测试函数"""
        code = '''
def test_add():
    assert 1 + 1 == 2

def test_sub():
    assert 3 - 1 == 2

def helper():
    pass
'''
        result = await test_runner.execute(code=code)
        assert len(result["test_cases"]) == 2
        assert result["summary"]["total_tests"] == 2
        names = [tc["name"] for tc in result["test_cases"]]
        assert "test_add" in names
        assert "test_sub" in names

    @pytest.mark.asyncio
    async def test_test_class_extraction(self, test_runner):
        """提取测试类"""
        code = '''
class TestCalculator:
    """Calculator tests"""
    def test_add(self):
        assert 1 + 1 == 2

    def test_sub(self):
        assert 3 - 1 == 2

    def helper(self):
        pass
'''
        result = await test_runner.execute(code=code)
        assert len(result["test_classes"]) == 1
        cls = result["test_classes"][0]
        assert cls["name"] == "TestCalculator"
        assert cls["test_count"] == 2
        assert cls["docstring"] == "Calculator tests"

    @pytest.mark.asyncio
    async def test_assertion_counting(self, test_runner):
        """断言计数"""
        code = '''
def test_multi_assert():
    assert True
    assert 1 == 1
    assert "hello" in "hello world"
'''
        result = await test_runner.execute(code=code)
        tc = result["test_cases"][0]
        assert tc["assertions"]["total"] == 3

    @pytest.mark.asyncio
    async def test_unittest_assertions(self, test_runner):
        """unittest 风格断言"""
        code = '''
import unittest

class TestStuff(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(1, 1)
        self.assertTrue(True)
        self.assertIn("a", "abc")
'''
        result = await test_runner.execute(code=code)
        cls = result["test_classes"][0]
        method = cls["test_methods"][0]
        assert method["assertions"]["total"] == 3
        assert "assertEqual" in method["assertions"]["by_type"]

    @pytest.mark.asyncio
    async def test_fixture_detection(self, test_runner):
        """pytest fixture 检测"""
        code = '''
import pytest

@pytest.fixture
def my_fixture():
    """A fixture"""
    return 42

@pytest.fixture(scope="session")
def session_fixture():
    return "db"

def test_use_fixture(my_fixture):
    assert my_fixture == 42
'''
        result = await test_runner.execute(code=code)
        assert len(result["fixtures"]) == 2
        f1 = result["fixtures"][0]
        assert f1["name"] == "my_fixture"
        assert f1["scope"] == "function"
        f2 = result["fixtures"][1]
        assert f2["name"] == "session_fixture"
        assert f2["scope"] == "session"

    @pytest.mark.asyncio
    async def test_fixture_args(self, test_runner):
        """测试函数的 fixture 参数"""
        code = '''
def test_with_fixtures(db, client, tmp_path):
    assert db is not None
'''
        result = await test_runner.execute(code=code)
        tc = result["test_cases"][0]
        assert "db" in tc["fixture_args"]
        assert "client" in tc["fixture_args"]
        assert "tmp_path" in tc["fixture_args"]

    @pytest.mark.asyncio
    async def test_markers_detection(self, test_runner):
        """pytest markers 检测"""
        code = '''
import pytest

@pytest.mark.asyncio
async def test_async():
    pass

@pytest.mark.slow
def test_slow():
    pass

@pytest.mark.skipif(True, reason="skip")
def test_skip():
    pass
'''
        result = await test_runner.execute(code=code)
        markers_map = {tc["name"]: tc["markers"] for tc in result["test_cases"]}
        assert "asyncio" in markers_map["test_async"]
        assert "slow" in markers_map["test_slow"]
        assert "skipif" in markers_map["test_skip"]

    @pytest.mark.asyncio
    async def test_parametrize_detection(self, test_runner):
        """parametrize 检测"""
        code = '''
import pytest

@pytest.mark.parametrize("x,y", [(1, 2), (3, 4), (5, 6)])
def test_add(x, y):
    assert x + y > 0
'''
        result = await test_runner.execute(code=code)
        tc = result["test_cases"][0]
        assert tc["parametrize"] is not None
        assert tc["parametrize"]["case_count"] == 3
        assert tc["parametrize"]["param_names"] == ["x", "y"]

    @pytest.mark.asyncio
    async def test_setup_teardown(self, test_runner):
        """setup/teardown 检测"""
        code = '''
class TestWithSetup:
    def setup_method(self):
        pass

    def teardown_method(self):
        pass

    def test_something(self):
        assert True
'''
        result = await test_runner.execute(code=code)
        cls = result["test_classes"][0]
        assert "setup_method" in cls["setup_teardown"]
        assert "teardown_method" in cls["setup_teardown"]

    @pytest.mark.asyncio
    async def test_syntax_error(self, test_runner):
        """语法错误处理"""
        result = await test_runner.execute(code="def test_(:\n  pass")
        assert "error" in result
        assert "SyntaxError" in result["error"]

    @pytest.mark.asyncio
    async def test_schema(self, test_runner):
        """Schema 格式"""
        schema = test_runner.get_schema()
        assert schema.name == "test_runner"
        assert "code" in schema.parameters["properties"]
        assert "code" in schema.parameters["required"]

    @pytest.mark.asyncio
    async def test_validate_input(self, test_runner):
        """输入验证"""
        assert test_runner.validate_input(code="x = 1") is True
        assert test_runner.validate_input() is False

    @pytest.mark.asyncio
    async def test_summary_structure(self, test_runner):
        """摘要结构"""
        code = '''
import pytest

@pytest.fixture
def db():
    return None

class TestA:
    def test_1(self):
        assert True

    def test_2(self):
        assert True

def test_standalone():
    assert 1 == 1
'''
        result = await test_runner.execute(code=code, filename="test_example.py")
        s = result["summary"]
        assert s["filename"] == "test_example.py"
        assert s["total_tests"] == 3  # 2 in class + 1 standalone
        assert s["test_functions"] == 1
        assert s["test_classes"] == 1
        assert s["fixtures"] == 1
        assert s["total_assertions"] >= 3

    @pytest.mark.asyncio
    async def test_async_test(self, test_runner):
        """异步测试函数"""
        code = '''
async def test_async_func():
    assert True
'''
        result = await test_runner.execute(code=code)
        assert result["test_cases"][0]["is_async"] is True

    @pytest.mark.asyncio
    async def test_empty_file(self, test_runner):
        """空文件"""
        result = await test_runner.execute(code="# No tests here\n")
        assert result["summary"]["total_tests"] == 0
        assert result["test_cases"] == []
        assert result["test_classes"] == []


# ─── 新版能力 Registry 集成 ───────────────────────────────


@pytest.mark.asyncio
async def test_registry_v2_all_capabilities():
    """三个新版能力都能注册到 registry 并执行"""
    registry = CapabilityRegistry()
    registry.register_native(CodeParserV2())
    registry.register_native(StaticAnalyzerV2())
    registry.register_native(TestRunnerCapability())

    assert len(registry) == 3
    assert "code_parser" in registry
    assert "static_analyzer" in registry
    assert "test_runner" in registry

    # 执行 code_parser
    r1 = await registry.execute("code_parser", code="x = 1")
    assert "functions" in r1

    # 执行 static_analyzer
    r2 = await registry.execute("static_analyzer", code="import os\nprint('hi')")
    assert "issues" in r2

    # 执行 test_runner
    r3 = await registry.execute("test_runner", code="def test_ok(): assert True")
    assert "test_cases" in r3
    assert r3["summary"]["total_tests"] == 1


@pytest.mark.asyncio
async def test_registry_v2_validate_fails():
    """缺少必选参数时注册表拒绝执行"""
    registry = CapabilityRegistry()
    registry.register_native(TestRunnerCapability())
    with pytest.raises(ValueError, match="Invalid input"):
        await registry.execute("test_runner")  # 缺 code

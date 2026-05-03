"""Safe calculator capability for deterministic arithmetic."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable

from core.capability.base import CapabilityBase, CapabilitySchema
from core.prompts import get_tool_description


class CalculatorCapability(CapabilityBase):
    """Evaluate arithmetic expressions with a restricted AST."""

    _BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    _FUNCTIONS: dict[str, Callable[..., Any]] = {
        "abs": abs,
        "ceil": math.ceil,
        "floor": math.floor,
        "max": max,
        "min": min,
        "pow": pow,
        "round": round,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
    }
    _CONSTANTS = {"pi": math.pi, "e": math.e}

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return get_tool_description(self.name)

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "要计算的数学表达式，例如: (12 + 8) * 3 / 2",
                    },
                    "precision": {
                        "type": "integer",
                        "description": "浮点结果保留小数位，默认 10",
                        "default": 10,
                    },
                },
                "required": ["expression"],
            },
            returns="计算结果",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=500,
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        expression = str(kwargs.get("expression", "")).strip()
        precision = int(kwargs.get("precision", 10) or 10)
        if not expression:
            return {"error": "expression is required"}

        try:
            tree = ast.parse(expression, mode="eval")
            result = self._eval_node(tree.body)
            if isinstance(result, float):
                result = round(result, max(0, min(precision, 15)))
            return {"expression": expression, "result": result}
        except ZeroDivisionError:
            return {"error": "division by zero"}
        except Exception as exc:
            return {"error": f"invalid expression: {str(exc)}"}

    def _eval_node(self, node: ast.AST) -> Any:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return node.value
        if isinstance(node, ast.Name) and node.id in self._CONSTANTS:
            return self._CONSTANTS[node.id]
        if isinstance(node, ast.BinOp):
            op = self._BIN_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"unsupported operator: {type(node.op).__name__}")
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent is too large")
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            op = self._UNARY_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
            return op(self._eval_node(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func = self._FUNCTIONS.get(node.func.id)
            if not func:
                raise ValueError(f"unsupported function: {node.func.id}")
            args = [self._eval_node(arg) for arg in node.args]
            return func(*args)
        raise ValueError(f"unsupported expression: {type(node).__name__}")

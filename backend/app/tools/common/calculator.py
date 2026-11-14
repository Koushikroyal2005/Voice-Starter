"""Bounded arithmetic AST interpreter: no eval, calls, names or code execution."""

import ast
import math
import operator

from pydantic import Field

from app.tools.base import ExecutionContext, Schema, ToolDefinition, ToolFailure


class CalculateInput(Schema):
    expression: str = Field(
        min_length=1,
        max_length=200,
        description="Arithmetic using numbers, parentheses, + - * / // % ** only.",
    )


class CalculateOutput(Schema):
    value: float


OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def calculate(expression: str) -> float:
    def visit(node, depth=0):
        if depth > 16:
            raise ValueError("Expression is too deeply nested")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
            value = visit(node.operand, depth + 1)
            result = value if isinstance(node.op, ast.UAdd) else -value
        elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("Exponent exceeds limit")
            result = OPERATORS[type(node.op)](left, right)
        else:
            raise ValueError("Unsupported arithmetic")
        if (
            type(result) not in (int, float)
            or not math.isfinite(result)
            or abs(result) > 1e12
        ):
            raise ValueError("Result exceeds numeric limits")
        return result

    try:
        if not 0 < len(expression) <= 200:
            raise ValueError("Expression length exceeds limit")
        tree = ast.parse(expression.strip(), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 64:
            raise ValueError("Expression exceeds node limit")
        return float(visit(tree.body))
    except (ValueError, SyntaxError, ArithmeticError, RecursionError):
        raise ToolFailure(
            "invalid_expression",
            "Use bounded arithmetic with numbers and arithmetic operators only. "
            "Division by zero and non-finite results are not allowed.",
        ) from None


async def calculate_expression(
    args: CalculateInput, _context: ExecutionContext
) -> CalculateOutput:
    return CalculateOutput(value=calculate(args.expression))


CALCULATOR_TOOL = ToolDefinition(
    name="calculate_expression",
    title="Calculate expression",
    description="Safely evaluate bounded arithmetic, not code. "
    "Not a financial precision calculator.",
    input_schema=CalculateInput,
    output_schema=CalculateOutput,
    handler=calculate_expression,
    public_result=lambda result: str(result.value),
)

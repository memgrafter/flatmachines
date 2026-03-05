"""
Simple expression engine for flatmachines.

Supports:
- Comparisons: ==, !=, <, <=, >, >=
- Boolean operators: and, or, not
- Field access: context.field, input.field, output.field
- Literals: strings, numbers, booleans, null

Examples:
    context.score >= 8
    context.current == context.target
    context.score >= 8 and context.round < 4
    not context.failed
"""

import ast
import operator
import re
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Tuple


class SimpleExpressionEngine:
    """
    Simple expression parser and evaluator.
    
    Uses Python's ast module for safe parsing, then evaluates
    with a restricted set of operations.
    """

    # Supported comparison operators
    COMPARISON_OPS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
    }

    # Supported boolean operators
    BOOL_OPS = {
        ast.And: lambda values: all(values),
        ast.Or: lambda values: any(values),
    }

    def __init__(self):
        pass

    def evaluate(self, expression: str, variables: Dict[str, Any]) -> Any:
        """
        Evaluate an expression with the given variables.

        Args:
            expression: The expression string to evaluate
            variables: Dictionary of variable names to values

        Returns:
            The result of evaluating the expression

        Raises:
            ValueError: If expression syntax is invalid
            KeyError: If referenced variable doesn't exist
        """
        if not expression or not expression.strip():
            return True  # Empty expression is always true (default transition)

        try:
            tree = ast.parse(expression, mode='eval')
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {expression}") from e

        return self._eval_node(tree.body, variables)

    def _eval_node(self, node: ast.AST, variables: Dict[str, Any]) -> Any:
        """Recursively evaluate an AST node."""

        # Literals
        if isinstance(node, ast.Constant):
            return node.value

        # Name (variable reference like 'context', 'input', 'output')
        if isinstance(node, ast.Name):
            name = node.id
            # Handle boolean literals
            if name == 'true' or name == 'True':
                return True
            if name == 'false' or name == 'False':
                return False
            if name == 'null' or name == 'None':
                return None
            if name not in variables:
                raise KeyError(f"Unknown variable: {name}")
            return variables[name]

        # Attribute access (e.g., context.score, context.nested.field)
        if isinstance(node, ast.Attribute):
            value = self._eval_node(node.value, variables)
            attr = node.attr
            if isinstance(value, Mapping):
                if attr not in value:
                    return None  # Missing fields return None
                return value[attr]
            return getattr(value, attr, None)

        # Comparison (e.g., context.score >= 8)
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, variables)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, variables)
                op_func = self.COMPARISON_OPS.get(type(op))
                if op_func is None:
                    raise ValueError(f"Unsupported comparison operator: {type(op).__name__}")
                if not op_func(left, right):
                    return False
                left = right
            return True

        # Boolean operators (and, or)
        if isinstance(node, ast.BoolOp):
            op_func = self.BOOL_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"Unsupported boolean operator: {type(node.op).__name__}")
            # Short-circuit evaluation
            if isinstance(node.op, ast.And):
                for value_node in node.values:
                    if not self._eval_node(value_node, variables):
                        return False
                return True
            else:  # Or
                for value_node in node.values:
                    if self._eval_node(value_node, variables):
                        return True
                return False

        # Unary operators (not)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, variables)
            if isinstance(node.op, ast.Not):
                return not operand
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

        # Binary operators (for arithmetic in expressions like context.round + 1)
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, variables)
            right = self._eval_node(node.right, variables)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")

        # Subscript (e.g., context["key"])
        if isinstance(node, ast.Subscript):
            value = self._eval_node(node.value, variables)
            index = self._eval_node(node.slice, variables)
            return value[index]

        raise ValueError(f"Unsupported expression type: {type(node).__name__}")


__all__ = ["SimpleExpressionEngine"]

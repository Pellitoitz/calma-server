"""Model parameters and safe expressions ('$circuits_per_rack', '1 - $branch2_share', '$n * 2').

Only numbers, parameter references, + - * / and parentheses are allowed (no names, calls or
attributes): parsed with `ast` and evaluated by a whitelist, never with eval().
"""

from __future__ import annotations

import ast
import copy
import operator
import re
from typing import Any

from .isms import ISMSModel

_REF = re.compile(r"\$([a-z][a-z0-9_]*)")
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class ExpressionError(ValueError):
    pass


class MissingParameter(ExpressionError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"El parámetro '{name}' no tiene valor (REQUIRED).")


def is_expression(v: Any) -> bool:
    return isinstance(v, str) and "$" in v


def references(expr: str) -> list[str]:
    return _REF.findall(expr)


def evaluate(expr: str, values: dict[str, float | None]) -> float:
    for name in references(expr):
        if name not in values:
            raise ExpressionError(f"Parámetro desconocido '${name}' en '{expr}'.")
        if values[name] is None:
            raise MissingParameter(name)
    src = _REF.sub(lambda m: f"__p_{m.group(1)}", expr)
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        raise ExpressionError(f"Expresión inválida '{expr}'.") from None

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.Name) and n.id.startswith("__p_"):
            return float(values[n.id[4:]])  # type: ignore[arg-type]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise ExpressionError(f"Elemento no permitido en la expresión '{expr}'.")

    return ev(tree)


def _num(x: float) -> float | int:
    return int(x) if float(x).is_integer() else x


def resolve(model: ISMSModel) -> tuple[ISMSModel | None, list[tuple[str, str, bool]]]:
    """Return (model with every '$expr' replaced by its value, problems[(path, message, is_missing)])."""
    values = {p.id: p.value for p in model.parameters}
    problems: list[tuple[str, str, bool]] = []
    data = copy.deepcopy(model.model_dump(mode="json"))

    def walk(obj: Any, path: str) -> Any:
        if isinstance(obj, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v, f"{path}.{i}") for i, v in enumerate(obj)]
        if is_expression(obj):
            try:
                return _num(evaluate(obj, values))
            except MissingParameter as e:
                problems.append((path, f"{e} Se usa en {path}.", True))
            except ExpressionError as e:
                problems.append((path, str(e), False))
            return None
        return obj

    for section in ("resources", "nodes", "edges"):
        data[section] = walk(data[section], section)
    if problems:
        return None, problems
    try:
        return ISMSModel.model_validate(data), []
    except Exception as e:  # noqa: BLE001
        return None, [("model", f"Valor resuelto inválido: {e}", False)]

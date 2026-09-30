"""Conservative observations of documented library behavior changes.

These match observed values and executed source, never dataset labels or case names.
Installed/declaration versions and upstream sources are checked by the rule base.
"""

import ast
from collections import Counter
from pathlib import Path
import re


SCALAR_REPR = re.compile(
    r"\b(?:np|numpy)\.(?:float(?:16|32|64)|u?int(?:8|16|32|64))\("
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)\)", re.I,
)


def scalar_representation_only(message: str) -> bool:
    """Both assertion operands must be strings differing only by scalar wrappers."""
    first = message.splitlines()[0] if message else ""
    if len(first) > 8000:
        return False
    try:
        tree = ast.parse(first)
    except (SyntaxError, ValueError, RecursionError):
        return False
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
        return False
    comparison = tree.body[0].test
    if not isinstance(comparison, ast.Compare) or len(comparison.ops) != 1:
        return False
    if not isinstance(comparison.ops[0], ast.Eq):
        return False
    left, right = comparison.left, comparison.comparators[0]
    if not all(isinstance(n, ast.Constant) and isinstance(n.value, str) for n in (left, right)):
        return False
    if left.value == right.value:
        return False
    # Require a legacy string on one side, not two differently typed NumPy values.
    if bool(SCALAR_REPR.search(left.value)) == bool(SCALAR_REPR.search(right.value)):
        return False
    return SCALAR_REPR.sub(r"\g<value>", left.value) == SCALAR_REPR.sub(r"\g<value>", right.value)


def qualified(node: ast.AST, imports: dict) -> str:
    if isinstance(node, ast.Name):
        return imports.get(node.id, "")
    if isinstance(node, ast.Attribute):
        base = qualified(node.value, imports)
        return f"{base}.{node.attr}" if base else ""
    return ""


def promotion_in_json_call(lines: list[str], imports: dict) -> bool:
    """A JSON call contains a NumPy float scalar/Python float arithmetic expression.

    Direct serialization of np.float32 was already unsupported in NumPy 1.x. It
    must not be turned into an upgrade diagnosis merely because NumPy is installed.
    """
    def python_float(node):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            node = node.operand
        return isinstance(node, ast.Constant) and type(node.value) is float

    def numpy_float(node):
        return isinstance(node, ast.Call) and qualified(node.func, imports) in (
            "numpy.float16", "numpy.float32",
        )

    for line in lines[:80]:
        if len(line) > 2000:
            continue
        try:
            tree = ast.parse(line)
        except (SyntaxError, ValueError, RecursionError):
            continue
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or qualified(call.func, imports) not in (
                "json.dumps", "json.dump",
            ):
                continue
            # Only the serialized value, not an unrelated keyword or statement.
            if not call.args:
                continue
            for expression in ast.walk(call.args[0]):
                if isinstance(expression, ast.BinOp) and isinstance(
                    expression.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
                ) and (
                    numpy_float(expression.left) and python_float(expression.right)
                    or python_float(expression.left) and numpy_float(expression.right)
                ):
                    return True
    return False


def numpy_repr_functions(tree: ast.Module, module: str, imports: dict) -> list[str]:
    """Index simple functions returning a repr-formatted NumPy expression.

    Requiring the failing assertion to call one of these functions prevents an
    unrelated import plus a literal 'np.float64(...)' string from matching.
    """
    result = []
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assignments = {}
        for statement in function.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        assignments.setdefault(target.id, []).append(statement.value)
        shadowed = set(assignments) | {
            a.arg for a in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        }
        visible = {k: v for k, v in imports.items() if k not in shadowed}

        def from_numpy(node):
            if isinstance(node, ast.Name):
                values = assignments.get(node.id, [])
                node = values[0] if len(values) == 1 else node
            return isinstance(node, ast.Call) and qualified(node.func, visible).startswith("numpy.")

        for statement in function.body:
            if not isinstance(statement, ast.Return):
                continue
            if any(isinstance(n, ast.FormattedValue) and n.conversion == ord("r") and from_numpy(n.value)
                   for n in ast.walk(statement)):
                result.append(module + "." + function.name)
    return result


def calls_numpy_formatter(lines: list[str], imports: dict, functions: list[str]) -> bool:
    for line in lines[:80]:
        if len(line) > 2000:
            continue
        try:
            tree = ast.parse(line)
        except (SyntaxError, ValueError, RecursionError):
            continue
        if any(isinstance(n, ast.Call) and qualified(n.func, imports) in functions for n in ast.walk(tree)):
            return True
    return False


def index_behavior_context(root: Path, files: list[str], imports: dict, max_bytes: int, max_files: int) -> dict:
    """Conservatively detect custom/strict validation without importing project code.

    An incomplete index cannot establish default coercion. Old saved snapshots that
    lack this field also cannot establish it; they retain their previous diagnosis.
    """
    complete = len(files) < max_files
    customized = False
    formatters = []
    model_names, definitions = set(), Counter()
    custom_names = {
        "strict", "model_config", "coerce_numbers_to_str", "validation_alias", "validator", "root_validator",
        "field_validator", "model_validator", "BeforeValidator", "AfterValidator",
        "WrapValidator", "PlainValidator", "__get_pydantic_core_schema__",
    }
    for relative in files:
        path = root / relative
        try:
            if path.is_symlink() or path.stat().st_size > max_bytes:
                complete = False
                continue
            tree = ast.parse(path.read_text("utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError, RecursionError):
            complete = False
            continue
        module = relative.removeprefix("src/").removesuffix(".py").replace("/", ".")
        module = module.removesuffix(".__init__")
        formatters += numpy_repr_functions(tree, module, imports)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                definitions[node.name] += 1
                if node.name == "Config":
                    customized = True
                if len(node.bases) == 1 and qualified(node.bases[0], imports) == "pydantic.BaseModel":
                    model_names.add(node.name)
            if isinstance(node, ast.keyword) and node.arg in custom_names:
                customized = True
            if isinstance(node, ast.alias) and (
                node.name.split(".")[-1] in custom_names or node.name.split(".")[-1].startswith("Strict")
            ):
                customized = True
            if isinstance(node, ast.Dict) and any(
                isinstance(key, ast.Constant) and key.value in custom_names
                for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ):
                customized = True
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name.startswith("Strict") or name in custom_names:
                    customized = True
    return {
        "validation_settings": {"complete": complete, "customized": customized},
        "numpy_repr_functions": sorted(set(formatters)),
        "pydantic_default_models": sorted(n for n in model_names if definitions[n] == 1),
    }


def observed_changes(evidence: dict, project: dict) -> list[tuple[str, str]]:
    """Return (knowledge entry id, distribution) for narrowly observed symptoms."""
    imports = project.get("imported_names", {})
    providers = {name.split(".")[0] for name in imports.values()}
    providers -= set(project.get("own_names", []))
    providers -= {row["name"] for row in project.get("local_modules", [])}
    found = []
    if "numpy" in providers:
        if (
            evidence["exception"] == "AssertionError"
            and scalar_representation_only(evidence["message"])
            and calls_numpy_formatter(evidence["executed_lines"], imports, project.get("numpy_repr_functions", []))
        ):
            found.append(("numpy-scalar-repr", "numpy"))
        if (
            evidence["exception"] == "TypeError"
            and evidence["raised_in"] == "stdlib"
            and re.fullmatch(r"Object of type float(?:16|32) is not JSON serializable", evidence["message"])
            and promotion_in_json_call(evidence["executed_lines"], imports)
        ):
            found.append(("numpy-scalar-promotion", "numpy"))
    settings = project.get("validation_settings", {})
    model = re.match(r"1 validation error for ([A-Za-z_]\w*)\n", evidence["message"])
    if (
        evidence["exception"] == "ValidationError"
        and evidence["library"] == "pydantic"
        and evidence["exception_module"].split(".")[0] in ("pydantic", "pydantic_core")
        and "pydantic" in providers
        and settings.get("complete") and not settings.get("customized")
        and model and model[1] in project.get("pydantic_default_models", [])
        and re.search(r"\[type=string_type, input_value=.+, input_type=(?:int|float|Decimal)\]", evidence["message"])
    ):
        found.append(("pydantic-number-to-string", "pydantic"))
    return found

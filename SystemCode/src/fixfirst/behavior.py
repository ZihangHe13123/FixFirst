"""Conservative observations of documented library behavior changes.

These match observed values and executed source, never dataset labels or case names.
Installed/declaration versions and upstream sources are checked by the rule base.
"""

import ast
from collections import Counter
from itertools import zip_longest
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


def generator_consumption(tree: ast.AST) -> dict[int, bool | None]:
    """Record eager, unknown, or simple lazy uses of a named generator.

    This is a bounded static guard, not proof about consumers in other functions.
    Only direct aliases and bare returns are known lazy uses. Passing the value
    to an unrecognised callable or capturing it in a nested scope is unknown.
    Missing/oversized contexts are absent, not marked safe.
    """
    result = {}
    consumers = {"list", "tuple", "set", "dict", "next", "sum", "min", "max", "sorted", "any", "all", "deque"}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        pending, nodes = list(function.body), []
        while pending and len(nodes) <= 2000:
            node = pending.pop()
            nodes.append(node)
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                pending.extend(ast.iter_child_nodes(node))
        if pending or len(nodes) > 2000:
            continue
        parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
        nodes.sort(key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))
        for at, node in enumerate(nodes):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if (len(targets) != 1 or not isinstance(targets[0], ast.Name)
                    or not isinstance(node.value, ast.GeneratorExp)):
                continue
            aliases, consumed, unknown = {targets[0].id}, False, False
            creation_nodes = set(ast.walk(node))
            for later in nodes[at + 1:]:
                if later in creation_nodes:
                    continue
                assigned = later.targets if isinstance(later, ast.Assign) else [later.target] if isinstance(later, ast.AnnAssign) else []
                if (assigned and all(isinstance(t, ast.Name) for t in assigned)
                        and isinstance(later.value, ast.Name) and later.value.id in aliases):
                    aliases.update(t.id for t in assigned)
                if isinstance(later, ast.Call):
                    name = later.func.id if isinstance(later.func, ast.Name) else getattr(later.func, "attr", "")
                    consumes = name in consumers or name in {"__next__", "send"}
                    uses = any(isinstance(n, ast.Name) and n.id in aliases for n in ast.walk(later))
                    consumed |= consumes and uses
                elif isinstance(later, (ast.For, ast.AsyncFor)):
                    consumed |= any(isinstance(n, ast.Name) and n.id in aliases for n in ast.walk(later.iter))
                elif isinstance(later, (ast.ListComp, ast.SetComp, ast.DictComp, ast.YieldFrom, ast.Starred)):
                    consumed |= any(isinstance(n, ast.Name) and n.id in aliases for n in ast.walk(later))
                elif isinstance(later, ast.Name) and isinstance(later.ctx, ast.Load) and later.id in aliases:
                    parent = parents.get(later)
                    direct_return = isinstance(parent, ast.Return) and parent.value is later
                    direct_alias = (isinstance(parent, ast.Assign) and parent.value is later
                                    and all(isinstance(t, ast.Name) for t in parent.targets))
                    annotated_alias = (isinstance(parent, ast.AnnAssign) and parent.value is later
                                       and isinstance(parent.target, ast.Name))
                    unknown |= not (direct_return or direct_alias or annotated_alias)
            for scope in nodes:
                if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                    continue
                # A nested function may be declared before the assignment and
                # called afterwards. Do not mistake its captured value for an
                # unused generator. Parameter names shadow the outer aliases.
                pending = [scope]
                captured, count = [], 0
                while pending and count < 2000:
                    child = pending.pop()
                    captured.append(child)
                    pending.extend(ast.iter_child_nodes(child))
                    count += 1
                if pending:
                    unknown = True
                    continue
                arguments = getattr(scope, "args", None)
                bound = set()
                headers = list(getattr(scope, "decorator_list", []))
                if arguments:
                    bound = {a.arg for a in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}
                    bound.update(a.arg for a in (arguments.vararg, arguments.kwarg) if a is not None)
                    headers += list(arguments.defaults) + [d for d in arguments.kw_defaults if d is not None]
                unknown |= any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in aliases
                               for header in headers for n in ast.walk(header))
                unknown |= any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in aliases - bound
                               for n in captured)
            result[node.lineno] = True if consumed else None if unknown else False
    return result


def index_behavior_context(root: Path, files: list[str], imports: dict, max_bytes: int, max_files: int) -> dict:
    """Conservatively detect custom/strict validation without importing project code.

    An incomplete index cannot establish default coercion. Old saved snapshots that
    lack this field also cannot establish it; they retain their previous diagnosis.
    """
    complete = len(files) < max_files
    customized = False
    formatters = []
    model_names, definitions = set(), Counter()
    optional_models, generator_uses = {}, {}
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
        generator_uses.update({f"{relative}:{line}": value for line, value in generator_consumption(tree).items()})
        from .source_context import scope_bindings

        bindings = scope_bindings(tree.body, module, module.rpartition(".")[0])
        if "*" in bindings:
            bindings = {}
        formatters += numpy_repr_functions(tree, module, imports)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                definitions[node.name] += 1
                if node.name == "Config":
                    customized = True
                if len(node.bases) == 1 and qualified(node.bases[0], imports) == "pydantic.BaseModel":
                    model_names.add(node.name)
                if (node in tree.body and not node.decorator_list and len(node.bases) == 1
                        and qualified(node.bases[0], bindings) == "pydantic.BaseModel"):
                    fields = {}
                    for field in node.body:
                        if not isinstance(field, ast.AnnAssign) or not isinstance(field.target, ast.Name):
                            continue
                        annotation = field.annotation
                        nullable = (
                            isinstance(annotation, ast.Subscript)
                            and qualified(annotation.value, bindings) == "typing.Optional"
                        ) or (
                            isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr)
                            and any(isinstance(v, ast.Constant) and v.value is None
                                    for v in (annotation.left, annotation.right))
                        )
                        fields[field.target.id] = {"nullable": nullable,
                                                  "nullable_without_default": nullable and field.value is None,
                                                  "location": f"{relative}:{field.lineno}"}
                    optional_models[f"{module}.{node.name}"] = {"name": node.name, "fields": fields}
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
        "pydantic_optional_models": {k: v for k, v in optional_models.items() if definitions[v["name"]] == 1},
        "generator_consumption": generator_uses,
    }


def observed_changes(evidence: dict, project: dict) -> list[tuple[str, str]]:
    """Return (knowledge entry id, distribution) for narrowly observed symptoms."""
    imports = project.get("imported_names", {})
    providers = {name.split(".")[0] for name in imports.values()}
    providers -= set(project.get("own_names", []))
    providers -= {row["name"] for row in project.get("local_modules", [])}
    found = []
    if ("sqlalchemy" in providers and evidence["exception"] == "ModuleNotFoundError"
            and evidence["missing_module"] == "sqlalchemy.databases"
            and evidence["message"] == "No module named 'sqlalchemy.databases'"
            and evidence["raised_in"] == "project"):
        try:
            body = ast.parse(evidence.get("source_statement", "")).body
            statement = body[0] if len(body) == 1 else None
            if (isinstance(statement, ast.ImportFrom) and statement.level == 0
                    and statement.module == "sqlalchemy.databases"
                    and len(statement.names) == 1 and statement.names[0].name == "sqlite"):
                found.append(("sqlalchemy-sqlite-dialect-import", "sqlalchemy"))
        except (SyntaxError, ValueError, RecursionError):
            pass
    if (evidence["exception"] == "ResourceClosedError" and evidence["library"] == "sqlalchemy"
            and evidence["exception_module"] == "sqlalchemy.exc" and "sqlalchemy" in providers
            and evidence["message"] == "This result object does not return rows. It has been closed automatically."
            and project.get("generator_consumption", {}).get(evidence.get("source_location")) is False
            and "return self._iter_impl()" in evidence.get("executed_lines", [])):
        # 1.4 made iterator creation eager. Only a standalone lazy generator
        # construction fits that change; list/fetchall consumption already failed
        # on 1.3 and must not borrow this history.
        try:
            statement = ast.parse(evidence.get("source_statement", "")).body
            node = statement[0] if len(statement) == 1 else None
            if (isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return))
                    and isinstance(node.value, ast.GeneratorExp)
                    and len(node.value.generators) == 1
                    and isinstance(node.value.generators[0].iter, ast.Name)):
                found.append(("sqlalchemy-eager-result-iterator", "sqlalchemy"))
        except (SyntaxError, ValueError):
            pass
    # These are the statically resolved calls at the failure site, including C
    # APIs which cannot contribute their own Python traceback frame.
    location = evidence.get("source_location") or evidence.get("where", "")
    site_calls = set(project.get("source_context", {}).get("calls", {}).get(location, []))
    if ("xlrd" in providers and evidence["exception"] == "XLRDError"
            and evidence["exception_module"] == "xlrd.biffh" and evidence["library"] == "xlrd"
            and evidence["raised_in"] == "third_party"
            and evidence["message"] == "Excel xlsx file; not supported"
            and site_calls == {"xlrd.open_workbook"}
            and "xlrd.open_workbook" in evidence.get("library_calls", [])):
        found.append(("xlrd-xlsx-reading", "xlrd"))
    if (evidence["exception"] == "InvalidVersion" and evidence["library"] == "packaging"
            and "packaging.version.parse" in evidence.get("library_calls", [])
            and "packaging" in providers):
        found.append(("packaging-legacy-parse", "packaging"))
    if evidence.get("call_signature"):
        from .source_context import resolved_calls

        calls = resolved_calls(evidence, project, legacy=True)
        local = {row["name"] for row in project.get("local_modules", [])}
        if "yaml.load" in calls and "yaml" not in local and re.search(
            r"\bload\(\) missing 1 required positional argument: ['\"]Loader['\"]", evidence["message"],
        ):
            found.append(("yaml-required-loader", "pyyaml"))
        if "click.testing.CliRunner" in calls and "click" not in local and "mix_stderr" in evidence.get("kwargs", []):
            found.append(("click-runner-streams", "click"))
    if "numpy" in providers:
        if (evidence["exception"] == "ValueError" and site_calls == {"numpy.array"}
                and evidence["message"].startswith("Unable to avoid copy while creating an array as requested")):
            found.append(("numpy-copy-false", "numpy"))
        for call in evidence.get("call_arguments", []):
            if call.get("callee") not in ("numpy.linalg._linalg.solve", "numpy.linalg.linalg.solve"):
                continue
            a, b = call["shapes"]["a"], call["shapes"]["b"]
            broadcast = all(x == y or x == 1 or y == 1
                            for x, y in zip_longest(reversed(a[:-2]), reversed(b[:-1]), fillvalue=1))
            if (evidence["exception"] == "ValueError" and "mismatch in its core dimension" in evidence["message"]
                    and len(a) >= 3 and len(b) == len(a) - 1 and len(b) > 1
                    and a[-2] == a[-1] == b[-1] and broadcast):
                found.append(("numpy-solve-vector", "numpy"))
                break
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
    if (evidence["exception"] == "ValidationError" and evidence["library"] == "pydantic"
            and evidence["exception_module"].split(".")[0] in ("pydantic", "pydantic_core")
            and "pydantic" in providers and settings.get("complete") and not settings.get("customized")
            and model and len(site_calls) == 1):
        definition = project.get("pydantic_optional_models", {}).get(next(iter(site_calls)), {})
        if definition.get("name") == model[1]:
            fields = definition["fields"]
            for rejected in evidence.get("validation_errors", []):
                if not isinstance(rejected, dict):
                    continue
                missing, supplied = rejected.get("field", ""), set(rejected.get("input_keys", []))
                if (isinstance(rejected, dict) and rejected.get("type") == "missing"
                        and fields.get(missing, {}).get("nullable_without_default")
                        and supplied <= set(fields)
                        and not any(fields[key].get("nullable") is not False or missing.casefold() in key.casefold()
                                    for key in supplied)):
                    found.append(("pydantic-optional-required", "pydantic"))
                    break
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


def observed_input_errors(evidence: dict) -> list[tuple[str, str]]:
    """Known input-rejection contracts, requiring the actual raising library.

    A project's exception named ParserError/BadParameter is not sufficient, and
    a documented behavior change takes precedence in the rules.
    """
    if evidence["raised_in"] != "third_party":
        return []
    library, error, module = evidence["library"], evidence["exception"], evidence["exception_module"]
    message = evidence["message"]
    if library == "numpy":
        if error == "ValueError" and re.fullmatch(r"cannot reshape array of size \d+ into shape .+", message):
            return [("numpy-shape", "numpy")]
        if error == "AxisError" and module in ("numpy.exceptions", "numpy.core._exceptions", "numpy._core._exceptions"):
            return [("numpy-axis", "numpy")]
    if library == "yaml" and (module, error) in (("yaml.parser", "ParserError"), ("yaml.scanner", "ScannerError")):
        return [("yaml-syntax", "pyyaml")]
    if library == "click" and (module, error) == ("click.exceptions", "BadParameter"):
        return [("click-value", "click")]
    if library == "packaging" and (module, error) == ("packaging.version", "InvalidVersion"):
        return [("version-string", "packaging")]
    if (library == "sqlalchemy" and (module, error) == ("sqlalchemy.exc", "ResourceClosedError")
            and message == "This result object does not return rows. It has been closed automatically."):
        return [("sqlalchemy-no-rows", "sqlalchemy")]
    if (library == "pydantic" and error == "ValidationError"
            and module.split(".")[0] in ("pydantic", "pydantic_core")
            and evidence.get("validation_errors")):
        return [("pydantic-missing", "pydantic")]
    return []

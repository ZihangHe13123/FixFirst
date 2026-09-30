"""Bounded static call provenance for classifier observations.

Bindings are accepted only when a scope gives a name one unambiguous source.
Arguments, reassignment and conflicting imports make that name unknown. Nothing
is imported or executed, and no diagnostic rule or training label is consulted.
"""

import ast
from collections import defaultdict
from pathlib import Path

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .behavior import scalar_representation_only

MAX_SITES = 6000
FEATURE_NAMES = [
    "context_project_resolution", "context_external_api", "call_signature_mismatch",
    "callee_project", "callee_external", "assertion_text_difference",
    "assertion_numeric_difference", "assertion_scalar_representation",
    "relevant_lock_series_changed", "relevant_requirement_conflict",
    "library_exception_type",
    "source_context_available",
]


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute) and len(parts) < 32:
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else ""


def resolve(node, bindings):
    name = dotted(node)
    head, _, tail = name.partition(".")
    target = bindings.get(head)
    return target + ("." + tail if tail else "") if target else ""


def scope_bindings(statements, module, package, arguments=None):
    found = defaultdict(set)

    class Collector(ast.NodeVisitor):
        depth = 0

        def visit(self, node):
            if self.depth >= 64:
                found["*"].add("")  # truncated scope cannot establish a binding
                return
            self.depth += 1
            try:
                return super().visit(node)
            finally:
                self.depth -= 1

        def visit_Import(self, node):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                found[name].add(alias.name if alias.asname else name)

        def visit_ImportFrom(self, node):
            prefix = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                if node.level > len(parts):
                    for alias in node.names:
                        found[alias.asname or alias.name].add("")
                    return
                prefix = ".".join(parts[:len(parts) - node.level + 1] + ([prefix] if prefix else []))
            for alias in node.names:
                if alias.name == "*":
                    found["*"].add("")
                else:
                    found[alias.asname or alias.name].add(f"{prefix}.{alias.name}" if prefix else "")

        def visit_FunctionDef(self, node):
            found[node.name].add("" if node.decorator_list else f"{module}.{node.name}")

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                found[node.id].add("")

        def visit_ExceptHandler(self, node):
            if node.name:
                found[node.name].add("")
            self.generic_visit(node)

        def visit_Global(self, node):
            for name in node.names:
                found[name].add("")

        visit_Nonlocal = visit_Global

        def visit_Lambda(self, node):
            pass

    collector = Collector()
    for node in statements:
        collector.visit(node)
    if arguments:
        args = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        args += [arg for arg in (arguments.vararg, arguments.kwarg) if arg]
        for arg in args:
            found[arg.arg].add("")
    return {name: next(iter(values)) if len(values) == 1 else "" for name, values in found.items()}


def index_source_context(root: Path, files: list[str], max_bytes: int):
    calls, bases = {}, defaultdict(list)
    root = root.resolve()
    for relative in files:
        if len(calls) >= MAX_SITES:
            break
        path = root / relative
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > max_bytes:
                continue
            tree = ast.parse(path.read_text("utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError, RecursionError):
            continue
        module = relative.removeprefix("src/").removesuffix(".py").replace("/", ".")
        package = module.removesuffix(".__init__") if module.endswith(".__init__") else module.rpartition(".")[0]
        module = module.removesuffix(".__init__")
        global_names = scope_bindings(tree.body, module, package)
        if "*" in global_names:
            global_names = {name: "" for name in global_names}

        def visit(node, bindings, function_parent=None, depth=0):
            if len(calls) >= MAX_SITES or depth >= 64:
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # A method does not resolve bare names in its class namespace.
                parent = bindings if function_parent is None else function_parent
                own = scope_bindings(node.body, module, package, node.args)
                local = {**parent, **own}
                if "*" in own:
                    local = {name: "" for name in local}
                for item in node.body:
                    visit(item, local, depth=depth + 1)
                return
            if isinstance(node, ast.ClassDef):
                bases[node.name].append([resolve(base, bindings) for base in node.bases])
                local = {**bindings, **scope_bindings(node.body, module, package)}
                if "*" in local:
                    local = {name: "" for name in local}
                for item in node.body:
                    visit(item, local, function_parent=bindings, depth=depth + 1)
                return
            if isinstance(node, ast.Lambda):
                return
            if isinstance(node, ast.Call):
                target = resolve(node.func, bindings)
                if target:
                    start, end = node.lineno, min(node.end_lineno or node.lineno, node.lineno + 20)
                    for line in range(start, end + 1):
                        key = f"{relative}:{line}"
                        if len(calls) >= MAX_SITES and key not in calls:
                            break
                        calls.setdefault(key, set()).add(target)
            for child in ast.iter_child_nodes(node):
                visit(child, bindings, function_parent, depth + 1)

        for node in tree.body:
            visit(node, global_names)
    return {
        "calls": {key: sorted(value) for key, value in calls.items()},
        "class_bases": {name: values[0] for name, values in bases.items() if len(values) == 1},
    }


def assertion_operands(message):
    line = message.splitlines()[0] if message else ""
    if len(line) > 8000:
        return None
    try:
        tree = ast.parse(line)
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assert):
            return None
        value = tree.body[0].test
        if not isinstance(value, ast.Compare) or len(value.ops) != 1 or not isinstance(value.ops[0], ast.Eq):
            return None
        operands = [ast.literal_eval(n) for n in (value.left, value.comparators[0])]
        return operands
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return None


def resolved_calls(evidence, project, legacy=False):
    """Only call sites matching the function named by the argument error."""
    if "source_context" in project:
        sites = project["source_context"].get("calls", {}).get(evidence.get("where", ""), [])
        callees = {c.rsplit(".", 1)[-1] for c in evidence.get("callees", [])}
        return [target for target in sites if target.rsplit(".", 1)[-1] in callees]
    if not legacy:
        return []
    result = []
    for callee in evidence.get("callees", []):
        head, _, tail = callee.partition(".")
        target = project.get("imported_names", {}).get(head)
        if target and head not in project.get("defined_names", []):
            result.append(target + ("." + tail if tail else ""))
    return result


def feature_values(evidence, values, project, environment):
    """Relations among observed names, call sites and version records; no causes."""
    imports = environment.get("import_distributions", {})
    stdlib = set(environment.get("stdlib_modules", []))
    own = set(project.get("own_names", []))
    local = {p.removeprefix("src/").split("/")[0].removesuffix(".py")
             for p in project.get("python_files", [])}

    def origin(target):
        top = target.split(".")[0]
        providers = imports.get(top, [])
        if top in local or any(canonicalize_name(p) in own for p in providers):
            return "project"
        if top in stdlib or providers:
            return "external"
        return "unknown"

    index = project.get("source_context", {})
    targets = resolved_calls(evidence, project)
    signature = bool(evidence.get("call_signature"))
    external_call = signature and any(origin(t) == "external" for t in targets)
    project_call = signature and any(origin(t) == "project" for t in targets)
    external_base = any(
        origin(base) == "external"
        for owner in evidence.get("owners", [])
        for base in index.get("class_bases", {}).get(owner, []) if base
    )
    provider = values["module_installed"] or values["module_stdlib"]
    project_resolution = (
        values["module_local"] or (values["module_similar_local"] and not provider)
        or values["signal_relative_import"] or values["signal_partially_initialized"]
        or values["owner_defined_locally"]
    )
    external_api = (
        provider and not values["module_local"]
        and (values["api_mentioned"] or values["missing_module_dotted"])
    ) or external_call or (external_base and values["signal_no_attribute"])

    involved = set(evidence.get("modules", []))
    involved.update(t.split(".")[0] for t in targets)
    if evidence.get("library"):
        involved.add(evidence["library"])
    distributions = {canonicalize_name(p) for name in involved for p in imports.get(name, [])}
    installed = {canonicalize_name(p.get("name", "")): p.get("version", "")
                 for p in environment.get("packages", [])}
    changed = False
    for row in project.get("tested_versions", []):
        name = row["name"]
        if name not in distributions or name not in installed:
            continue
        try:
            changed |= Version(installed[name]).release[:2] != Version(row["version"]).release[:2]
        except InvalidVersion:
            continue
    conflict = any(row["name"] in distributions and row.get("status") == "version_mismatch"
                   for row in project.get("declarations", []))
    operands = assertion_operands(evidence.get("message", "")) if evidence["exception"] == "AssertionError" else None
    text = bool(operands and all(type(v) is str for v in operands) and operands[0] != operands[1])
    numeric = bool(operands and all(type(v) in (int, float) for v in operands) and operands[0] != operands[1])
    namespace = evidence.get("exception_module", "").split(".")[0]
    return {
        "context_project_resolution": project_resolution,
        "context_external_api": external_api,
        "call_signature_mismatch": signature,
        "callee_project": project_call,
        "callee_external": external_call,
        "assertion_text_difference": text,
        "assertion_numeric_difference": numeric,
        "assertion_scalar_representation": text and scalar_representation_only(evidence["message"]),
        "relevant_lock_series_changed": changed,
        "relevant_requirement_conflict": conflict,
        "library_exception_type": bool(namespace and namespace not in ("builtins", "_pytest", "pytest")
                                       and imports.get(namespace)),
        "source_context_available": "source_context" in project,
    }

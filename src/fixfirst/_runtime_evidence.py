"""Bounded, standard-library-only exception observations in the target Python.

Copied beside the pytest probe; also used by the standalone unittest runner.
Record names, shapes and supplied keys only, never object values or array data.
"""

import ast
import dis
import re
import sys
import types


def plain_class(cls):
    """Only the builtin metaclass or the already loaded standard ABCMeta."""
    abc = sys.modules.get("abc")
    abc_meta = vars(abc).get("ABCMeta") if type(abc) is types.ModuleType else None
    return type(cls) is type or (abc_meta is not None and type(cls) is abc_meta)


def class_namespace(cls):
    # Invoke Python's own descriptor directly, never a metaclass override.
    return type.__dict__["__dict__"].__get__(cls)


def class_mro(cls):
    return type.__dict__["__mro__"].__get__(cls)


def class_identity(cls):
    if not plain_class(cls):
        return "", ""
    module = type.__dict__["__module__"].__get__(cls)
    name = type.__dict__["__qualname__"].__get__(cls)
    if type(module) is not str or type(name) is not str or max(len(module), len(name)) > 200:
        return "", ""
    loaded = sys.modules.get(module)
    if type(loaded) is types.ModuleType and vars(loaded).get(name) is cls:
        return module, name
    return "", ""


def receiver_owners(value):
    """Bounded registered MRO identities and real exports from loaded parent modules.

    Public aliases (unittest.TestCase, pandas.DataFrame) must point to the exact
    same class. No module is imported and no object attribute is evaluated.
    """
    cls = value if plain_class(value) else type(value)
    if not plain_class(cls):
        return []
    mro = class_mro(cls)
    if len(mro) > 16:
        return []
    rows = []
    for parent in mro:
        module, name = class_identity(parent)
        if not module or parent is object:
            continue
        parts = module.split(".")
        if len(parts) > 8:
            continue
        for end in range(len(parts), 0, -1):
            alias_module = ".".join(parts[:end])
            loaded = sys.modules.get(alias_module)
            if type(loaded) is not types.ModuleType:
                continue
            namespace = vars(loaded)
            origin = namespace.get("__file__", "")
            if (len(namespace) > 5000 or type(origin) is not str or len(origin) > 4000):
                continue
            aliases = sorted(key for key, item in namespace.items() if item is parent
                             and type(key) is str and key.isidentifier() and len(key) <= 200)
            for alias in aliases[:8]:
                rows.append({"module": alias_module, "owner": alias, "file": origin, "direct": parent is cls})
                if len(rows) >= 32:
                    return []  # An incomplete identity set must not imply unique ownership.
    return rows


def registered_type(value):
    cls = type(value)
    try:
        return class_identity(cls)
    except Exception:
        pass
    return "", ""


def attribute_at_failure(tb, *, receiver=False):
    """Recover only a simple name receiver at the actual failed attribute load.

    Some extension descriptors (NumPy 2.2's removed methods) omit name/obj on
    AttributeError. Do not execute an expression, follow properties, or infer
    an object from text. Complex receivers and exceptions inside a call stay unknown.
    """
    if tb is None or len(tb.tb_frame.f_code.co_code) > 64_000:
        return {}
    previous, intervening_target = None, False
    try:
        for instruction in dis.get_instructions(tb.tb_frame.f_code):
            if instruction.offset > tb.tb_lasti:
                break
            if instruction.opname in ("EXTENDED_ARG", "CACHE"):
                intervening_target |= instruction.is_jump_target
                continue
            if instruction.offset == tb.tb_lasti:
                if (instruction.opname not in ("LOAD_ATTR", "LOAD_METHOD")
                        or not isinstance(instruction.argval, str) or previous is None
                        or instruction.is_jump_target or intervening_target):
                    return {}
                frame, key = tb.tb_frame, previous.argval
                if previous.opname in ("LOAD_FAST_LOAD_FAST", "STORE_FAST_LOAD_FAST",
                                       "LOAD_FAST_BORROW_LOAD_FAST_BORROW"):
                    # CPython 3.13/3.14 combines these loads. The low nibble
                    # identifies the final (top-of-stack) loaded local.
                    # https://docs.python.org/3.14/library/dis.html
                    if not isinstance(previous.arg, int):
                        return {}
                    key = frame.f_code.co_varnames[previous.arg & 15]
                    value = frame.f_locals.get(key)
                elif previous.opname == "LOAD_CONST" and type(key) in (str, bytes, int, float, bool, tuple):
                    value = key
                elif not isinstance(key, str):
                    return {}
                elif previous.opname in ("LOAD_FAST", "LOAD_FAST_CHECK", "LOAD_FAST_BORROW", "LOAD_DEREF"):
                    value = frame.f_locals.get(key)
                elif previous.opname == "LOAD_GLOBAL":
                    value = frame.f_globals.get(key)
                elif previous.opname == "LOAD_NAME":
                    value = frame.f_locals.get(key, frame.f_globals.get(key))
                else:
                    return {}
                if receiver:
                    return value, instruction.argval
                module, name = registered_type(value)
                if module:
                    return {"name": instruction.argval[:128], "owner_module": module,
                            "owner_name": name, "source": "traceback_instruction"}
                return {}
            previous = instruction
            intervening_target = False
    except Exception:
        pass
    return {}


def one_edit(left, right):
    """Conservative typo patterns: an adjacent swap or a doubled character.

    Arbitrary insertions/substitutions include intentional API prefixes such as
    msort versus sort; those must not become spelling diagnoses.
    """
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        different = [n for n, (a, b) in enumerate(zip(left, right)) if a != b]
        return (len(different) == 2 and different[1] == different[0] + 1
            and left[different[0]] == right[different[1]] and left[different[1]] == right[different[0]])
    short, long = (left, right) if len(left) < len(right) else (right, left)
    return any(long[n] == long[n + 1] and long[:n] + long[n + 1:] == short for n in range(len(long) - 1))


def module_attribute(error, tracebacks):
    """A spelling lead from the actual, already loaded module, never a new import."""
    if type(error) is not AttributeError or not error.args or type(error.args[0]) is not str:
        return {}
    message = re.match(r"module '([\w.]+)' has no attribute '(\w+)'", error.args[0])
    if not message or len(message[2]) > 80:
        return {}
    for tb in reversed(tracebacks[-20:]):
        found = attribute_at_failure(tb, receiver=True)
        if not isinstance(found, tuple):
            continue
        value, name = found
        if name != message[2] or type(value) is not type(sys):
            continue
        namespace = vars(value)
        module = namespace.get("__name__")
        if module != message[1] or sys.modules.get(module) is not value or len(namespace) > 5000:
            continue
        alternatives = sorted(key for key in namespace if type(key) is str and key.isidentifier()
                              and not key.startswith("_") and len(key) <= 80 and one_edit(name, key))
        return {"module": module, "name": name, "suggestions": alternatives[:5],
                "unique": len(alternatives) == 1, "source": "loaded_module_namespace",
                "file": tb.tb_frame.f_code.co_filename, "line": tb.tb_lineno}
    return {}


def near_distance(left, right):
    """Levenshtein distance capped at two; a narrow band bounds the work."""
    if abs(len(left) - len(right)) > 2:
        return 3
    previous = {j: j for j in range(min(len(right), 2) + 1)}
    for i, char in enumerate(left, 1):
        current = {0: i} if i <= 2 else {}
        for j in range(max(1, i - 2), min(len(right), i + 2) + 1):
            current[j] = min(current.get(j - 1, 3) + 1, previous.get(j, 3) + 1,
                             previous.get(j - 1, 3) + (char != right[j - 1]))
        if min(current.values(), default=3) > 2:
            return 3
        previous = current
    return min(previous.get(len(right), 3), 3)


def namespace_candidates(name, keys):
    found = []
    for key in sorted(k for k in keys if type(k) is str and k.isidentifier()
                      and not k.startswith("_") and len(k) <= 80 and k != name):
        if name.isascii() and key.isascii() and name.casefold() == key.casefold():
            rank, relation = 0, "case"
        elif one_edit(name, key):
            rank, relation = 1, "swap" if len(name) == len(key) else "repeat"
        else:
            distance = near_distance(name, key)
            if distance > 2 or min(len(name), len(key)) < 3:
                continue
            rank, relation = 2 + distance, "other"
        found.append((rank, key, relation))
    if not found:
        return [], False
    best = min(row[0] for row in found)
    tied = [{"name": key, "relation": relation} for rank, key, relation in found if rank == best]
    return tied[:5], len(tied) == 1


def static_namespace(value):
    """Read dictionary keys only. Never call dir(), a property or __getattr__."""
    if type(value) is types.ModuleType:
        namespace = vars(value)
        module = namespace.get("__name__")
        if type(module) is not str or sys.modules.get(module) is not value or len(namespace) > 5000:
            return None
        return {key for key in namespace if type(key) is str}, "module", module, "", "__getattr__" in namespace
    cls = value if plain_class(value) else type(value)
    if not plain_class(cls):
        return None
    mro = class_mro(cls)
    if len(mro) > 16:
        return None
    keys, dynamic = set(), False
    for parent in mro:
        namespace = class_namespace(parent)
        if len(keys) + len(namespace) > 5000:
            return None
        keys.update(key for key in namespace if type(key) is str)
        dynamic |= "__getattr__" in namespace or (parent is not object and "__getattribute__" in namespace)
    if plain_class(value):
        module, name = class_identity(cls)
        kind = "class"
    else:
        module, name = registered_type(value)
        kind = "instance"
    return keys, kind, module, name, dynamic


def _operand(frame, instruction):
    """Only direct loads; caller must establish their place in the failed operation."""
    key = instruction.argval
    if instruction.opname == "LOAD_CONST" and type(key) in (str, bytes, int, float, bool, tuple):
        return True, key
    if type(key) is not str:
        return False, None
    if instruction.opname in ("LOAD_FAST", "LOAD_FAST_CHECK", "LOAD_FAST_BORROW", "LOAD_DEREF"):
        return key in frame.f_locals, frame.f_locals.get(key)
    if instruction.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
        scope = frame.f_locals if instruction.opname == "LOAD_NAME" else frame.f_globals
        if key in scope:
            return True, scope[key]
        if key in frame.f_globals:
            return True, frame.f_globals[key]
        return key in frame.f_builtins, frame.f_builtins.get(key)
    return False, None


def builtin_arity_observation(error, tb):
    """A real builtin binding failure at CALL; no inferred or executed expressions.

    Unsupported call shapes remain unknown. In particular, a Python function
    which manually raises the same TypeError ends at RAISE, not this CALL.
    """
    if tb is None or len(tb.tb_frame.f_code.co_code) > 64000:
        return {}
    match = re.match(r"^([\w.]+)\(\) takes exactly (zero|one|two|\d+) arguments? \((\d+) given\)", error.args[0])
    if not match:
        return {}
    expected = {"zero": 0, "one": 1, "two": 2}.get(match[2])
    expected = int(match[2]) if expected is None else expected
    given = int(match[3])
    if not 1 <= given <= 8 or given == expected:
        return {}
    instructions = [i for i in dis.get_instructions(tb.tb_frame.f_code)
                    if i.offset <= tb.tb_lasti and i.opname not in ("CACHE", "EXTENDED_ARG", "PRECALL")]
    if not instructions or instructions[-1].offset != tb.tb_lasti:
        return {}
    call = instructions[-1]
    if call.opname not in ("CALL", "CALL_FUNCTION", "CALL_METHOD") or call.argval != given:
        return {}
    tail = instructions[-given - 3:-1]
    if len(tail) < given + 1 or any(i.is_jump_target for i in tail):
        return {}
    arguments = [_operand(tb.tb_frame, i) for i in tail[-given:]]
    if not all(known for known, _ in arguments):
        return {}
    callee = tail[-given - 1]
    owner = ""
    if callee.opname in ("LOAD_ATTR", "LOAD_METHOD") and len(tail) == given + 2:
        known, receiver = _operand(tb.tb_frame, tail[0])
        cls = type(receiver)
        if not known or type(cls) is not type or type.__getattribute__(cls, "__module__") != "builtins":
            return {}
        owner, name = type.__getattribute__(cls, "__name__"), callee.argval
        member = type.__getattribute__(cls, "__dict__").get(name)
        if type(member) is not types.MethodDescriptorType or match[1] != f"{owner}.{name}":
            return {}
    else:
        known, function = _operand(tb.tb_frame, callee)
        if not known or type(function) is not types.BuiltinFunctionType or function.__module__ != "builtins":
            return {}
        name = function.__name__
        if match[1] != name or vars(sys.modules["builtins"]).get(name) is not function:
            return {}
    # Only coarse builtin types, never supplied values or user-defined repr/name hooks.
    types_seen = [next((name for cls, name in ((str, "str"), (bytes, "bytes"), (int, "int"),
                   (float, "float"), (list, "list"), (tuple, "tuple"), (dict, "dict"))
                   if type(value) is cls), "other") for _, value in arguments]
    return {"source": "failed_instruction_namespace", "kind": "builtin_call", "module": "builtins",
            "owner": owner, "name": name, "static_namespace_checked": True,
            "requested_member_present": True, "dynamic": False, "candidates": [], "unique": False,
            "argument_count_expected": expected, "argument_count_given": given, "argument_types": types_seen,
            "file": tb.tb_frame.f_code.co_filename, "line": tb.tb_lineno, "operation": call.opname}


def _argument_type(value):
    return next((name for cls, name in ((str, "str"), (bytes, "bytes"), (int, "int"),
                (float, "float"), (list, "list"), (tuple, "tuple"), (dict, "dict"))
                 if type(value) is cls), "other")


def _call_operands(tb):
    """Recover only direct loads at the innermost failed CALL; never evaluate them."""
    if (tb is None or len(tb.tb_frame.f_code.co_code) > 64000
            or len(tb.tb_frame.f_code.co_filename) > 4000):
        return None
    frame = tb.tb_frame
    instructions = [i for i in dis.get_instructions(frame.f_code)
                    if i.offset <= tb.tb_lasti and i.opname not in ("CACHE", "EXTENDED_ARG", "PRECALL")]
    if not instructions or instructions[-1].offset != tb.tb_lasti:
        return None
    call = instructions.pop()
    if (call.opname not in ("CALL", "CALL_FUNCTION", "CALL_METHOD", "CALL_KW", "CALL_FUNCTION_KW")
            or type(call.argval) is not int or not 0 <= call.argval <= 8 or call.is_jump_target):
        return None
    count, keywords = call.argval, ()
    if instructions and instructions[-1].opname == "KW_NAMES":
        names = instructions.pop()
        if names.is_jump_target or type(names.arg) is not int:
            return None
        keywords = frame.f_code.co_consts[names.arg]
    elif call.opname in ("CALL_KW", "CALL_FUNCTION_KW"):
        if not instructions or instructions[-1].opname != "LOAD_CONST":
            return None
        names = instructions.pop()
        if names.is_jump_target:
            return None
        keywords = names.argval
    if (type(keywords) is not tuple or len(keywords) > count
            or any(type(k) is not str or not k.isidentifier() or len(k) > 80 for k in keywords)
            or len(set(keywords)) != len(keywords) or len(instructions) < count + 1):
        return None
    args = instructions[-count:] if count else []
    before = instructions[:-count] if count else instructions
    if any(i.is_jump_target for i in args):
        return None
    loaded = [(True, None) if instruction.opname == "LOAD_CONST" and instruction.argval is None
              else _operand(frame, instruction) for instruction in args]
    if not all(known for known, _ in loaded):
        return None
    # CPython 3.13 places PUSH_NULL after the callable in some call forms.
    if before and before[-1].opname == "PUSH_NULL" and not before[-1].is_jump_target:
        before = before[:-1]
    if not before or before[-1].is_jump_target:
        return None
    callee = before[-1]
    name = callee.argval
    if type(name) is not str or not name.isidentifier() or len(name) > 80:
        return None
    if callee.opname in ("LOAD_ATTR", "LOAD_METHOD"):
        if len(before) < 2 or before[-2].is_jump_target:
            return None
        known, module = _operand(frame, before[-2])
        if not known or type(module) is not types.ModuleType:
            return None  # Bound methods, descriptors and receiver expressions stay unknown.
        namespace = vars(module)
        module_name = namespace.get("__name__")
        if (type(module_name) is not str or sys.modules.get(module_name) is not module
                or len(namespace) > 5000 or "__getattr__" in namespace):
            return None
        function = namespace.get(name)
    else:
        known, function = _operand(frame, callee)
        if not known:
            return None
    return function, name, count - len(keywords), list(keywords), [
        _argument_type(value) for _, value in loaded], call.opname


def _parameters(function):
    """Read code layout or trusted builtin text, with no signature/default evaluation."""
    if type(function) is types.FunctionType:
        code = function.__code__
        if code.co_flags & (4 | 8):
            return [], "variadic_signature"
        total = code.co_argcount + code.co_kwonlyargcount
        if total > 32:
            return [], "signature_limit"
        defaults, kwdefaults = function.__defaults__, function.__kwdefaults__
        if defaults is not None and type(defaults) is not tuple:
            return [], "unsupported_callable"
        if kwdefaults is not None and type(kwdefaults) is not dict:
            return [], "unsupported_callable"
        if kwdefaults and (len(kwdefaults) > 32 or any(type(k) is not str for k in kwdefaults)):
            return [], "unsupported_callable"
        required = code.co_argcount - len(defaults or ())
        parameters = [{"name": name,
                       "kind": "positional_only" if i < code.co_posonlyargcount else "positional_or_keyword",
                       "required": i < required}
                      for i, name in enumerate(code.co_varnames[:code.co_argcount])]
        parameters += [{"name": name, "kind": "keyword_only", "required": name not in (kwdefaults or {})}
                       for name in code.co_varnames[code.co_argcount:total]]
    elif (type(function) is types.BuiltinFunctionType and function.__module__ == "builtins"
          and vars(sys.modules["builtins"]).get(function.__name__) is function):
        signature = function.__text_signature__
        if type(signature) is not str or len(signature) > 2000:
            return [], "unsupported_callable"
        # $module is a CPython implementation parameter, not a supplied argument.
        signature = re.sub(r"^\(\$module,\s*/\s*(?:,\s*)?", "(", signature)
        signature = re.sub(r"^\(\$module,\s*", "(", signature)
        try:
            tree = ast.parse("def observed" + signature + ":\n pass")
        except (SyntaxError, ValueError, RecursionError):
            return [], "unsupported_callable"
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
            return [], "unsupported_callable"
        arguments = tree.body[0].args
        if arguments.vararg or arguments.kwarg:
            return [], "variadic_signature"
        positional = arguments.posonlyargs + arguments.args
        if len(positional) + len(arguments.kwonlyargs) > 32:
            return [], "signature_limit"
        parameters = [{"name": arg.arg,
                       "kind": "positional_only" if i < len(arguments.posonlyargs) else "positional_or_keyword",
                       "required": i < len(positional) - len(arguments.defaults)}
                      for i, arg in enumerate(positional)]
        parameters += [{"name": arg.arg, "kind": "keyword_only", "required": default is None}
                       for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults)]
    else:
        return [], "unsupported_callable"
    if any(not p["name"].isidentifier() or len(p["name"]) > 80 for p in parameters):
        return [], "signature_limit"
    return parameters, "observed_operation"


def _binding_errors(parameters, positional_count, keyword_names):
    positional = [p for p in parameters if p["kind"] != "keyword_only"]
    by_name = {p["name"]: p for p in parameters}
    bound = {p["name"] for p in positional[:positional_count]}
    errors = {"positional_only_as_keyword": [], "missing": [], "unexpected": [], "duplicate": [],
              "too_many_positional": positional_count > len(positional)}
    for name in keyword_names:
        parameter = by_name.get(name)
        if parameter is None:
            errors["unexpected"].append(name)
        elif parameter["kind"] == "positional_only":
            errors["positional_only_as_keyword"].append(name)
        elif name in bound:
            errors["duplicate"].append(name)
        else:
            bound.add(name)
    errors["missing"] = [p["name"] for p in parameters if p["required"] and p["name"] not in bound]
    return errors


def binding_observation(error, tb):
    if type(error) is not TypeError:
        return {}, "unsupported_exception"
    operands = _call_operands(tb)
    if operands is None:
        return {}, "unsupported_call_shape"
    function, name, positional, keywords, argument_types, operation = operands
    parameters, status = _parameters(function)
    if status != "observed_operation":
        return {}, status
    errors = _binding_errors(parameters, positional, keywords)
    if not any(errors.values()):
        return {}, "valid_binding_body_error"
    module, callee_name = function.__module__, function.__name__
    if (type(module) is not str or len(module) > 200 or not all(p.isidentifier() for p in module.split("."))
            or type(callee_name) is not str or not callee_name.isidentifier() or len(callee_name) > 80):
        return {}, "unsupported_callable"
    python = type(function) is types.FunctionType
    record = {"source": "failed_instruction_namespace", "kind": "python_binding" if python else "builtin_binding",
              "operation": operation, "module": module, "owner": "", "name": name, "callee_name": callee_name,
              "static_namespace_checked": True, "requested_member_present": True, "dynamic": False,
              "candidates": [], "unique": False, "file": tb.tb_frame.f_code.co_filename, "line": tb.tb_lineno,
              "parameters": parameters, "positional_count": positional, "keyword_names": keywords,
              "argument_types": argument_types, "binding_errors": errors}
    if python and len(function.__code__.co_filename) <= 4000:
        record.update(definition_file=function.__code__.co_filename, definition_line=function.__code__.co_firstlineno)
    return record, "observed_operation"


def symbol_observation(error, tracebacks, *, status=None):
    """A bounded observation, not a spelling diagnosis or an API-history claim."""
    def finish(record, reason):
        if status is not None:
            status["status"] = reason
        return record

    reason = "unsupported_call_shape"
    try:
        if type(error) not in (AttributeError, ImportError, TypeError) or not error.args or type(error.args[0]) is not str:
            return finish({}, "unsupported_exception")
        if type(error) is TypeError:
            last = tracebacks[-1] if tracebacks else None
            legacy = builtin_arity_observation(error, last)
            if legacy:
                return finish(legacy, "observed_operation")
            record, reason = binding_observation(error, last)
            return finish(record, reason)
        imported = re.match(r"cannot import name '(\w+)' from '([\w.]+)'", error.args[0])
        for tb in reversed(tracebacks[-20:]):
            if len(tb.tb_frame.f_code.co_code) > 64000:
                continue
            instructions = list(dis.get_instructions(tb.tb_frame.f_code))
            instruction = next((i for i in instructions if i.offset == tb.tb_lasti), None)
            if instruction is None:
                continue
            if type(error) is AttributeError:
                found = attribute_at_failure(tb, receiver=True)
                native = False
                if (not isinstance(found, tuple) and tb is tracebacks[-1]
                        and instruction.opname in ("LOAD_ATTR", "LOAD_METHOD")
                        and not instruction.is_jump_target and type(error.name) is str
                        and error.name == instruction.argval and error.obj is not None):
                    found, native = (error.obj, error.name), True
                if not isinstance(found, tuple):
                    continue
                value, missing = found
                if error.name is not None and error.name != missing:
                    continue
                if error.obj is not None and error.obj is not value:
                    continue
            elif imported and error.name == imported[2] and instruction.opname == "IMPORT_FROM":
                if instruction.argval != imported[1] or instruction.is_jump_target:
                    continue
                imported_name = None
                for earlier in instructions:
                    if earlier.offset >= instruction.offset:
                        break
                    if earlier.is_jump_target:
                        imported_name = None
                    if earlier.opname == "IMPORT_NAME":
                        imported_name = earlier.argval
                if imported_name != error.name:
                    continue  # Relative/ambiguous imports are not reconstructed.
                missing, value = imported[1], sys.modules.get(error.name)
            else:
                continue
            if type(missing) is not str or not missing.isidentifier() or len(missing) > 80:
                continue
            namespace = static_namespace(value)
            if namespace is None:
                reason = "unsupported_receiver"
                continue
            keys, kind, module, owner, dynamic = namespace
            if type(error) is AttributeError and native and (dynamic or missing in keys):
                return finish({}, "dynamic_receiver" if dynamic else "member_present")
            hints, unique = namespace_candidates(missing, keys) if missing not in keys else ([], False)
            return finish({"source": "failed_instruction_namespace", "kind": kind,
                    "module": module, "owner": owner, "name": missing,
                    "static_namespace_checked": True, "requested_member_present": missing in keys,
                    "dynamic": dynamic, "candidates": hints, "unique": unique,
                    "file": tb.tb_frame.f_code.co_filename, "line": tb.tb_lineno,
                    "operation": instruction.opname,
                    **({"receiver_owners": receiver_owners(value)} if kind in ("class", "instance") else {})},
                    "observed_operation")
    except Exception:
        reason = "unsupported_observation"
    return finish({}, reason)


def django_registry_state(tb):
    """Read native bools from the actual global Apps receiver at its failure.

    No Django import, API, property, __getattr__ or user __dict__ descriptor is
    invoked. A custom registry and changed method/class bindings stay unknown.
    This records current state, never whether setup ran at an earlier time.
    """
    if tb is None:
        return {}
    module = sys.modules.get("django.apps.registry")
    if type(module) is not types.ModuleType:
        return {}
    namespace = vars(module)
    cls, receiver = namespace.get("Apps"), tb.tb_frame.f_locals.get("self")
    if type(cls) is not type or type(receiver) is not cls or receiver is not namespace.get("apps"):
        return {}
    members = type.__getattribute__(cls, "__dict__")
    method, descriptor = members.get("check_apps_ready"), members.get("__dict__")
    if (type(method) is not types.FunctionType or method.__code__ is not tb.tb_frame.f_code
            or type(descriptor) is not types.GetSetDescriptorType):
        return {}
    values = descriptor.__get__(receiver, cls)
    keys = ("apps_ready", "loading", "ready")
    if type(values) is not dict or not all(type(values.get(key)) is bool for key in keys):
        return {}
    return {"global_registry": True, **{key: values[key] for key in keys}}


def exception_metadata(error, tb):
    result = {"attribute_access": {}, "traceback_frames": [], "validation_errors": [], "module_attribute": {}}
    if type(error) is AttributeError and isinstance(getattr(error, "name", None), str):
        module, name = registered_type(error.obj)
        if module:
            result["attribute_access"] = {"name": error.name[:128], "owner_module": module,
                                          "owner_name": name, "source": "exception_object"}
    frames, tracebacks, last = [], [], None
    while tb is not None and len(frames) < 200:
        last = tb
        tracebacks.append(tb)
        frame = tb.tb_frame
        module, function = frame.f_globals.get("__name__", ""), frame.f_code.co_name
        row = {"file": frame.f_code.co_filename, "line": tb.tb_lineno, "function": function}
        if module in ("numpy.linalg._linalg", "numpy.linalg.linalg") and function == "solve":
            shapes = {}
            for key in ("a", "b"):
                value = frame.f_locals.get(key)
                if registered_type(value) == ("numpy", "ndarray"):
                    shape = value.shape
                    if len(shape) <= 16:
                        shapes[key] = list(shape)
            if len(shapes) == 2:
                row["array_shapes"] = shapes
        frames.append(row)
        tb = tb.tb_next
    result["traceback_frames"] = frames[-20:]
    registry = django_registry_state(last)
    if registry:
        result["django_registry"] = registry
    result["module_attribute"] = module_attribute(error, tracebacks)
    symbol_status = {"status": "traceback_limit"}
    result["symbol_observation"] = symbol_observation(error, tracebacks, status=symbol_status) if tb is None else {}
    result["symbol_observation_status"] = symbol_status["status"]
    # pytest wraps collection imports in Collector.CollectError. Its real
    # exception chain still retains the failed IMPORT_FROM and loaded module;
    # the wrapper's formatted text alone is never used to reconstruct them.
    pytest_nodes = sys.modules.get("_pytest.nodes")
    collector = vars(pytest_nodes).get("Collector") if type(pytest_nodes) is types.ModuleType else None
    wrapped_type = type.__getattribute__(collector, "__dict__").get("CollectError") if isinstance(collector, type) else None
    if type(error) is wrapped_type and not result["symbol_observation"]:
        cause = error.__cause__ if error.__cause__ is not None else error.__context__
        if type(cause) in (ImportError, AttributeError, TypeError):
            cause_tb, cause_frames = cause.__traceback__, []
            while cause_tb is not None and len(cause_frames) < 200:
                cause_frames.append(cause_tb)
                cause_tb = cause_tb.tb_next
            if cause_tb is None:
                result["symbol_observation"] = symbol_observation(cause, cause_frames, status=symbol_status)
                result["symbol_observation_status"] = symbol_status["status"]
            else:
                result["symbol_observation_status"] = "traceback_limit"
    if type(error) is AttributeError and not result["attribute_access"] and tb is None:
        result["attribute_access"] = attribute_at_failure(last)

    module, name = registered_type(error)
    if module in ("pydantic_core._pydantic_core", "pydantic_core") and name == "ValidationError":
        try:
            if error.error_count() <= 20:
                for item in error.errors(include_url=False, include_context=False):
                    location, supplied = item.get("loc"), item.get("input")
                    if (item.get("type") != "missing" or not isinstance(location, tuple)
                            or len(location) != 1 or not isinstance(location[0], str)
                            or not isinstance(supplied, dict) or len(supplied) > 32
                            or not all(isinstance(k, str) and len(k) <= 128 for k in supplied)):
                        continue
                    result["validation_errors"].append(
                        {"type": "missing", "field": location[0][:128], "input_keys": sorted(supplied)})
        except Exception:
            pass
    return result

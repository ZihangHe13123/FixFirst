"""Bounded, standard-library-only exception observations in the target Python.

Copied beside the pytest probe; also used by the standalone unittest runner.
Record names, shapes and supplied keys only, never object values or array data.
"""

import dis
import sys


def registered_type(value):
    cls = type(value)
    try:
        module, name = type.__getattribute__(cls, "__module__"), type.__getattribute__(cls, "__qualname__")
        loaded = sys.modules.get(module)
        if (isinstance(module, str) and isinstance(name, str) and loaded is not None
                and vars(loaded).get(name) is cls):
            return module[:200], name[:200]
    except Exception:
        pass
    return "", ""


def attribute_at_failure(tb):
    """Recover only a simple name receiver at the actual failed attribute load.

    Some extension descriptors (NumPy 2.2's removed methods) omit name/obj on
    AttributeError. Do not execute an expression, follow properties, or infer
    an object from text. Complex receivers and exceptions inside a call stay unknown.
    """
    if tb is None or len(tb.tb_frame.f_code.co_code) > 64_000:
        return {}
    previous = None
    try:
        for instruction in dis.get_instructions(tb.tb_frame.f_code):
            if instruction.offset > tb.tb_lasti:
                break
            if instruction.offset == tb.tb_lasti:
                if (instruction.opname not in ("LOAD_ATTR", "LOAD_METHOD")
                        or not isinstance(instruction.argval, str) or previous is None
                        or not isinstance(previous.argval, str)):
                    return {}
                frame, key = tb.tb_frame, previous.argval
                if previous.opname in ("LOAD_FAST", "LOAD_FAST_CHECK", "LOAD_DEREF"):
                    value = frame.f_locals.get(key)
                elif previous.opname == "LOAD_GLOBAL":
                    value = frame.f_globals.get(key)
                elif previous.opname == "LOAD_NAME":
                    value = frame.f_locals.get(key, frame.f_globals.get(key))
                else:
                    return {}
                module, name = registered_type(value)
                if module:
                    return {"name": instruction.argval[:128], "owner_module": module,
                            "owner_name": name, "source": "traceback_instruction"}
                return {}
            previous = instruction
    except Exception:
        pass
    return {}


def exception_metadata(error, tb):
    result = {"attribute_access": {}, "traceback_frames": [], "validation_errors": []}
    if type(error) is AttributeError and isinstance(getattr(error, "name", None), str):
        module, name = registered_type(error.obj)
        if module:
            result["attribute_access"] = {"name": error.name[:128], "owner_module": module,
                                          "owner_name": name, "source": "exception_object"}
    frames, last = [], None
    while tb is not None and len(frames) < 200:
        last = tb
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

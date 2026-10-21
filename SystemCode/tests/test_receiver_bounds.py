"""Keep deep real-library inheritance usable without unbounded evidence."""

import json
import sys
import types

import pytest

from fixfirst._runtime_evidence import receiver_owners, static_namespace
from fixfirst.symbol_context import valid_record


def hierarchy(monkeypatch, depth, aliases=1, origin="/library/deep.py"):
    module = types.ModuleType("bounded_library")
    module.__file__ = origin
    monkeypatch.setitem(sys.modules, module.__name__, module)
    cls = object
    for number in range(depth):
        name = f"Class{number}"
        cls = type(name, (cls,), {"__module__": module.__name__})
        setattr(module, name, cls)
        for alias in range(1, aliases):
            setattr(module, f"Alias{number}_{alias}", cls)
    return cls()


def observation(owners):
    return {"source": "failed_instruction_namespace", "kind": "instance",
            "module": "bounded_library", "owner": "Class0", "name": "removed",
            "static_namespace_checked": True, "requested_member_present": False,
            "dynamic": False, "candidates": [], "unique": False,
            "operation": "LOAD_ATTR", "file": "/project/app.py", "line": 2,
            "receiver_owners": owners}


@pytest.mark.parametrize("depth", [40, 63])
def test_deep_registered_hierarchy_retains_public_base_and_direct_owner(monkeypatch, depth):
    value = hierarchy(monkeypatch, depth)
    owners = receiver_owners(value)
    assert len(owners) == depth
    assert owners[0]["owner"] == f"Class{depth - 1}" and owners[0]["direct"]
    assert owners[-1]["owner"] == "Class0" and not owners[-1]["direct"]
    assert static_namespace(value) is not None
    assert valid_record(observation(owners))


def test_mro_overflow_cannot_return_a_partial_ancestry(monkeypatch):
    value = hierarchy(monkeypatch, 64)  # Includes object: 65 MRO entries.
    assert receiver_owners(value) == []
    assert static_namespace(value) is None


def test_alias_row_boundary_is_shared_by_capture_and_reader(monkeypatch):
    value = hierarchy(monkeypatch, 16, aliases=8)
    owners = receiver_owners(value)
    assert len(owners) == 128
    assert valid_record(observation(owners))
    assert valid_record(observation([*owners, owners[0]])) == {}
    assert receiver_owners(hierarchy(monkeypatch, 17, aliases=8)) == []


@pytest.mark.parametrize("origin", ["/" + "a" * 3900, "/" + "测" * 1000])
def test_many_long_paths_fail_closed_in_capture_and_reader(monkeypatch, origin):
    value = hierarchy(monkeypatch, 3, origin=origin)
    owners = receiver_owners(value)
    assert len(owners) == 3
    assert valid_record(observation(owners))
    oversized = owners * 4  # <128 rows, each individual path remains <=4000.
    assert valid_record(observation(oversized)) == {}
    assert receiver_owners(hierarchy(monkeypatch, 12, origin=origin)) == []


def test_serialized_budget_accepts_exact_boundary_rejects_next_byte():
    owners = [{"module": "bounded_library", "owner": f"Class{i}", "file": "", "direct": False}
              for i in range(9)]
    remaining = 32768 - len(json.dumps(owners, ensure_ascii=True, separators=(",", ":")))
    for row in owners:
        count = min(remaining, 3999)
        row["file"] = "a" * count
        remaining -= count
    assert remaining == 0
    assert valid_record(observation(owners))
    owners[-1]["file"] += "a"
    assert valid_record(observation(owners)) == {}


def test_deep_inspection_does_not_invoke_descriptors_or_imports(monkeypatch):
    value = hierarchy(monkeypatch, 40)
    seen = []
    type(value).__getattr__ = lambda self, name: seen.append(name)
    type(value).__getattribute__ = lambda self, name: seen.append(name)
    before = set(sys.modules)
    assert len(receiver_owners(value)) == 40
    assert static_namespace(value)[-1] is True
    assert seen == []
    assert set(sys.modules) == before

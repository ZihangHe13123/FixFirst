"""Owned shopping-cart fixtures: executable test failures, recovery, and independent labels."""

import json
from pathlib import Path
import sys

from .cases import write, source_fingerprint
from .models import now
from .report import render
from .service import create_session, scan, mark_fixed

VARIANTS = ("assertion", "setup", "teardown", "runtime_import", "mixed", "runtime_config")
HEALTHY = (
    "def discount(total):\n    return total * 0.9\n\ndef tax(total):\n    return total * 0.1\n"
)
FIXTURE = "import pytest\n\n@pytest.fixture\ndef ready():\n    return True\n"
TESTS = "import cart\n\ndef test_discount():\n    assert cart.discount(100) == 90\n\ndef test_tax():\n    assert cart.tax(100) == 10\n\ndef test_fixture(ready):\n    assert ready\n"


def create_project(root: Path):
    if root.exists():
        raise ValueError(f"案例目录已存在，不覆盖：{root}")
    root.mkdir(parents=True)
    write(root / "cart.py", HEALTHY)
    write(root / "conftest.py", FIXTURE)
    write(root / "test_cart.py", TESTS)
    write(root / "LICENSE", "Generated fixture code: CC0-1.0.\n")


def set_variant(root, variant):
    cart, fixture = HEALTHY, FIXTURE
    if variant in ("assertion", "mixed"):
        cart = cart.replace("total * 0.9", "total * 0.7")
    if variant == "mixed":
        cart = cart.replace("total * 0.1", "total * 0.2")
    if variant == "setup":
        fixture = FIXTURE.replace("return True", "raise RuntimeError('fixture preparation failed')")
    if variant == "teardown":
        fixture = FIXTURE.replace(
            "return True", "yield True\n    raise RuntimeError('fixture cleanup failed')"
        )
    if variant == "runtime_import":
        cart = cart.replace(
            "return total", "import fixfirst_fixture_missing_package\n    return total"
        )
    if variant == "runtime_config":
        cart = cart.replace(
            "return total * 0.9", "raise RuntimeError('Missing configuration: SHIPPING_REGION')"
        )
    write(root / "cart.py", cart)
    write(root / "conftest.py", fixture)


def capture(root, name):
    session = create_session(root, sys.executable, name, goal="pass_tests")
    scan(session, ["pytest", "pytest_run"])
    return session


def require_healthy(session):
    if session.goal_status != "achieved" or not all(r.verified_pass for r in session.runs[-2:]):
        raise ValueError("执行案例基线或恢复未通过，请查看原始记录")


def build_dataset(output: Path, projects=5):
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("数据目录已存在，请选择新目录")
    output.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "created_at": now(),
        "origin": "controlled_execution_injection",
        "license": "CC0-1.0 for generated fixture code",
        "cases": [],
        "limitations": "购物车模板的受控执行故障；五个项目变体结构相近，不是自然开源故障。",
    }
    rows = []
    try:
        for p in range(1, projects + 1):
            project_id = f"execution-project-{p}"
            for variant in VARIANTS:
                case_id = f"x{p}-{variant}"
                directory, root = output / case_id, output / case_id / "project"
                create_project(root)
                # Keep a distinct project marker without pretending templates are independent.
                write(root / "PROJECT.txt", project_id + "\n")
                baseline = capture(root, case_id)
                write(directory / "baseline.json", baseline.model_dump_json(indent=2))
                require_healthy(baseline)
                before = source_fingerprint(root)
                set_variant(root, variant)
                session = capture(root, case_id)
                write(directory / "input.json", session.model_dump_json(indent=2))
                expected = {
                    "assertion": "test_assertion",
                    "mixed": "test_assertion",
                    "setup": "test_runtime_error",
                    "teardown": "test_runtime_error",
                    "runtime_import": "import_failure",
                    "runtime_config": "explicit_config_missing",
                }[variant]
                if session.goal_status != "blocked" or {i.kind for i in session.issues} != {
                    expected
                }:
                    raise ValueError(f"{case_id} 未捕获预设失败")
                # Group truth comes from the injected faults: imports share one missing module;
                # independent discount/tax defects have different node-level groups.
                event_groups = {
                    e.event_id: ("missing-package" if variant == "runtime_import" else e.location)
                    for e in session.events
                }
                labels = [{"issue_id": i.issue_id, "label": expected} for i in session.issues]
                truth = {
                    "case_id": case_id,
                    "variant": variant,
                    "labels": labels,
                    "expected_kinds": [expected],
                    "event_groups": event_groups,
                    "repair": "Restore owned cart.py and conftest.py from HEALTHY/FIXTURE",
                }
                write(directory / "truth.json", json.dumps(truth, ensure_ascii=False, indent=2))
                rows += [
                    {
                        "project_id": project_id,
                        "case_id": case_id,
                        "label": expected,
                        "issue": i.model_dump(),
                    }
                    for i in session.issues
                ]
                write(root / "cart.py", HEALTHY)
                write(root / "conftest.py", FIXTURE)
                scan(session, ["pytest", "pytest_run"])
                write(directory / "restored.json", session.model_dump_json(indent=2))
                require_healthy(session)
                manifest["cases"].append(
                    {
                        "case_id": case_id,
                        "project_id": project_id,
                        "variant": variant,
                        "path": case_id,
                        "baseline_pass": True,
                        "restored_pass": True,
                        "baseline_sha256": before,
                        "restored_sha256": source_fingerprint(root),
                        "raw_runs": len(baseline.runs) + len(session.runs),
                    }
                )
                print(f"  {case_id}: 收集成功 → 执行失败 → 修复验证通过", flush=True)
    finally:
        write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        write(output / "labeled_issues.json", json.dumps(rows, ensure_ascii=False, indent=2))
    return output / "manifest.json"


def demo(output: Path, store):
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("演示目录已存在，请选择新的输出目录")
    root = output / "project"
    create_project(root)
    session = capture(root, "小王的购物车：测试能收集，但运行失败")
    require_healthy(session)
    render(session, store.root, output / "00-healthy.html")
    set_variant(root, "mixed")
    scan(session, ["pytest", "pytest_run"])
    assert len(session.issues) == 2 and session.goal_status == "blocked"
    render(session, store.root, output / "01-two-failures.html")
    write(root / "cart.py", HEALTHY.replace("total * 0.1", "total * 0.2"))
    issue = next(i for i in session.issues if "test_cart.py::test_discount" in i.targets)
    mark_fixed(session, issue.issue_id)
    scan(session, ["pytest_run"], targets=["test_cart.py::test_discount"])
    assert sum(i.status == "resolved" for i in session.issues) == 1
    assert session.goal_status == "unknown"
    render(session, store.root, output / "02-selected-pass.html")
    write(
        root / "test_cart.py",
        "import pytest\n"
        + TESTS.replace(
            "def test_tax", "@pytest.mark.skip(reason='temporarily hidden')\ndef test_tax"
        ),
    )
    scan(session, ["pytest_run"])
    assert session.goal_status == "unknown"
    render(session, store.root, output / "03-skipped-is-not-fixed.html")
    write(root / "cart.py", HEALTHY)
    write(root / "test_cart.py", TESTS)
    scan(session, ["pytest_run"])
    assert session.goal_status == "achieved" and all(i.status == "resolved" for i in session.issues)
    final = render(session, store.root, output / "04-restored.html")
    with store.lock(session.session_id):
        store.save(session)
        render(session, store.root, store.directory(session.session_id) / "report.html")
    return final

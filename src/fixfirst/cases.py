"""Creates and runs only new, explicitly named fixture projects; never user code fixes."""

import hashlib
import json
from pathlib import Path
import sys
import sysconfig
import venv

from .models import now
from .report import render
from .service import create_session, scan, mark_fixed
from .storage import Store

CHECKS = ["environment", "pip_check", "pytest", "ruff"]
VARIANTS = ["missing_module", "missing_config", "style", "code_check", "dependency", "mixed"]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_project(root: Path, project_id: str):
    if root.exists():
        raise ValueError(f"案例目录已存在，不覆盖：{root}")
    root.mkdir(parents=True)
    write(root / "helper.py", f"def greet():\n    return '{project_id}'\n")
    write(root / "app.py", "from helper import greet\n\ndef result():\n    return greet()\n")
    write(root / "settings.json", '{"DEMO_SETTING": "example"}\n')
    write(
        root / "test_alpha.py",
        f"from app import result\n\ndef test_alpha():\n    assert result() == '{project_id}'\n",
    )
    write(
        root / "test_beta.py",
        "from app import result\n\ndef test_beta():\n    assert isinstance(result(), str)\n",
    )
    write(root / "pyproject.toml", '[tool.ruff.lint]\nselect = ["E501", "F821"]\n')
    write(
        root / "LICENSE",
        "This generated fixture is dedicated to the public domain under CC0-1.0.\n",
    )


def inject(root: Path, variant: str):
    if variant in ("missing_module", "mixed"):
        (root / "helper.py").rename(root / "helper.py.disabled")
    if variant == "missing_config":
        original = (root / "app.py").read_text()
        write(root / "app.py.original", original)
        write(
            root / "app.py",
            "from pathlib import Path\n"
            "if not Path(__file__).with_name('settings.json').exists():\n"
            "    raise RuntimeError('Missing configuration: DEMO_SETTING')\n" + original,
        )
        (root / "settings.json").rename(root / "settings.json.disabled")
    if variant in ("style", "mixed"):
        write(root / "notes.py", "message = '" + "long example " * 14 + "'\n")
    if variant == "code_check":
        write(root / "notes.py", "def example():\n    return undefined_example_name\n")
    if variant == "dependency":
        site = next((root.parent / "runtime" / "lib").glob("python*/site-packages"))
        write(
            site / "fixfirst_fixture_dependency-1.0.dist-info" / "METADATA",
            "Metadata-Version: 2.1\nName: fixfirst-fixture-dependency\nVersion: 1.0\nRequires-Dist: packaging<0\n",
        )


def repair_fixture(root: Path, variant: str):
    """Oracle repairs used by dataset/demo only; the product never calls this on sessions."""
    if variant in ("missing_module", "mixed"):
        (root / "helper.py.disabled").rename(root / "helper.py")
    if variant == "missing_config":
        (root / "settings.json.disabled").rename(root / "settings.json")
        (root / "app.py").write_text((root / "app.py.original").read_text())
    if variant in ("style", "mixed", "code_check"):
        (root / "notes.py").unlink()
    if variant == "dependency":
        site = next((root.parent / "runtime" / "lib").glob("python*/site-packages"))
        metadata = site / "fixfirst_fixture_dependency-1.0.dist-info" / "METADATA"
        metadata.unlink()
        metadata.parent.rmdir()


def require_pass(session):
    failures = [r for r in session.runs[-4:] if not r.verified_pass]
    if failures:
        detail = "\n".join(
            f"{r.tool}: {r.status}/{r.exit_code}\n{r.stdout[-1200:]}\n{r.stderr[-600:]}"
            for r in failures
        )
        raise ValueError("案例基线/恢复检查未通过：\n" + detail)


def source_fingerprint(root):
    value = "".join(p.name + p.read_text() for p in sorted(root.glob("*.py")))
    return hashlib.sha256(value.encode()).hexdigest()


def build_dataset(output: Path, projects=5):
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("数据目录已存在，请指定新的 --output；保留原始实验")
    output.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "created_at": now(),
        "origin": "controlled_injection",
        "license": "CC0-1.0 for generated fixture code",
        "cases": [],
        "limitations": "五个生成项目共用相近模板，不是五个独立真实开源项目；只验证受控流程。",
    }
    rows = []
    try:
        for p in range(projects):
            project_id = f"fixture-project-{p + 1}"
            for variant in VARIANTS:
                case_id = f"p{p + 1}-{variant}"
                case_root = output / case_id
                root = case_root / "project"
                create_project(root, project_id)
                python = sys.executable
                if variant == "dependency":
                    runtime = case_root / "runtime"
                    venv.EnvBuilder(with_pip=True).create(runtime)
                    site = next((runtime / "lib").glob("python*/site-packages"))
                    # Read tool dependencies from the app env, but inject the fixture metadata
                    # only into this disposable environment's own site-packages.
                    write(site / "fixfirst_tools.pth", sysconfig.get_path("purelib") + "\n")
                    python = str(runtime / "bin" / "python")
                session = create_session(
                    root,
                    python,
                    case_id,
                    goal="check_style" if variant in ("style", "code_check") else "collect_tests",
                )
                scan(session, CHECKS)
                require_pass(session)
                write(case_root / "baseline.json", session.model_dump_json(indent=2))
                before = source_fingerprint(root)
                inject(root, variant)
                failure = create_session(root, python, case_id, goal=session.goal)
                scan(failure, CHECKS)
                observed = [i for i in failure.issues if i.status == "open"]
                expected = {
                    "missing_module": {"import_failure"},
                    "missing_config": {"explicit_config_missing"},
                    "style": {"style_issue"},
                    "code_check": {"code_check"},
                    "dependency": {"dependency_conflict"},
                    "mixed": {"import_failure", "style_issue"},
                }[variant]
                if not expected.issubset({i.kind for i in observed}):
                    write(case_root / "failed_capture.json", failure.model_dump_json(indent=2))
                    raise ValueError(
                        f"{case_id} 没有观察到预设故障，实际 {[i.kind for i in observed]}"
                    )
                write(case_root / "input.json", failure.model_dump_json(indent=2))
                # Labels are generated from the known injected scenario, not the model prediction.
                labels = []
                for issue in observed:
                    label = (
                        "other_unknown"
                        if variant == "code_check"
                        else (
                            "style_issue"
                            if variant == "mixed" and issue.tool == "ruff"
                            else "import_failure"
                            if variant in ("mixed", "missing_module")
                            else {
                                "missing_config": "explicit_config_missing",
                                "style": "style_issue",
                                "dependency": "dependency_conflict",
                            }[variant]
                        )
                    )
                    labels.append({"issue_id": issue.issue_id, "label": label})
                    rows.append(
                        {
                            "project_id": project_id,
                            "case_id": case_id,
                            "label": label,
                            "issue": issue.model_dump(),
                        }
                    )
                truth = {
                    "case_id": case_id,
                    "variant": variant,
                    "labels": labels,
                    "expected_kinds": sorted(expected),
                    "repair": "repair_fixture for this controlled fixture only",
                    "expected_groups": len(expected),
                }
                write(case_root / "truth.json", json.dumps(truth, ensure_ascii=False, indent=2))
                repair_fixture(root, variant)
                scan(failure, CHECKS)
                require_pass(failure)
                write(case_root / "restored.json", failure.model_dump_json(indent=2))
                manifest["cases"].append(
                    {
                        "case_id": case_id,
                        "project_id": project_id,
                        "variant": variant,
                        "baseline_sha256": before,
                        "restored_sha256": source_fingerprint(root),
                        "path": case_id,
                        "baseline_pass": True,
                        "restored_pass": True,
                        "raw_runs": len(failure.runs) + len(session.runs),
                    }
                )
                print(f"  {case_id}: 正常 → 故障 → 恢复 已实际验证", flush=True)
    finally:
        write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        write(output / "labeled_issues.json", json.dumps(rows, ensure_ascii=False, indent=2))
    return output / "manifest.json"


def demo(output: Path, store: Store):
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("演示目录已存在，请指定新目录，避免覆盖上次演示")
    root = output / "project"
    create_project(root, "FixFirst 演示项目")
    session = create_session(root, sys.executable, "小王接手的 Python 项目")
    scan(session, CHECKS)
    require_pass(session)
    render(session, store.root, output / "00-healthy.html")
    inject(root, "mixed")
    scan(session, CHECKS)
    render(session, store.root, output / "01-failure.html")
    failures = [i for i in session.issues if i.tool == "pytest" and i.status == "open"]
    assert failures, "必须观察到真实导入失败"
    (root / "notes.py").write_text("message = 'short example'\n")
    scan(session, ["ruff"])
    assert all(
        i.status != "resolved"
        for i in session.issues
        if i.issue_id in {f.issue_id for f in failures}
    )
    render(session, store.root, output / "02-partial-check.html")
    (root / "helper.py.disabled").rename(root / "helper.py")
    for issue in failures:
        mark_fixed(session, issue.issue_id)
    scan(session, ["pytest"])
    assert session.goal_status == "achieved"
    assert all(
        i.status == "resolved"
        for i in session.issues
        if i.tool == "pytest" and i.kind == "import_failure"
    )
    with store.lock(session.session_id):
        store.save(session)
        render(session, store.root, store.directory(session.session_id) / "report.html")
    final = render(session, store.root, output / "03-restored.html")
    # Frozen story pages remain reviewable after later changes to the live session.
    write(
        output / "README.md",
        "# 真实运行演示\n\n00 正常 → 01 导入失败与风格问题 → 02 只修风格并检查 → 03 恢复模块并验证测试收集。\n\n"
        "演示脚本只修改它自己创建的项目；产品的 scan/run 不修改用户源码。所有 JSON 是此次实际运行记录。\n\n"
        f"排查编号：{session.session_id}\n",
    )
    return final

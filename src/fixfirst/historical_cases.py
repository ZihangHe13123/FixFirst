"""Offline replay of small, source-attributed upstream regressions in owned virtualenvs."""

import hashlib
import json
from pathlib import Path
import sys

from .models import now
from .report import public_data, render
from .runner import execute
from .service import create_session, scan
from .storage import Store, atomic_write

# These are locally authored minimal regression tests for published upstream defects.
# The tested packages are unmodified official wheels, accompanied by their own licenses.
CASES = [
    {
        "id": "packaging-prerelease",
        "package": "packaging",
        "broken": "24.1",
        "fixed": "24.2",
        "title": "Pre-release wrongly excluded by a specifier",
        "kind": "test_assertion",
        "source": "https://github.com/pypa/packaging/issues/788",
        "fix": "https://github.com/pypa/packaging/pull/794",
        "commit": "cf2cbe2aec28f87c6228a6fb136c27931c9af407",
        "test": """from packaging.specifiers import Specifier


def test_prerelease_is_accepted():
    requirement = Specifier("<3.0.0a8")
    actual = requirement.contains("3.0.0a7")
    assert actual, "An earlier prerelease should match the exclusive prerelease bound"
""",
    },
    {
        "id": "packaging-full-version",
        "package": "packaging",
        "broken": "24.1",
        "fixed": "24.2",
        "title": "Untagged Python version breaks marker evaluation",
        "kind": "test_runtime_error",
        "source": "https://github.com/pypa/packaging/issues/678",
        "fix": "https://github.com/pypa/packaging/pull/825",
        "commit": "c385b58c4d0e4d66f5c8273ebb155801c92aadf3",
        "test": """from packaging.markers import Marker


def test_untagged_python_version():
    condition = Marker("python_full_version < '3.12'")
    assert condition.evaluate({"python_full_version": "3.11.1+"})
""",
    },
    {
        "id": "click-empty-default",
        "package": "click",
        "broken": "8.1.7",
        "fixed": "8.1.8",
        "title": "Command help omits an empty-string default",
        "kind": "test_assertion",
        "source": "https://github.com/pallets/click/issues/2500",
        "fix": "https://github.com/pallets/click/pull/2724",
        "commit": "d3e3852eba45a6f7ce0ae5e02ca49106e228add6",
        "test": """import click
from click.testing import CliRunner


def test_help_shows_empty_default():
    @click.command()
    @click.option("--label", default="", show_default=True)
    def command(label):
        click.echo(label)

    result = CliRunner().invoke(command, ["--help"])
    assert result.exit_code == 0
    assert '[default: ""]' in result.output
""",
    },
    {
        "id": "click-default-map",
        "package": "click",
        "broken": "8.1.7",
        "fixed": "8.1.8",
        "title": "Command help shows the wrong default from default_map",
        "kind": "test_assertion",
        "source": "https://github.com/pallets/click/issues/2632",
        "fix": "https://github.com/pallets/click/pull/2730",
        "commit": "bc16dbf788861266177661b576291a1b264fb5de",
        "test": """import click
from click.testing import CliRunner


def test_help_uses_default_map():
    @click.command()
    @click.option("--long/--short", show_default=True)
    def command(long):
        click.echo(long)

    result = CliRunner().invoke(command, ["--help"], default_map={"long": True})
    assert result.exit_code == 0
    assert "[default: long]" in result.output
""",
    },
]


def verify_assets(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    files = {}
    for row in manifest["assets"]:
        path = (directory / row["filename"]).resolve()
        if not path.is_relative_to(directory) or path.suffix != ".whl":
            raise ValueError("Wheel is outside the asset directory")
        if path.stat().st_size != row["bytes"]:
            raise ValueError("Wheel size mismatch: " + row["filename"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Wheel SHA256 mismatch: " + row["filename"])
        if not row.get("licenses") or any(not (directory / p).is_file() for p in row["licenses"]):
            raise ValueError("Wheel is missing its licence file")
        files[(row["package"], row["version"])] = path
    return files


def replay(output: Path, assets: Path, cases=None) -> Path:
    """No network and no changes outside the newly created output tree."""
    files = verify_assets(assets)
    output = output.resolve()
    if output.exists():
        raise ValueError("The replay output must be a new directory so earlier evidence is kept")
    output.mkdir(parents=True)
    manifest = {"created_at": now(), "python": sys.version, "cases": [], "all_reproduced": False}
    manifest_path = output / "results.json"
    store = Store(output / "store")

    def save():
        atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    save()
    for case in CASES if cases is None else cases:
        result = {k: v for k, v in case.items() if k != "test"}
        result["status"] = "incomplete"
        manifest["cases"].append(result)
        directory = output / case["id"]
        project = directory / "project"
        project.mkdir(parents=True)
        test = project / "test_regression.py"
        test.write_text(case["test"], encoding="utf-8")
        (project / "requirements.txt").write_text(
            case.get("requirement", case["package"] + ">=0") + "\n"
        )
        (project / "pytest.ini").write_text("[pytest]\ntestpaths = .\n")
        result["test_sha256"] = hashlib.sha256(test.read_bytes()).hexdigest()
        result["reproducer_origin"] = (
            "Locally authored minimal test based on the linked upstream defect; not the entire upstream suite"
        )
        python = str(directory / ".venv" / "bin" / "python")
        commands = []

        def command(argv, label):
            run = execute(argv, str(project), "pip_install", "owned:replay", python, timeout=60)
            record = json.dumps(run.model_dump(), ensure_ascii=False)
            for private, alias in ((str(directory), "<case>"), (str(assets.resolve()), "<assets>"),
                                   (sys.prefix, "<fixfirst-env>"), (str(Path.home()), "<home>")):
                record = record.replace(private, alias)
            commands.append(json.loads(record))
            atomic_write(
                directory / "setup.json", json.dumps(commands, ensure_ascii=False, indent=2)
            )
            if run.exit_code != 0 or run.status != "completed":
                raise ValueError(f"{label} did not complete; see setup.json")

        try:
            command([sys.executable, "-m", "venv", str(directory / ".venv")], "Create an isolated environment")
            dependencies = [
                ("pytest", "8.3.5"),
                ("packaging", "24.2"),
                ("pluggy", "1.5.0"),
                ("iniconfig", "2.1.0"),
            ]
            if sys.version_info < (3, 11):
                dependencies += [("exceptiongroup", "1.2.2"), ("tomli", "2.2.1")]
            command(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    *[str(files[k]) for k in dependencies],
                ],
                "Install test tools offline",
            )
            command(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    str(files[(case["package"], case["broken"])]),
                ],
                "Install the broken version",
            )
            session = create_session(project, python, case["title"], goal="pass_tests")
            scan(session, ["environment", "pip_check", "pytest_run", "project"])
            broken_run = next(r for r in session.runs if r.tool == "pytest_run")
            failed = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
            result["broken_exit_code"] = broken_run.exit_code
            result["broken_nodes"] = broken_run.test_summary
            result["observed_kinds"] = sorted({i.kind for i in failed})
            result["broken_version_observed"] = next(
                (
                    p["version"]
                    for p in session.environment["packages"]
                    if p["name"].lower() == case["package"]
                ),
                None,
            )
            result["pip_check_passed_before_fix"] = next(
                r for r in session.runs if r.tool == "pip_check"
            ).verified_pass
            render(session, store.root, directory / "01-broken.html", public=True)
            atomic_write(
                directory / "broken.json",
                json.dumps(public_data(session), ensure_ascii=False, indent=2),
            )
            command(
                [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    str(files[(case["package"], case["fixed"])]),
                ],
                "Install the upstream fixed version",
            )
            scan(session, ["environment", "pip_check", "pytest_run", "project"])
            fixed_run = next(r for r in reversed(session.runs) if r.tool == "pytest_run")
            result["fixed_exit_code"] = fixed_run.exit_code
            result["fixed_nodes"] = fixed_run.test_summary
            result["fixed_version_observed"] = next(
                (
                    p["version"]
                    for p in session.environment["packages"]
                    if p["name"].lower() == case["package"]
                ),
                None,
            )
            result["test_unchanged"] = (
                hashlib.sha256(test.read_bytes()).hexdigest() == result["test_sha256"]
            )
            result["issues_closed"] = all(
                next(i for i in session.issues if i.issue_id == old.issue_id).status == "resolved"
                for old in failed
            )
            result["goal_status"] = session.goal_status
            verified = (
                broken_run.exit_code == 1
                and broken_run.coverage_complete
                and failed
                and case["kind"] in result["observed_kinds"]
                and fixed_run.verified_pass
                and result["test_unchanged"]
                and result["issues_closed"]
                and result["broken_version_observed"] == case["broken"]
                and result["fixed_version_observed"] == case["fixed"]
            )
            result["status"] = "reproduced" if verified else "not_reproduced"
            store.save(session)
            render(session, store.root, directory / "02-fixed.html", public=True)
        except (OSError, ValueError, KeyError) as exc:
            result["error"] = str(exc)
        save()
        print(f"{case['id']}: {result['status']}", flush=True)
    manifest["all_reproduced"] = all(r["status"] == "reproduced" for r in manifest["cases"])
    save()
    lines = [
        "# Upstream regression replay",
        "",
        "Each case switches official wheels in a new isolated environment while the test source stays unchanged. Installation is offline; sources and SHA256 hashes are in assets/manifest.json.",
        "",
        "| Case | Version change | Exit code broken → fixed | Result |",
        "|---|---|---|---|",
    ]
    for row in manifest["cases"]:
        lines.append(
            f"| [{row['title']}]({row['source']}) | {row['broken']} → {row['fixed']} | {row.get('broken_exit_code', 'not run')} → {row.get('fixed_exit_code', 'not run')} | {row['status']} |"
        )
    lines += [
        "",
        "These are minimal reproductions of specific upstream defects. They do not represent independent projects, the distribution of faults or developer time. The replay knows the fixed version; the product never guesses versions for other errors. No model was trained on these cases.",
    ]
    report = output / "REPORT.md"
    atomic_write(report, "\n".join(lines) + "\n")
    return report

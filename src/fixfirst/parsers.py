"""Conservative per-tool parsers. Unknown nonzero results remain visible."""

import json
import re

from .models import Event, Run
from .test_results import summarize_tests

IMPORT = re.compile(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]")
EXCEPTION = re.compile(r"\b([A-Za-z_]\w*(?:Error|Exception)):\s*(.*)")
CONFIG = re.compile(
    r"(?:Missing (?:required )?(?:configuration|environment variable|config)|"
    r"(?:configuration|environment variable) (?:missing|not set))[:\s]+['\"]?([A-Z][A-Z0-9_]+)",
    re.I,
)
STYLE_PREFIXES = ("E1", "E2", "E3", "E5", "W", "Q", "COM", "I", "D")


def event(
    run, message, *, stage, kind, component="", location="", line=1, code="", stream="stdout"
):
    return Event(
        run_id=run.run_id,
        tool=run.tool,
        stage=stage,
        kind=kind,
        message=message.strip(),
        component=component,
        location=location,
        line=line,
        code=code,
        evidence_refs=[f"{run.run_id}:{stream}:{line}"],
    )


def exception_event(run, text, location="", stage="collect", line=1, stream="stdout"):
    match = IMPORT.search(text)
    if match:
        return event(
            run,
            match.group(0),
            stage=stage,
            kind="import_failure",
            component=match.group(1),
            location=location,
            line=line,
            stream=stream,
        )
    match = CONFIG.search(text)
    if match:
        return event(
            run,
            match.group(0),
            stage=stage,
            kind="explicit_config_missing",
            component=match.group(1),
            location=location,
            line=line,
            stream=stream,
        )
    matches = list(EXCEPTION.finditer(text))
    if matches:
        match = matches[-1]
        return event(
            run,
            match.group(0),
            stage=stage,
            kind=(
                "import_failure"
                if match.group(1) == "ImportError"
                else "test_assertion"
                if stage == "call" and match.group(1) == "AssertionError"
                else "test_runtime_error"
                if stage in ("call", "setup", "teardown")
                else "other_unknown"
            ),
            location=location,
            line=line,
            code=match.group(1),
            stream=stream,
        )
    return event(
        run,
        text[-2000:] or "未知测试失败",
        stage=stage,
        kind="test_runtime_error" if stage in ("call", "setup", "teardown") else "other_unknown",
        location=location,
        line=line,
        stream=stream,
    )


def parse(run: Run) -> list[Event]:
    run.verified_pass = False
    run.coverage_complete = False
    run.passed_nodes = []
    run.test_summary = {}
    if run.status != "completed" or run.truncated:
        return [
            event(
                run,
                f"检查未完成：{run.status}。{run.stderr[:500]}",
                stage="tool",
                kind="tool_failure",
                stream="stderr",
            )
        ]
    text = run.stdout + "\n" + run.stderr
    missing_tool = re.search(r"No module named ['\"]?(pytest|ruff|pip)\b", text)
    if missing_tool and run.tool != "pip_install":
        # A project's own import failure is not necessarily a missing runner.
        if not run.records and ("-m" in run.argv or run.source == "imported"):
            return [
                event(
                    run,
                    f"目标环境中未能启动 {missing_tool.group(1)}：{text.strip()[:500]}",
                    stage="tool",
                    kind="tool_failure",
                    component=missing_tool.group(1),
                )
            ]
    if run.tool == "environment":
        try:
            payload = json.loads(run.stdout)
            valid = isinstance(payload, dict) and isinstance(payload.get("packages"), list)
            run.verified_pass = run.exit_code == 0 and valid
            run.coverage_complete = run.verified_pass
        except ValueError:
            pass
        return (
            []
            if run.verified_pass
            else [event(run, "环境快照未成功取得", stage="tool", kind="tool_failure")]
        )
    if run.tool == "ruff":
        try:
            rows = json.loads(run.stdout)
            if not isinstance(rows, list) or run.exit_code not in (0, 1):
                raise ValueError()
            events = []
            for index, row in enumerate(rows):
                if not isinstance(row, dict) or not all(
                    k in row for k in ("message", "location", "filename")
                ):
                    raise ValueError()
                code = row.get("code") or "invalid-syntax"
                kind = "style_issue" if code.startswith(STYLE_PREFIXES) else "code_check"
                events.append(
                    event(
                        run,
                        row["message"],
                        stage="lint",
                        kind=kind,
                        component=code,
                        code=code,
                        location=row["filename"],
                        line=row["location"].get("row", 1),
                    )
                )
                events[-1].evidence_refs = [f"{run.run_id}:json:{index}"]
            run.coverage_complete = True
            run.verified_pass = run.exit_code == 0 and not events
            if not events and run.exit_code != 0:
                raise ValueError()
            return events
        except (ValueError, KeyError, TypeError, AttributeError):
            return [
                event(
                    run,
                    "Ruff 输出无法识别或工具失败：" + text[:1000],
                    stage="tool",
                    kind="tool_failure",
                )
            ]
    if run.tool == "pip_check":
        run.verified_pass = run.exit_code == 0 and "No broken requirements found" in text
        run.coverage_complete = run.verified_pass
        if run.verified_pass:
            return []
        results = []
        for stream in ("stdout", "stderr"):
            for line, value in enumerate(getattr(run, stream).splitlines(), 1):
                if re.search(
                    r"has requirement .+but you have|requires .+(?:not installed|not compatible)",
                    value,
                ):
                    component = value.split()[0]
                    results.append(
                        event(
                            run,
                            value,
                            stage="dependency",
                            kind="dependency_conflict",
                            component=component,
                            line=line,
                            stream=stream,
                        )
                    )
        return results or [
            event(run, text[:1000] or "依赖检查结果未知", stage="tool", kind="other_unknown")
        ]
    if run.tool == "pip_install":
        results = []
        for stream in ("stdout", "stderr"):
            for line, value in enumerate(getattr(run, stream).splitlines(), 1):
                if "ERROR" not in value and not re.search(
                    r"ResolutionImpossible|Could not find|Failed building", value
                ):
                    continue
                conflict = bool(
                    re.search(
                        r"ResolutionImpossible|conflicting dependencies|dependency conflict",
                        value,
                        re.I,
                    )
                )
                results.append(
                    event(
                        run,
                        value,
                        stage="install",
                        kind="dependency_conflict" if conflict else "install_failure",
                        line=line,
                        stream=stream,
                    )
                )
        # Installation input is historical evidence; an empty log does not prove installation.
        return results or [
            event(
                run,
                "安装日志没有可识别的失败；不据此证明安装成功",
                stage="install",
                kind="other_unknown",
            )
        ]
    if run.tool in ("pytest", "pytest_run"):
        failures = [r for r in run.records if r.get("type") == "failure"]
        finishes = [r for r in run.records if r.get("type") == "finish"]
        if run.records:
            result = []
            for index, record in enumerate(run.records):
                if record.get("type") == "failure":
                    item = exception_event(
                        run,
                        str(record.get("message", "")),
                        str(record.get("nodeid", "")),
                        str(record.get("stage", "unknown")),
                    )
                    item.evidence_refs = [f"{run.run_id}:probe:{index}"]
                    exception = next(
                        (
                            r
                            for r in run.records
                            if r.get("type") == "exception"
                            and r.get("nodeid") == record.get("nodeid")
                            and r.get("stage") == record.get("stage")
                        ),
                        {},
                    )
                    if exception.get("exception_type") == "AssertionError" and item.stage == "call":
                        item.kind, item.code = "test_assertion", "AssertionError"
                    result.append(item)
            run.verified_pass = bool(
                finishes
                and finishes[-1].get("collected", 0) > 0
                and run.exit_code == 0
                and not failures
                and finishes[-1].get("exit_code") == 0
                and not finishes[-1].get("records_dropped", False)
            )
            run.coverage_complete = run.verified_pass
            if run.tool == "pytest_run":
                run.verified_pass = False
                run.coverage_complete = False
                summarize_tests(run)
            if result:
                return result
            if run.verified_pass:
                return []
            if run.tool == "pytest_run" and run.coverage_complete and run.exit_code == 0:
                return [
                    event(
                        run,
                        "测试未提供实际通过的节点；全部跳过或标记为预期失败不等于修复",
                        stage="verification",
                        kind="other_unknown",
                    )
                ]
        else:
            # Text imports retain context but cannot prove collection coverage.
            result = []
            location = ""
            for stream in ("stdout", "stderr"):
                for line, value in enumerate(getattr(run, stream).splitlines(), 1):
                    context = re.search(
                        r"(?:ERROR collecting|ERROR|FAILED)\s+([^\s]+\.py[^\s]*)", value
                    )
                    if context:
                        location = context.group(1)
                    if IMPORT.search(value) or CONFIG.search(value) or EXCEPTION.search(value):
                        result.append(
                            exception_event(run, value, location, "unknown", line, stream)
                        )
            if result:
                return result
        descriptions = {
            2: "收集错误或中断",
            3: "pytest 内部错误",
            4: "pytest 使用错误",
            5: "没有收集到测试",
        }
        message = descriptions.get(
            run.exit_code, "缺少可验证的测试完成记录；可能全部跳过或执行未覆盖"
        )
        return [event(run, message + "；请查看原始输出", stage="tool", kind="tool_failure")]
    raise ValueError("不支持的来源")

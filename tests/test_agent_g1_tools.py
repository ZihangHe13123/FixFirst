"""G1 file tools and measurement with temporary files and fake MCP, never a language model."""

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/agent_baseline"))
import agent_file_tools as aft  # noqa: E402
import agent_pilot as ap  # noqa: E402
import compare_arms as ca  # noqa: E402
import hard_instances as hi  # noqa: E402
import isolation as iso  # noqa: E402

FILES_SUPPORTED = os.open in os.supports_dir_fd
file_test = pytest.mark.skipif(not FILES_SUPPORTED, reason="macOS/Linux directory-relative file APIs required")


@file_test
@pytest.mark.parametrize("text", ["", "one\ntwo\nthree", "一🙂\r\n二é\r\n三\r\n", "one\rtwo\rthree"])
def test_line_pages_reconstruct_original_newlines_and_unicode(tmp_path, text):
    (tmp_path / "code.py").write_bytes(text.encode())
    start, pieces = 1, []
    while True:
        page = aft.read_page(tmp_path, {"path": "code.py", "start_line": start, "line_count": 1})
        assert not page["omitted_chars"] and page["start_line"] == start
        pieces.append(page["text"])
        if page["eof"]:
            break
        start = page["next_line"]
    assert "".join(pieces) == text


@file_test
def test_long_line_keeps_head_tail_and_character_pages_can_recover_its_middle(tmp_path):
    text = "START" + "🙂" * 14000 + "END\r\n"
    (tmp_path / "code.py").write_bytes(text.encode())
    page = aft.read_page(tmp_path, {"path": "code.py", "line_count": 1})
    assert len(page["text"]) == 6000 and page["text"].startswith("START") and page["text"].endswith("END\r\n")
    assert f"[{page['omitted_chars']} characters omitted]" in page["text"]
    offset, pieces = 0, []
    while True:
        page = aft.read_page(tmp_path, {"path": "code.py", "offset": offset, "limit": 997})
        pieces.append(page["text"])
        if page["eof"]:
            break
        offset = page["next_offset"]
    assert "".join(pieces) == text


@file_test
@pytest.mark.parametrize("values", [{"start_line": 0}, {"start_line": True}, {"start_line": 3},
                                     {"line_count": 0}, {"line_count": 1001}, {"line_count": 1.5},
                                     {"start_line": 1, "offset": 0}, {"line_count": 1, "limit": 6}])
def test_bad_line_requests_are_rejected(tmp_path, values):
    (tmp_path / "code.py").write_text("one\n")
    with pytest.raises(ValueError):
        aft.read_page(tmp_path, {"path": "code.py", **values})


@file_test
def test_exact_edit_preserves_unrelated_bytes_newlines_and_mode(tmp_path):
    path = tmp_path / "code.py"
    original = "# unchanged 一🙂\r\ndef answer():\r\n    return 1\r\n# tail\r\n".encode()
    path.write_bytes(original)
    path.chmod(0o751)
    result = aft.exact_edit(tmp_path, {"path": "code.py", "old": "return 1", "new": "return 23"})
    assert result["replacements"] == 1
    assert path.read_bytes() == original.replace(b"return 1", b"return 23")
    assert stat.S_IMODE(path.stat().st_mode) == 0o751
    assert not list(tmp_path.glob(".fixfirst-edit-*"))


@file_test
@pytest.mark.parametrize("values", [{"old": "absent"}, {"old": "x"}, {"old": ""},
                                     {"expected_count": True}, {"expected_count": 0}, {"expected_count": 1001}])
def test_ambiguous_missing_or_invalid_edits_leave_file_unchanged(tmp_path, values):
    path = tmp_path / "code.py"
    path.write_bytes(b"x\r\nx\r\n")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        aft.exact_edit(tmp_path, {"path": "code.py", "old": "x", "new": "new", **values})
    assert path.read_bytes() == before and not list(tmp_path.glob(".fixfirst-edit-*"))


@file_test
def test_replacing_multiple_matches_requires_exact_explicit_count(tmp_path):
    path = tmp_path / "code.py"
    path.write_text("old\nold\nkeep\n")
    result = aft.exact_edit(tmp_path, {"path": "code.py", "old": "old", "new": "new", "expected_count": 2})
    assert result["replacements"] == 2 and path.read_text() == "new\nnew\nkeep\n"


@file_test
@pytest.mark.parametrize("kind", ["parent", "absolute", "symlink_file", "symlink_directory", "directory", "fifo", "invalid_utf8"])
def test_file_boundaries_do_not_read_or_edit_outside_or_special_files(tmp_path, kind):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    path = "code.py"
    if kind == "parent":
        path = "../private.txt"
    elif kind == "absolute":
        path = str(outside)
    elif kind == "symlink_file":
        (project / path).symlink_to(outside)
    elif kind == "symlink_directory":
        (project / "link").symlink_to(tmp_path, target_is_directory=True)
        path = "link/private.txt"
    elif kind == "directory":
        (project / path).mkdir()
    elif kind == "fifo":
        os.mkfifo(project / path)
    else:
        (project / path).write_bytes(b"\xff")
    for action in (lambda: aft.read_page(project, {"path": path}),
                   lambda: aft.exact_edit(project, {"path": path, "old": "private", "new": "wrong"})):
        with pytest.raises((OSError, ValueError)):
            action()
    assert outside.read_text() == "private"


@file_test
def test_concurrent_file_change_prevents_overwriting_other_edit(tmp_path, monkeypatch):
    path = tmp_path / "code.py"
    path.write_text("old")
    original = aft.read_at

    def read(fd, name):
        data, info = original(fd, name)
        path.write_text("another edit")
        return data, info

    monkeypatch.setattr(aft, "read_at", read)
    with pytest.raises(ValueError, match="changed during"):
        aft.exact_edit(tmp_path, {"path": "code.py", "old": "old", "new": "new"})
    assert path.read_text() == "another edit" and not list(tmp_path.glob(".fixfirst-edit-*"))


@file_test
def test_oversize_reads_and_edits_are_rejected_without_a_write(tmp_path, monkeypatch):
    monkeypatch.setattr(aft, "MAX_BYTES", 16)
    path = tmp_path / "code.py"
    path.write_text("old" + "x" * 13)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="would exceed"):
        aft.exact_edit(tmp_path, {"path": "code.py", "old": "old", "new": "bigger"})
    assert path.read_bytes() == before and not list(tmp_path.glob(".fixfirst-edit-*"))
    path.write_text("x" * 17)
    with pytest.raises(ValueError, match="at most"):
        aft.read_page(tmp_path, {"path": "code.py"})


def test_lines_mode_contract_is_explicit_and_legacy_tools_are_unchanged():
    tools = ap.basic_tools("lines")
    read = next(t["function"] for t in tools if t["function"]["name"] == "read_file")
    assert {"start_line", "line_count", "offset", "limit"} <= read["parameters"]["properties"].keys()
    assert "edit_file" in {t["function"]["name"] for t in tools}
    assert "edit_file" not in {t["function"]["name"] for t in ap.basic_tools("paged")}
    assert ap.basic_tools("tail") == ap.BASIC_TOOLS


def test_file_tool_content_binds_h5_and_hard_instance_identities(tmp_path, monkeypatch):
    source = Path(ap.pp.__file__).parent
    for name in set(hi.CODE_FILES) | {"pytest_policy.py"}:
        (tmp_path / name).write_bytes((source / name).read_bytes())
    monkeypatch.setattr(ap.pp, "__file__", str(tmp_path / "pytest_policy.py"))
    monkeypatch.setattr(ap.pp, "PROBE", tmp_path / "_h5_grading_probe.py")
    monkeypatch.setattr(hi, "HERE", tmp_path)
    policy_before, code_before = ap.pp.identity(), hi.code_identity()
    with (tmp_path / "agent_file_tools.py").open("a") as stream:
        stream.write("\n# changed file tool implementation\n")
    assert ap.pp.identity() != policy_before
    assert hi.code_identity()["agent_baseline/agent_file_tools.py"] != code_before["agent_baseline/agent_file_tools.py"]


def test_g1_choices_separate_new_protocols_from_existing_defaults():
    row = {"settings": vars(ap.Settings()), "harness_commit": "same", "network": "off"}
    variants = [{**row, "settings": {**row["settings"], **change}}
                for change in ({}, {"file_read_mode": "lines"}, {"max_no_tool_reminders": 3},
                               {"max_length_continuations": None}, {"max_length_continuations": 0})]
    assert len({ca.protocol(v) for v in variants}) == len(variants)


def test_post_grading_harness_error_invalidates_finish_measurement(tmp_path, monkeypatch):
    def crash(ctx, row, *args):
        row.update(finish_called=True, finish_check_status="passed", finish_fixed=True, fixed=True)
        raise RuntimeError("failure while saving final files")

    monkeypatch.setattr(ap, "run_generated", crash)
    output = tmp_path / "out"
    ap.main(["--model", "stub", "--cases", "pkg-inventory:lm_renamed", "--arms", "baseline", "--out", str(output)])
    row = json.loads((output / "results.jsonl").read_text())
    assert row["grading"] == "not_graded" and row["fixed"] is None
    assert row["finish_check_status"] == "not_checked" and row["finish_fixed"] is None


def test_mcp_calls_record_first_dispatch_and_failures_without_counting_unexecuted_calls(tmp_path):
    stats = {**ap.measurement_defaults(), "file_read_mode": "lines", "fixfirst_calls": 0, "mcp_goal_filled": 0}
    run = SimpleNamespace(real=False, project=tmp_path)
    mcp = SimpleNamespace(names={"diagnose", "check_again", "explain"}, dead=False, facts=True,
                          call=lambda *a: '{}')
    for turn, name in ((2, "diagnose"), (4, "diagnose"), (5, "check_again"), (6, "explain")):
        ap.run_tool(name, {}, run, stats, mcp, iso.Budget(10), turn)
    assert stats["diagnose_calls"] == 2 and stats["diagnose_first_turn"] == 2
    assert stats["check_again_called"] and stats["check_again_first_turn"] == 5
    assert stats["fixfirst_calls"] == 4
    mcp.dead = True
    ap.run_tool("diagnose", {}, run, stats, mcp, iso.Budget(10), 7)
    assert stats["diagnose_calls"] == 2
    mcp.dead = False

    def timeout(*args):
        raise ap.ToolTimeout("deadline")

    mcp.call = timeout
    with pytest.raises(ap.ToolTimeout):
        ap.run_tool("check_again", {}, run, stats, mcp, iso.Budget(10), 8)
    assert stats["check_again_calls"] == 2 and stats["check_again_first_turn"] == 5


def test_scheduled_call_uses_turn_zero_and_head_tail_output(tmp_path):
    text = 'START' + 'x' * 14000 + 'END'
    stats = {**ap.measurement_defaults(), "fixfirst_s": 0, "fixfirst_reports": 0,
             "fixfirst_output_chars": 0, "file_read_mode": "lines"}
    run = SimpleNamespace(project=tmp_path, python=Path(sys.executable))
    mcp = SimpleNamespace(facts=True, call=lambda *a: text)
    output = ap.fixfirst_report("diagnose", run, mcp, iso.Budget(10), stats)
    assert stats["diagnose_first_turn"] == 0 and stats["diagnose_called"]
    assert output.startswith('START') and output.endswith('END') and "characters omitted" in output


def test_finish_verification_distinguishes_failed_missing_and_restored_violation(tmp_path):
    import test_h5_grading as hg
    root, ref = hg.reference(tmp_path)
    run = SimpleNamespace(ctx=SimpleNamespace(grading_policy=ap.pp.H5), baseline=ref["h5_baseline"], project=root)
    row = {"finish_called": True, "fixed": False}
    suite = deepcopy(ref)
    ap.finish_verification(run, ref, suite, row)
    # Earlier forbidden edits can invalidate repair credit even after the current test bytes are restored.
    assert row["finish_check_status"] == "passed" and row["finish_fixed"] is False
    suite.update(exit_code=1)
    suite["h5_observation"]["exit_code"] = 1
    ap.finish_verification(run, ref, suite, row)
    assert row["finish_check_status"] == "failed" and row["finish_check_exit_code"] == 1
    suite = deepcopy(ref)
    suite.pop("h5_observation")
    ap.finish_verification(run, ref, suite, row)
    assert row["finish_check_status"] == "not_checked" and row["finish_check_exit_code"] == 0
    suite = deepcopy(ref)
    suite["h5_state"]["tests"]["test_value.py"] = '0' * 64
    ap.finish_verification(run, ref, suite, row)
    assert row["finish_check_status"] == "not_checked"

"""Completed API replies, bounded recovery, and evidence before actions; no model or project runs."""

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))

import agent_pilot as ap  # noqa: E402


def response(content="", reason="stop", **fields):
    return {"choices": [{"message": {"content": content, **fields}, "finish_reason": reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4}}


def perform(tmp_path, monkeypatch, steps, grading_policy=ap.pp.LEGACY, **settings):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(steps), encoding="utf-8")
    fake = ap.FakeModel(script)
    run = SimpleNamespace(network=False, project=tmp_path / "project", stopped=[],
                          ctx=SimpleNamespace(grading_policy=grading_policy),
                          responses_log=tmp_path / "responses.jsonl", transcript=tmp_path / "transcript.json",
                          end_processes=lambda stage: None, check_integrity=lambda turn, name: None)
    executed = []

    def tool(name, arguments, *rest):
        # The complete response must already be on disk when an action is taken.
        assert run.responses_log.exists()
        executed.append((name, arguments))
        return "ok"

    monkeypatch.setattr(ap, "run_tool", tool)
    stats = ap.episode("stub", "baseline", run, ap.Settings(**settings), fake, lambda: False, lambda: "same")
    records = [json.loads(line) for line in run.responses_log.read_text().splitlines()] if run.responses_log.exists() else []
    messages = json.loads(run.transcript.read_text())
    return stats, records, messages, executed


@pytest.mark.parametrize("network", [False, True])
def test_h5_recovery_prompt_has_one_rule_and_no_broader_config_permission(network):
    common = ap.system_prompt(network, ap.pp.H5)
    assert common.count(ap.pp.PROMPT) == 1
    assert "Other configuration changes may persist" not in common
    assert "new shell" in common and "restore it later" in common
    assert "pythonpath" in common and "DJANGO_SETTINGS_MODULE" in common
    legacy = ap.system_prompt(network)
    assert ap.pp.PROMPT not in legacy and "Other configuration changes may persist" in legacy


def test_h5_episode_keeps_both_the_rule_and_paged_tools(tmp_path, monkeypatch):
    settings = ap.Settings(file_read_mode="paged")
    requests = []
    original = ap.chat

    def chat(model, messages, tools, settings, fake, timeout):
        requests.append((messages[0]["content"], tools))
        return original(model, messages, tools, settings, fake, timeout)

    monkeypatch.setattr(ap, "chat", chat)
    stats, _, messages, calls = perform(tmp_path, monkeypatch,
        [{"say": "partial", "finish_reason": "length"}, {"call": "finish"}],
        grading_policy=ap.pp.H5, file_read_mode=settings.file_read_mode, max_turns=2)
    assert stats["end"] == "finish" and stats["length_continuations"] == 1
    assert calls == [("finish", {})]
    assert messages[0]["content"] == ap.system_prompt(False, ap.pp.H5)
    for common, tools in requests:
        assert common.count(ap.pp.PROMPT) == 1 and "Other configuration changes may persist" not in common
        read = next(t["function"] for t in tools if t["function"]["name"] == "read_file")
        assert {"offset", "limit"} <= read["parameters"]["properties"].keys()


def test_a_length_cutoff_continues_within_the_original_turn_and_token_budget(tmp_path, monkeypatch):
    cut = response("I will inspect the", "length")
    finish = {"call": "finish", "arguments": {"summary": "x"}, "usage": {"completion_tokens": 2}}
    stats, records, messages, executed = perform(tmp_path, monkeypatch, [{"raw_response": cut}, finish], max_turns=2)
    assert (stats["end"], stats["turns"], stats["length_continuations"]) == ("finish", 2, 1)
    assert stats["length_responses"] == 1 and stats["model_responses"] == 2
    assert stats["completion_tokens"] == 6 and stats["prompt_tokens"] == 10
    assert stats["finish_reasons"] == {"length": 1, "tool_calls": 1}
    assert records[0] == {"turn": 1, "response": cut}
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "assistant", "tool"]
    assert "remaining turn and time budget" in messages[3]["content"]
    assert executed == [("finish", {"summary": "x"})]


@pytest.mark.parametrize("allowance,turn_cap,expected_turns,expected_continuations", [(0, 20, 1, 0), (2, 20, 3, 2), (2, 1, 1, 0)])
def test_continuation_cannot_exceed_its_allowance_or_the_turn_cap(tmp_path, monkeypatch, allowance, turn_cap,
                                                             expected_turns, expected_continuations):
    stats, records, _, executed = perform(tmp_path, monkeypatch, [{"say": "partial", "finish_reason": "length"}] * 5,
                                          max_turns=turn_cap, max_length_continuations=allowance)
    assert stats["end"] == "response_truncated" and stats["turns"] == len(records) == expected_turns
    assert stats["length_continuations"] == expected_continuations and not executed


def test_continuation_does_not_make_tool_turns_free(tmp_path, monkeypatch):
    stats, _, _, executed = perform(tmp_path, monkeypatch, [{"say": "partial", "finish_reason": "length"},
                                        {"call": "read_file", "arguments": {"path": "core.py"}},
                                        {"call": "finish"}], max_turns=2)
    assert stats["end"] == "turn_cap" and stats["turns"] == 2
    assert executed == [("read_file", {"path": "core.py"})]


@pytest.mark.parametrize("arguments", ['{"command":"touch marker"}', '{"command":"touch'])
def test_no_action_from_a_truncated_choice_is_executed(tmp_path, monkeypatch, arguments):
    data = response("partial", "length", tool_calls=[{"id": "x", "function": {"name": "run_command", "arguments": arguments}}])
    stats, records, _, executed = perform(tmp_path, monkeypatch, [{"raw_response": data}, {"call": "finish"}])
    assert stats["end"] == "response_truncated" and stats["tool_calls"] == stats["length_continuations"] == 0
    assert records == [{"turn": 1, "response": data}] and not executed


@pytest.mark.parametrize("content,reason,end", [("", "stop", "empty_response"), ("  \n", "stop", "empty_response"),
                                                 (None, "stop", "empty_response"), ("done", "stop", "stopped_without_tool"),
                                                 ("partial", None, "stopped_without_tool"), ("partial", 17, "stopped_without_tool")])
def test_empty_and_complete_stops_do_not_trigger_recovery(tmp_path, monkeypatch, content, reason, end):
    data = response(content, reason, reasoning_content="provider-specific hidden field", refusal=None)
    data["choices"].append({"message": {"content": "unused choice"}, "finish_reason": "length"})
    stats, records, _, executed = perform(tmp_path, monkeypatch, [{"raw_response": data}, {"call": "finish"}])
    assert stats["end"] == end and stats["turns"] == 1 and stats["length_continuations"] == 0
    assert stats["empty_responses"] == int(end == "empty_response")
    assert records == [{"turn": 1, "response": data}] and not executed


@pytest.mark.parametrize("body,error", [({"choices": []}, "no choices"), ([], "no choices"),
                                         ({"choices": [{"message": "bad"}]}, "no message object")])
def test_malformed_completed_responses_are_saved_before_rejection(tmp_path, monkeypatch, body, error):
    stats, records, _, executed = perform(tmp_path, monkeypatch, [{"raw_response": body}])
    assert stats["end"] == "model_error" and error in stats["error"]
    assert records == [{"turn": 1, "response": body}] and not executed


def test_an_unsaved_response_cannot_execute_an_action(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("disk is full")
    monkeypatch.setattr(ap, "save_response", fail)
    with pytest.raises(OSError, match="disk is full"):
        perform(tmp_path, monkeypatch, [{"call": "run_command", "arguments": {"command": "touch marker"}}])
    assert not any(m["role"] == "tool" for m in json.loads((tmp_path / "transcript.json").read_text()))


def test_a_continuation_uses_the_remaining_time_and_never_retries_a_timeout(tmp_path, monkeypatch):
    stats, records, _, executed = perform(tmp_path, monkeypatch, [{"say": "partial", "finish_reason": "length"},
                                          {"delay": 1, "call": "finish"}, {"call": "finish"}], run_timeout=0.05)
    assert stats["end"] == "time_cap" and stats["length_continuations"] == 1
    assert len(records) == stats["model_responses"] == 1 and not executed
    assert stats["agent_s"] < 0.5


def test_chat_preserves_the_full_provider_body_and_keeps_request_settings(monkeypatch):
    body = {"id": "r", **response("partial", "length"), "provider_field": {"x": 1}}
    requests = []
    monkeypatch.setattr(ap, "post_before", lambda url, data, timeout: (requests.append((url, data, timeout)), body)[1])
    settings = ap.Settings(max_tokens=4096, temperature=0.2, seed=20261001)
    messages, tools = [{"role": "user", "content": "x"}], ap.BASIC_TOOLS
    assert ap.chat("stub", messages, tools, settings, None, 7) is body
    assert requests[0][1] == {"model": "stub", "messages": messages, "tools": tools, "max_tokens": 4096,
                              "temperature": 0.2, "seed": 20261001}
    assert requests[0][2] == 7


def test_negative_continuation_limit_is_rejected_before_setup(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        ap.main(["--model", "stub", "--cases", "pkg-inventory:lm_renamed", "--max-length-continuations", "-1",
                 "--out", str(tmp_path / "out")])
    assert error.value.code == 2 and "must be nonnegative" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_one_complete_stop_can_be_reminded_then_finish(tmp_path, monkeypatch):
    stats, records, messages, calls = perform(tmp_path, monkeypatch,
        [{"say": "I will now apply the repair"}, {"call": "finish"}], max_no_tool_reminders=1)
    assert stats["end"] == "finish" and stats["turns"] == len(records) == 2
    assert stats["no_tool_reminders"] == 1 and stats["length_continuations"] == 0
    assert calls == [("finish", {})]
    assert "original turn and time budget" in messages[3]["content"]


def test_a_reminder_is_once_per_episode_not_once_between_actions(tmp_path, monkeypatch):
    stats, records, _, calls = perform(tmp_path, monkeypatch,
        [{"say": "plan"}, {"call": "read_file", "arguments": {"path": "core.py"}},
         {"say": "another plan"}, {"call": "finish"}], max_no_tool_reminders=1)
    assert stats["end"] == "stopped_without_tool" and stats["no_tool_reminders"] == 1
    assert stats["turns"] == len(records) == 3 and len(calls) == 1


@pytest.mark.parametrize("data,end", [
    (response("", "stop"), "empty_response"),
    (response("plan", None), "stopped_without_tool"),
    (response("plan", "content_filter"), "stopped_without_tool"),
    (response("plan", "stop", refusal="declined"), "stopped_without_tool"),
    (response("plan", "length"), "response_truncated"),
])
def test_a_reminder_does_not_retry_empty_unknown_filtered_refused_or_truncated_replies(tmp_path, monkeypatch, data, end):
    stats, records, _, calls = perform(tmp_path, monkeypatch,
        [{"raw_response": data}, {"call": "finish"}], max_no_tool_reminders=1, max_length_continuations=0)
    assert stats["end"] == end and len(records) == 1 and not calls
    assert stats["no_tool_reminders"] == 0


def test_a_reminder_never_extends_the_turn_or_time_cap(tmp_path, monkeypatch):
    stats, records, _, calls = perform(tmp_path, monkeypatch, [{"say": "plan"}, {"call": "finish"}],
                                      max_turns=1, max_no_tool_reminders=1)
    assert stats["end"] == "stopped_without_tool" and len(records) == 1 and not calls
    assert stats["no_tool_reminders"] == 0
    timed = tmp_path / "timed"
    timed.mkdir()
    stats, records, _, calls = perform(timed, monkeypatch,
        [{"say": "plan"}, {"delay": 1, "call": "finish"}], run_timeout=0.05, max_no_tool_reminders=1)
    assert stats["end"] == "time_cap" and stats["no_tool_reminders"] == len(records) == 1 and not calls


@pytest.mark.parametrize("text", ["", "START\n" + "x" * 19000 + "\nEND", "开头\r\n" + "🙂é\r" * 6500 + "结尾"])
def test_file_pages_reconstruct_the_entire_file_without_skipping_long_lines_or_unicode(tmp_path, text):
    (tmp_path / "code.py").write_bytes(text.encode())
    run = SimpleNamespace(project=tmp_path)
    offset, chunks = 0, []
    while True:
        page = json.loads(ap.run_tool("read_file", {"path": "code.py", "offset": offset}, run,
                                      {"file_read_mode": "paged"}, None, None, 1))
        assert page["offset"] == offset and len(page["text"]) <= ap.OUTPUT_LIMIT
        chunks.append(page["text"])
        assert page["next_offset"] == offset + len(page["text"])
        if page["eof"]:
            assert page["next_offset"] == page["total_chars"]
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert "".join(chunks) == text.replace("\r\n", "\n").replace("\r", "\n")


@pytest.mark.parametrize("values", [{"offset": -1}, {"offset": True}, {"offset": 4}, {"offset": 0.5},
                                  {"limit": 0}, {"limit": 6001}, {"limit": False}, {"limit": "2"}])
def test_invalid_page_ranges_are_refused(tmp_path, values):
    (tmp_path / "code.py").write_text("abc")
    reply = ap.run_tool("read_file", {"path": "code.py", **values}, SimpleNamespace(project=tmp_path),
                        {"file_read_mode": "paged"}, None, None, 1)
    assert reply.startswith("error:")


def test_pages_and_legacy_tail_have_distinct_tool_contracts_and_respect_project_boundaries(tmp_path):
    (tmp_path / "code.py").write_text("head" + "x" * 6000 + "tail")
    run = SimpleNamespace(project=tmp_path)
    legacy = ap.run_tool("read_file", {"path": "code.py"}, run, {}, None, None, 1)
    assert legacy.startswith("...(earlier output cut)...") and legacy.endswith("tail")
    page = json.loads(ap.run_tool("read_file", {"path": "code.py", "limit": 4}, run,
                                  {"file_read_mode": "paged"}, None, None, 1))
    assert page["text"] == "head" and page["next_offset"] == 4 and not page["eof"]
    outside = tmp_path.parent / "outside.py"
    outside.write_text("private")
    (tmp_path / "link.py").symlink_to(outside)
    assert ap.run_tool("read_file", {"path": "link.py"}, run, {"file_read_mode": "paged"}, None, None, 1).startswith("error:")
    assert ap.basic_tools("tail") == ap.BASIC_TOOLS
    read = next(t["function"] for t in ap.basic_tools("paged") if t["function"]["name"] == "read_file")
    assert {"offset", "limit"} <= read["parameters"]["properties"].keys()
    assert "offset" not in ap.BASIC_TOOLS[1]["function"]["parameters"]["properties"]


def test_explicit_sampling_values_are_sent_and_protocols_remain_distinct(monkeypatch):
    import compare_arms as ca
    requests = []
    monkeypatch.setattr(ap, "post_before", lambda url, body, timeout: (requests.append(body), response())[1])
    ap.chat("stub", [], [], ap.Settings(max_tokens=32768, temperature=0.6, top_p=0.95, top_k=20), None, 7)
    assert {k: requests[0][k] for k in ("max_tokens", "temperature", "top_p", "top_k")} == {
        "max_tokens": 32768, "temperature": 0.6, "top_p": 0.95, "top_k": 20}
    row = {"settings": {"max_turns": 20, "run_timeout": 900.0, "temperature": 0.2, "max_tokens": 4096,
                        "seed": 20261001}, "harness_commit": "fixed", "network": "on"}
    legacy = ca.protocol(row)
    for field, value in (("top_p", 0.95), ("top_k", 20), ("file_read_mode", "paged"), ("max_no_tool_reminders", 1)):
        assert ca.protocol({**row, "settings": {**row["settings"], field: value}}) != legacy


@pytest.mark.parametrize("options", [["--top-p", "nan"], ["--top-p", "inf"], ["--top-p", "0"],
                                    ["--top-p", "1.01"], ["--top-k", "-1"], ["--max-no-tool-reminders", "2"]])
def test_invalid_sampling_and_reminder_values_fail_before_setup(tmp_path, options):
    with pytest.raises(SystemExit) as error:
        ap.main(["--model", "stub", "--cases", "pkg-inventory:lm_renamed", "--out", str(tmp_path / "out"), *options])
    assert error.value.code == 2 and not (tmp_path / "out").exists()

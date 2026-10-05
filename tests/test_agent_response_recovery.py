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


def perform(tmp_path, monkeypatch, steps, **settings):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(steps), encoding="utf-8")
    fake = ap.FakeModel(script)
    run = SimpleNamespace(network=False, project=tmp_path / "project", stopped=[],
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

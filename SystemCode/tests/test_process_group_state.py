"""Permission failures need evidence about the remaining helpers, not blanket suppression."""

import os
import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from fixfirst import processes


@pytest.mark.parametrize("snapshots, expected", [
    (["12346 12345 Z\n99 99 S\n"] * 2, True),
    (["12346 12345 Z\n99 99 S\n", "99 99 S\n"], True),
    (["99 99 S\n"] * 2, True),
    (["12346 12345 S\n"], False),
    (["12346 12345 Z\n12347 12345 S\n"], False),
    (["12346 12345 Z\n", "12346 12345 Z\n12347 12345 Z\n"], False),
    (["12346 12345 Z\n", "12346 12345 R\n"], False),
    ([""], False),
    (["PID PGID STAT\n"], False),
    (["12346 12345 Z\n12346 12345 Z\n"], False),
    (["12346 12345 Z\n", "malformed\n"], False),
])
def test_group_snapshots_do_not_conflate_dead_live_and_unverifiable(monkeypatch, snapshots, expected):
    query = Mock(side_effect=[subprocess.CompletedProcess([], 0, text, "") for text in snapshots])
    monkeypatch.setattr(subprocess, "run", query)
    assert processes._group_has_exited(12345) is expected
    for call in query.call_args_list:
        assert call.args[0] == ["/bin/ps", "-A", "-o", "pid=,pgid=,stat="]
        assert call.kwargs["timeout"] == 2


@pytest.mark.parametrize("failure", [OSError("cannot inspect"), subprocess.TimeoutExpired("ps", 2),
                                      UnicodeError("invalid state data")])
def test_failed_group_query_cannot_clear_permission_failure(monkeypatch, failure):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    assert not processes._group_has_exited(12345)


def test_nonzero_group_query_is_unverifiable(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 1, "99 99 S\n", "denied")))
    assert not processes._group_has_exited(12345)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_only_observed_dead_helpers_allow_repeated_eperm_to_finish(monkeypatch):
    process = processes.ManagedProcess.__new__(processes.ManagedProcess)
    process.scope = processes.ProcessScope()
    process.job = None
    process.closed = False
    process.proc = Mock(pid=12345)
    process.proc.poll.return_value = 0
    process.scope.children.add(process)
    kill = Mock(side_effect=PermissionError("already exited"))
    monkeypatch.setattr(os, "killpg", kill)
    query = Mock(return_value=subprocess.CompletedProcess([], 0, "12346 12345 Z\n", ""))
    monkeypatch.setattr(subprocess, "run", query)
    process.close()
    assert process.closed and process not in process.scope.children
    assert kill.call_args_list == [((12345, signal.SIGKILL),)] * 2
    assert query.call_count == 2
    process.proc.wait.assert_called_once_with(timeout=10)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_real_live_helper_is_terminated_after_its_leader_exits(tmp_path, monkeypatch):
    pidfile = tmp_path / "helper.pid"
    source = ("import pathlib, subprocess, sys\n"
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], "
              "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
              "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n")
    scope = processes.ProcessScope()
    with scope.activate():
        process = processes.ManagedProcess([sys.executable, "-c", source, str(pidfile)],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    helper = None
    try:
        assert process.wait(timeout=10) == 0
        helper = int(pidfile.read_text())
        assert os.getpgid(helper) == process.pid
        # Inspect a genuinely live group, rather than faking its state query.
        denied = PermissionError("cannot signal this live helper")
        with monkeypatch.context() as patch:
            patch.setattr(os, "killpg", Mock(side_effect=denied))
            with pytest.raises(PermissionError) as exc:
                process.close()
            assert exc.value is denied
            assert not process.closed and process in scope.children
        process.close()
        assert process.closed and not scope.children
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(helper)],
                                    capture_output=True, text=True, timeout=2).stdout.strip()
            if not status or status.startswith("Z"):
                break
            time.sleep(.01)
        else:
            pytest.fail("the helper remained alive after group cleanup")
    finally:
        process.close()

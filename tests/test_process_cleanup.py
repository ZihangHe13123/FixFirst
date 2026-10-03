"""Exited-leader cleanup must not hide failures or abandon other process groups."""

import os
import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from fixfirst.processes import ManagedProcess, ProcessCancelled, ProcessScope


def fake_process():
    process = ManagedProcess.__new__(ManagedProcess)
    process.scope = ProcessScope()
    process.job = None
    process.closed = False
    process.proc = Mock(pid=12345)
    process.scope.children.add(process)
    return process


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_reap_exited_leader_then_confirm_group_disappeared(monkeypatch):
    process = fake_process()
    process.proc.poll.return_value = 0
    kill = Mock(side_effect=[PermissionError("unreaped group"), ProcessLookupError()])
    monkeypatch.setattr(os, "killpg", kill)
    process.close()
    assert kill.call_args_list == [((12345, signal.SIGKILL),)] * 2
    process.proc.poll.assert_called_once_with()
    process.proc.wait.assert_called_once_with(timeout=10)
    assert process.closed and process not in process.scope.children
    process.close()
    assert kill.call_count == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_exited_leader_does_not_mean_no_descendants(monkeypatch):
    process = fake_process()
    process.proc.poll.return_value = 0
    kill = Mock(side_effect=[PermissionError(), None])
    monkeypatch.setattr(os, "killpg", kill)
    process.close()
    assert kill.call_count == 2
    assert process.closed


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
@pytest.mark.parametrize("returncode", [None, 0])
def test_permission_failure_is_not_reported_as_success(monkeypatch, returncode):
    process = fake_process()
    process.proc.poll.return_value = returncode
    denied = PermissionError("cannot terminate this group")
    kill = Mock(side_effect=denied)
    monkeypatch.setattr(os, "killpg", kill)
    with pytest.raises(PermissionError) as exc:
        process.close()
    assert exc.value is denied
    assert kill.call_count == (1 if returncode is None else 2)
    assert not process.closed and process in process.scope.children
    process.proc.wait.assert_not_called()


def test_cancel_attempts_other_children_before_reporting_failure(monkeypatch):
    scope = ProcessScope()
    denied = PermissionError("cannot terminate one check")
    failed, another_failed, other = Mock(), Mock(), Mock()
    failed.kill_tree.side_effect = denied
    another_failed.kill_tree.side_effect = denied
    scope.children = {failed, another_failed, other}
    popen = Mock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(PermissionError) as exc:
        scope.cancel()
    assert exc.value is denied and scope.cancelled
    failed.kill_tree.assert_called_once_with()
    another_failed.kill_tree.assert_called_once_with()
    other.kill_tree.assert_called_once_with()
    with scope.activate(), pytest.raises(ProcessCancelled):
        ManagedProcess([sys.executable, "-c", "pass"])
    popen.assert_not_called()


@pytest.mark.skipif(os.name == "nt", reason="POSIX zombie process observation")
def test_real_exited_child_is_reaped_and_unregistered():
    scope = ProcessScope()
    with scope.activate():
        process = ManagedProcess([sys.executable, "-c", "pass"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Observe without wait()/poll(), so the child remains unreaped. ps only
        # inspects the PID this test created; no signals go to unrelated processes.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(process.pid)],
                                   capture_output=True, text=True, timeout=2)
            if state.stdout.strip().startswith("Z"):
                break
            time.sleep(.01)
        else:
            pytest.fail("the child did not reach its exited, unreaped state")
        process.close()
        assert process.returncode == 0
        assert process.closed and process not in scope.children
    finally:
        # Ensure cleanup even when testing the pre-fix implementation, where
        # close() raises EPERM before it can reap the child.
        process.proc.wait(timeout=5)
        process.close()

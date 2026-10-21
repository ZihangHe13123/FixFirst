import sys

import pytest

from fixfirst import runner


@pytest.mark.parametrize("output,expected", [
    (b"first\r\nsecond\r\nprogress\rend\n", "first\nsecond\nprogress\rend\n"),
    (b"first\nsecond\nprogress\rend\n", "first\nsecond\nprogress\rend\n"),
    ("一行\r\n第二行\r".encode(), "一行\n第二行\r"),
])
def test_pipe_newlines_are_normalised_before_redaction(tmp_path, monkeypatch, output, expected):
    observed = []
    real_redact = runner.redact

    def inspect(text):
        observed.append(text)
        return real_redact(text)

    monkeypatch.setattr(runner, "redact", inspect)
    code = f"import os; os.write(1, {output!r}); os.write(2, {output!r})"
    run = runner.execute([sys.executable, "-c", code], str(tmp_path), "python_run",
                         "test:newlines", sys.executable)
    assert run.status == "completed" and run.exit_code == 0
    assert run.stdout == run.stderr == expected
    assert observed == [expected, expected]


def test_crlf_does_not_disable_environment_redaction(tmp_path):
    output = b'environ({"API_KEY": "private-value"})\r\nnext line\r\n'
    run = runner.execute([sys.executable, "-c", f"import os; os.write(2, {output!r})"],
                         str(tmp_path), "python_run", "test:redaction", sys.executable)
    assert run.stderr == "environ({<redacted>})\nnext line\n"
    assert "private-value" not in run.stderr

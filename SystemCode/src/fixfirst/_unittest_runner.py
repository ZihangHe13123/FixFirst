"""Standalone standard-library-only unittest adapter, executed by the target Python."""

import json
import os
from pathlib import Path
import sys
import traceback
import unittest

from _runtime_evidence import exception_metadata

record_path = Path(os.environ["FIXFIRST_EXECUTION_RECORDS"])
written = 0
dropped = False


def emit(record, final=False):
    global written, dropped
    line = json.dumps(record, ensure_ascii=True) + "\n"
    if written + len(line) > 800_000 and not final:
        dropped = True
        return
    with record_path.open("a", encoding="utf-8") as stream:
        stream.write(line)
    written += len(line)


class Result(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.current_outcome = "incomplete"

    def stopTest(self, test):
        emit({"type": "unit_outcome", "nodeid": test.id(), "outcome": self.current_outcome})
        super().stopTest(test)

    def problem(self, test, err):
        self.current_outcome = "failed"
        trace = "".join(traceback.format_exception(*err))
        frames = traceback.extract_tb(err[2])
        source = frames[-1] if frames else None
        stage = "collect" if type(test).__name__ == "_FailedTest" else "call"
        emit({"type": "failure", "nodeid": test.id(), "stage": stage, "message": trace[:60_000]})
        emit({"type": "exception", "nodeid": test.id(), "stage": stage,
              "exception_type": err[0].__name__, "exception_module": err[0].__module__,
              "exception_message": str(err[1])[:4000],
              **exception_metadata(err[1], err[2]),
              "source_file": source.filename if source else "",
              "source_line": source.lineno if source else None})

    def addSuccess(self, test):
        if self.current_outcome == "incomplete":
            self.current_outcome = "passed"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.problem(test, err)
        super().addFailure(test, err)

    def addError(self, test, err):
        self.problem(test, err)
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.problem(test, err)
        super().addSubTest(test, subtest, err)

    def addSkip(self, test, reason):
        if self.current_outcome != "failed":
            self.current_outcome = "skipped"
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.current_outcome = "xfail"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.current_outcome = "xpass"
        super().addUnexpectedSuccess(test)


def nodes(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from nodes(test)
        else:
            yield test.id()


def main():
    sys.path.insert(0, os.getcwd())
    suite = unittest.defaultTestLoader.discover(sys.argv[1], pattern=sys.argv[2])
    selected = list(nodes(suite))
    result = unittest.TextTestRunner(resultclass=Result, verbosity=2).run(suite)
    code = 0 if result.wasSuccessful() else 1
    emit({"type": "unit_finish", "nodes": selected[:5000], "ran": result.testsRun,
          "exit_code": code, "records_dropped": dropped or len(selected) > 5000}, final=True)
    return code


if __name__ == "__main__":
    sys.exit(main())

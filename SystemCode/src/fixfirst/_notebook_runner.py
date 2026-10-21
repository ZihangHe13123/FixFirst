"""Optional notebook driver. Host dependencies, explicitly selected target kernel."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def main():
    record_path = Path(os.environ["FIXFIRST_EXECUTION_RECORDS"])
    written = 0
    dropped = False

    def emit(record, final=False):
        nonlocal written, dropped
        line = json.dumps(record, ensure_ascii=True) + "\n"
        if written + len(line) > 800_000 and not final:
            dropped = True
            return
        with record_path.open("a", encoding="utf-8") as stream:
            stream.write(line)
        written += len(line)

    try:
        import nbformat
        from nbclient import NotebookClient
        from nbclient.exceptions import CellExecutionError
    except ImportError:
        emit({"type": "execution_tool_error", "component": "notebook_driver", "message":
              "Notebook execution needs nbclient and nbformat in FixFirst's Python. "
              "Install this checkout's notebooks extra, or install nbclient into FixFirst's environment."})
        return 2
    python, entry, timeout = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="fixfirst-kernel-") as directory:
        probe = subprocess.run([python, "-c", "import ipykernel"], cwd=directory,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if probe.returncode:
            emit({"type": "execution_tool_error", "component": "ipykernel", "message":
                  "The selected project Python needs ipykernel to run notebooks. "
                  "Install ipykernel in that environment and check again."})
            return 2
        kernel = Path(directory) / "kernels" / "fixfirst"
        kernel.mkdir(parents=True)
        (kernel / "kernel.json").write_text(json.dumps({
            "argv": [python, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "FixFirst selected Python", "language": "python",
        }), encoding="utf-8")
        os.environ["JUPYTER_PATH"] = directory + os.pathsep + os.environ.get("JUPYTER_PATH", "")
        os.environ["JUPYTER_RUNTIME_DIR"] = str(Path(directory) / "runtime")
        notebook = nbformat.read(entry, as_version=4)
        for cell in notebook.cells:
            if cell.cell_type == "code":
                cell.outputs = []
                cell.execution_count = None
        expected = sum(c.cell_type == "code" and bool(c.source.strip()) for c in notebook.cells)
        visited = []

        class CapturingClient(NotebookClient):
            def process_message(self, msg, cell, cell_index):
                # Stream output immediately so the parent enforces its output/memory bound
                # even when a cell never finishes.
                content = msg.get("content", {})
                kind = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
                if kind == "stream":
                    print(content.get("text", ""), end="", flush=True)
                elif kind in ("display_data", "execute_result"):
                    print(content.get("data", {}).get("text/plain", ""), flush=True)
                return super().process_message(msg, cell, cell_index)

        def on_cell_executed(cell, cell_index, execute_reply):
            visited.append(cell_index)
            emit({"type": "cell_outcome", "cell": cell_index + 1,
                  "status": execute_reply.get("content", {}).get("status", "unknown")})
        client = CapturingClient(
            notebook, kernel_name="fixfirst", timeout=max(1, int(float(timeout))),
            resources={"metadata": {"path": os.getcwd()}}, allow_errors=False,
            force_raise_errors=True, skip_cells_with_tag="", store_widget_state=False,
            on_cell_executed=on_cell_executed,
        )
        try:
            client.execute()
        except CellExecutionError:
            for index, cell in enumerate(notebook.cells):
                for output in cell.get("outputs", []):
                    if output.output_type != "error":
                        continue
                    trace = re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(output.get("traceback", [])))
                    # IPython abbreviates paths under the inherited home as ~/...
                    # Expand while recording, not later on a different replay host.
                    trace = re.sub(r"(?m)^File ~(?=[/\\])",
                                   lambda _: "File " + str(Path.home()), trace)
                    emit({"type": "failure", "stage": "run", "nodeid": f"{entry}:cell {index + 1}",
                          "message": trace[:60_000]})
                    emit({"type": "exception", "stage": "run", "nodeid": f"{entry}:cell {index + 1}",
                          "exception_type": output.get("ename", "Exception"),
                          "exception_message": output.get("evalue", "")[:4000],
                          "source_file": entry, "cell": index + 1})
                    print(trace, file=sys.stderr)
            return 1
        except Exception as exc:
            emit({"type": "execution_tool_error",
                  "message": f"Notebook execution did not complete: {type(exc).__name__}: {exc}"[:5000]})
            return 2
        emit({"type": "notebook_finish", "executed": len(visited), "expected": expected,
              "exit_code": 0, "records_dropped": dropped}, final=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())

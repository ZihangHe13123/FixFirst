"""Build a fixed-revision candidate source ZIP and its auditable sidecar receipt.

Only committed files in the committed allowlist are copied. No tests or installers
are run. This creates a local candidate, not a tag or a published release.
"""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ALLOWLIST = "docs/freeze/source-zip-allowlist.txt"
MODEL = "src/fixfirst/knowledge/diagnosis_tree.json"
MODEL_SHA256 = "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(repo, revision, output):
    def git(*args):
        return subprocess.check_output(["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf",
                                        "-c", f"core.attributesFile={os.devnull}", "-C", str(repo), *args])

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use the complete approved source commit SHA")
    git("rev-parse", "--verify", revision + "^{commit}")
    receipt_path = output.with_suffix(output.suffix + ".receipt.json")
    if output.exists() or receipt_path.exists():
        raise ValueError("Use new output paths; existing artifacts are never overwritten")
    manifest = git("show", f"{revision}:{ALLOWLIST}")
    paths = manifest.decode("utf-8").splitlines()
    if not paths or paths != sorted(set(paths)) or ALLOWLIST not in paths:
        raise ValueError("Allowlist must be sorted, unique and include itself")
    for name in paths:
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or str(path) != name
                or any(c in name for c in ("*", "?", "[", "\\", "\x00"))
                or any(part in {".git", ".venv", ".fixfirst", "workbench", "holdout-reveal"}
                       for part in path.parts)):
            raise ValueError(f"Unsafe allowlist entry: {name}")
        row = git("ls-tree", revision, "--", name).split()
        if not row or row[0] not in (b"100644", b"100755"):
            raise ValueError(f"Not a regular committed file: {name}")
    project = tomllib.loads(git("show", f"{revision}:pyproject.toml").decode())
    version = project["project"]["version"]
    init = ast.parse(git("show", f"{revision}:src/fixfirst/__init__.py"))
    versions = [ast.literal_eval(n.value) for n in init.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets)]
    if versions != [version] or version != "0.7.0":
        raise ValueError("Candidate package and module version must both be 0.7.0")
    if sha(git("show", f"{revision}:{MODEL}")) != MODEL_SHA256:
        raise ValueError("The approved bundled model changed")
    attributes = git("show", f"{revision}:.gitattributes")
    attribute_lines = {line.strip() for line in attributes.decode().splitlines()}
    payload = git("archive", "--format=zip", "--prefix=FixFirst/", revision, "--", *paths)
    contents = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        names = [item.filename.removeprefix("FixFirst/") for item in entries]
        if len(names) != len(set(names)) or set(names) != set(paths):
            raise ValueError("Archive membership differs from the exact allowlist")
        for item, name in zip(entries, names):
            data = archive.read(item)
            original = git("show", f"{revision}:{name}")
            transformation = "none"
            if data != original:
                suffix = PurePosixPath(name).suffix
                if (suffix not in (".bat", ".ps1")
                        or f"*{suffix} text eol=crlf" not in attribute_lines
                        or data != original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")):
                    raise ValueError(f"Archive bytes differ from the committed source: {name}")
                transformation = "declared text eol=crlf"
            contents[name] = {"sha256": sha(data), "bytes": len(data),
                              "git_blob_sha256": sha(original), "transformation": transformation}
    receipt = {
        "status": "local_candidate_not_formally_frozen", "source_commit": revision,
        "package_version": version, "archive": output.name, "archive_sha256": sha(payload),
        "archive_bytes": len(payload), "allowlist_sha256": sha(manifest),
        "gitattributes_sha256": sha(attributes),
        "default_model_sha256": MODEL_SHA256, "files": contents,
        "file_count": len(contents), "private_start_sessions_included": False,
        "full_development_regression_fixtures_included": False,
        "reproducibility": "git archive of the same commit and allowlist, with repository-declared CRLF for Windows scripts; no working-tree files",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in receipt.items() if key != "files"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.repo.resolve(), args.revision, args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()

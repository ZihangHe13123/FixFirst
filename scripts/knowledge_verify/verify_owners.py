#!/usr/bin/env python3
"""Verify the `owners` of FixFirst's removal knowledge against the real libraries.

A `[[removed]]` block with `owners` is applied only when the failed receiver's class (or one of its bases) is one of the named
library classes (src/fixfirst/removal_ownership.py). `owners` is therefore a claim about a real class, and this program checks it
by running real code, the same way verify.py checks that a name is gone:

  * for every key of every block with `owners`, a RECIPE (owners/recipes.toml) builds a real object of the class (`obj`; a block with
    several owners may need one receiver for each);
  * the recipe runs in the environments of the check of verify.py that proved the removal: in the last release that still has the
    attribute (the lookup must work) and in the first release without it and in later releases (the lookup must raise AttributeError);
  * in each of those releases the product's own receiver_owners() (fixfirst/_runtime_evidence.py, loaded from --fixfirst-src)
    is asked which class identities the object has. At least one declared owner must be among them, and must come from the
    block's distribution (the product's own condition: a dynamic receiver counts only through its own class); every declared owner
    must be a real identity of a receiver in some release (no phantom paths);
  * unless --no-e2e, FixFirst itself (--fixfirst-src) then diagnoses a script that ends in `obj.<name>`: exactly this key must be
    authorized (a `removal_owner` fact; a second entry that matches the same receiver would show the same step twice), the issue must be
    a version incompatibility decided by the rule of the entry (D02 for api, D03 for attribute) and the first step of the plan must be the
    removal action with the replacement text of the entry; and a project class of the same name that calls the same attribute must fail in the project
    run and NOT be authorized, diagnosed as a version problem or shown that replacement;
  * the candidates that were merged into an enabled entry (owners/dispositions.toml `[[merged]]`) are verified the same way with the
    receiver of the MERGED key (a DiGraph for api:DiGraph.node) against the entry that covers it: same attribute, distribution, removal
    version and source (and replacement, or a stated `replacement_note`), every release authorizes the receiver through that entry and
    through no other, and FixFirst authorizes exactly that entry and shows its replacement.

It does not prove that a replacement text is right (verify.py's probes do that for some blocks) and it does not prove that every failing
statement in the wild is observable. The recipes exercise the simplest shape, `obj.<name>`. The product observes the receiver of a failing
attribute load that is a name or an attribute of a name (`engine.t()`, `self.engine.t()`), but not a call result (`make_engine().t()`), not a
decorator line (`@app.t`) and not a lookup that fails inside a library; and only for classes that a module holds under their qualified name
and that have at most 64 base classes (at most 128 identities, 32768 bytes of them). A block that cannot be authorized for `obj.<name>` stays parked.

The receipt is a detailed record, not a verdict: audit_receipt() judges it again from the stored details with the functions that judged the run
(tests/test_knowledge_owners.py calls it offline). It judges: the keys, the block hashes and the recipe; the releases (exactly the ones the recipe and
the verifying checks call for, each in its environment, with its interpreter and its pinned packages); the receiver identities of every release in which
the attribute is gone (a declared owner authorizes the receiver, from the block's distribution wherever the interpreter can tell, which is Python 3.10 and
newer; exactly one entry of the knowledge base authorizes it; the receiver of a merged key is an object of the merged class); and the runs of FixFirst
(the authorization, the rule, the first step with the replacement text and the removal version, the project class of the same name). It takes as stored
what only a new run can show again: the raw measurements themselves (the rows of identities, the messages, the installed versions of unpinned packages).
The receipt is bound to this program and to the recipes, to the functions that decide a receiver's identities (identity_functions_sha256), and to the
product that the E2E runs executed: every module of the product that was loaded in them and the scripts that run in the target interpreter
(e2e_files_sha256), the knowledge data they read (e2e_data_sha256) and every rule (e2e_rules_sha256). Comments, blank lines, line endings and the order of
keys do not count. The digest of the whole package is informational.

Requirements: as verify.py (Python >= 3.11, `uv`, uv-managed CPython 3.8 - 3.14, network access to PyPI).

    python verify_owners.py --fixfirst-src ../../src --receipts /tmp/owners-receipt.json > owners-log.txt

By default the blocks of the shipped knowledge base (fixfirst/knowledge/domain.toml) that have `owners` are verified. Authoring aids:
--explore prints what the product sees for each key of --blocks FILE (rows of module.owner, `*` = the receiver's own class; the blocks
need no `owners`); --merge FILE adds not yet shipped blocks to the COPY of the knowledge base that the product runs on; --base DIR keeps
and reuses the environments. A reference run (the receipt) uses none of them.

Exit status 0 means every block with owners passed.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tokenize
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify  # noqa: E402  (the program that verified the blocks themselves: environments, checks, log hygiene)

MARK = "@@OWNERS@@"

# the functions of fixfirst/_runtime_evidence.py that decide which class identities a receiver has; the record is bound to their source
IDENTITY_FUNCTIONS = ("plain_class", "class_namespace", "class_mro", "class_identity", "receiver_owners", "registered_type", "static_namespace")


def identity_functions_sha256(probe_path: str) -> str:
    source = open(probe_path, encoding="utf-8").read().replace("\r\n", "\n")
    found = {node.name: ast.get_source_segment(source, node) for node in ast.parse(source).body
             if isinstance(node, ast.FunctionDef) and node.name in IDENTITY_FUNCTIONS}
    missing = [name for name in IDENTITY_FUNCTIONS if name not in found]
    if missing:
        raise SystemExit(f"{probe_path} no longer defines {missing}; verify_owners.py has to follow the product")
    return hashlib.sha256("\n".join(found[name] for name in IDENTITY_FUNCTIONS).encode("utf-8")).hexdigest()


# Python scripts of the product that run inside the target interpreter (the product does not import them, so no E2E run lists them as loaded)
TARGET_SIDE_SCRIPTS = ("_runtime_evidence.py", "_native_runner.py", "_unittest_runner.py", "_notebook_runner.py")
# knowledge data that the record does not bind as a whole: domain.toml is bound block by block (and by the other receipts), the parked file is not loaded
KNOWLEDGE_NOT_BOUND = ("knowledge/domain.toml", "knowledge/pending_attribution.toml")
RULE_OF_KIND = {"api": "D02", "attribute": "D03"}


def _normalized(path: str) -> bytes:
    return open(path, "rb").read().replace(b"\r\n", b"\n")


def _canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def code_sha256(path: str) -> str:
    """The digest of a Python source without its comments, its blank lines, its trailing spaces and its line-ending style: what the code says, not
    how it is annotated. (A comment is found with the tokenizer, so a `#` inside a string stays.)"""
    text = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    lines = text.split("\n")
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                row, column = token.start
                lines[row - 1] = lines[row - 1][:column]
    except (tokenize.TokenError, IndentationError, SyntaxError):         # not a source the tokenizer takes: bind it as it is
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return hashlib.sha256("\n".join(line.rstrip() for line in lines if line.strip()).encode("utf-8")).hexdigest()


def data_sha256(path: str) -> str:
    """The digest of a data file: TOML and JSON by what they parse to (comments, formatting and the order of keys do not count), anything else by its bytes."""
    raw = _normalized(path)
    if path.endswith(".toml"):
        return _canonical_sha256(tomllib.loads(raw.decode("utf-8")))
    if path.endswith(".json"):
        return _canonical_sha256(json.loads(raw.decode("utf-8")))
    return hashlib.sha256(raw).hexdigest()


def product_digests(package_dir: str, loaded=()) -> dict:
    """What the receipt binds in the product. `package_dir` is the directory of the `fixfirst` package; `loaded` are the modules (relative paths) that the
    E2E runs of the record loaded: they and the scripts of the target interpreter are bound file by file, every knowledge data file and every rule too."""
    names = sorted({*loaded, *(name for name in TARGET_SIDE_SCRIPTS if os.path.exists(os.path.join(package_dir, name)))})
    files = {}
    for name in names:
        path = os.path.join(package_dir, name)
        files[name] = code_sha256(path) if os.path.exists(path) else "missing"
    rules = tomllib.loads(_normalized(os.path.join(package_dir, "knowledge", "rules.toml")).decode("utf-8"))["rule"]
    data, everything = {}, hashlib.sha256()
    for directory, dirs, found in sorted(os.walk(package_dir)):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(found):
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, package_dir).replace(os.sep, "/")
            if relative.startswith("knowledge/") and relative not in KNOWLEDGE_NOT_BOUND and relative != "knowledge/rules.toml":
                data[relative] = data_sha256(path)
            if name.endswith((".py", ".toml")) and relative not in KNOWLEDGE_NOT_BOUND:
                everything.update(relative.encode("utf-8") + b"\0" + _normalized(path) + b"\0")
    return {"identity_functions_sha256": identity_functions_sha256(os.path.join(package_dir, "_runtime_evidence.py")),
            "e2e_files_sha256": files, "e2e_data_sha256": data,
            "e2e_rules_sha256": {rule["id"]: _canonical_sha256(rule) for rule in rules},
            "package_sha256": everything.hexdigest()}


# --------------------------------------------------------------------------------------------------
# what runs inside the target interpreter
# --------------------------------------------------------------------------------------------------
RUNNER = r'''
import sys, json, io, contextlib, warnings, importlib.util
MARK = "@@OWNERS@@"
spec = json.load(sys.stdin)
warnings.simplefilter("ignore")
out = {"python": "%d.%d.%d" % sys.version_info[:3]}


def done():
    print(MARK + json.dumps(out))
    sys.exit(0)


try:
    s = importlib.util.spec_from_file_location("ff_probe", spec["probe"])
    probe = importlib.util.module_from_spec(s)
    s.loader.exec_module(probe)
except BaseException as e:
    out["probe_error"] = type(e).__name__ + ": " + str(e)[:300]
    done()
g = {"__name__": "__main__", "__file__": "<recipe>"}
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        exec(compile(spec["setup"], "<recipe>", "exec"), g)
    obj = g["obj"]
except BaseException as e:
    out["setup_error"] = type(e).__name__ + ": " + str(e)[:500]
    done()
name = spec["name"]
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        getattr(obj, name)
    out["access"] = "ok"
except AttributeError as e:
    out["access"] = "AttributeError"
    out["message"] = str(e)[:300]
    out["error_name"] = getattr(e, "name", None)
except BaseException as e:
    out["access"] = "error:" + type(e).__name__
    out["message"] = str(e)[:300]
cls = obj if probe.plain_class(obj) else type(obj)
out["plain"] = bool(probe.plain_class(cls))
out["type"] = [getattr(cls, "__module__", ""), getattr(cls, "__qualname__", "")]
out["identity"] = list(probe.class_identity(cls)) if out["plain"] else ["", ""]
out["rows"] = [[r["module"], r["owner"], bool(r["direct"])] for r in probe.receiver_owners(obj)]
ns = probe.static_namespace(obj)
if ns:
    keys, kind, _module, _owner, dynamic = ns
    out["kind"], out["dynamic"], out["member_present"] = kind, bool(dynamic), name in keys
tops = sorted({row[0].split(".")[0] for row in out["rows"]})
providers = {}
if sys.version_info >= (3, 10):
    import importlib.metadata as md
    mapping = md.packages_distributions()
    for top in tops:
        providers[top] = sorted(mapping.get(top, []))
    out["stdlib"] = {top: top in sys.stdlib_module_names for top in tops}
out["providers"] = providers
done()
'''

# runs in an interpreter that has FixFirst's dependencies; the target interpreter is only started by FixFirst itself
E2E_RUNNER = r'''
import sys, json, os, shutil, tempfile
MARK = "@@OWNERS@@"
spec = json.load(sys.stdin)
sys.path.insert(0, spec["src"])
from fixfirst.models import Execution
from fixfirst.reasoning import infer_and_plan
from fixfirst.service import create_session, scan

results = []
for item in spec["items"]:
    work = tempfile.mkdtemp(prefix="ffo-")
    record = {"id": item["id"]}
    try:
        with open(os.path.join(work, "main.py"), "w", encoding="utf-8") as stream:
            stream.write(item["code"])
        session = create_session(work, item["python"], goal="run_project", execution=Execution(entry="main.py"))
        session.use_classifier = False
        scan(session, ["environment", "project", "python_run"])
        infer_and_plan(session)
        issues = [i for i in session.issues if i.tool == "python_run" and i.status == "open"]
        record["issues"] = [[i.title[:160], i.diagnosis, getattr(i, "diagnosis_source", None), getattr(i, "diagnosis_rule", None)] for i in issues]
        ids = {i.issue_id for i in issues}
        record["removal_owner"] = sorted({f.value for f in session.facts if f.predicate == "removal_owner" and f.subject in ids})
        record["steps"] = [[a.title[:200], a.explanation[:1500]] for a in session.actions][:6]
    except BaseException as error:
        record["error"] = type(error).__name__ + ": " + str(error)[:400]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    results.append(record)
package = os.path.join(os.path.realpath(spec["src"]), "fixfirst") + os.sep
loaded = sorted({os.path.realpath(m.__file__)[len(package):].replace(os.sep, "/") for m in list(sys.modules.values())
                 if getattr(m, "__file__", None) and os.path.realpath(m.__file__).startswith(package)})
print(MARK + json.dumps({"records": results, "loaded": loaded}))
'''


class PersistentWorkspace(verify.Workspace):
    """Reuse the environments of an earlier run in the same --base directory (authoring only; a reference run starts empty)."""

    def python_for(self, env):
        if env.pkgs and env.python in verify.find_pythons():
            digest = hashlib.sha1(repr((env.python, env.pkgs, env.only_binary)).encode()).hexdigest()[:10]
            directory = os.path.join(self.base, f"env-{env.python}-{digest}")
            marker = os.path.join(directory, ".ff-ready")
            if os.path.exists(marker):
                self.envs[env] = os.path.join(directory, "bin", "python")
                return self.envs[env]
            shutil.rmtree(directory, ignore_errors=True)
            python = super().python_for(env)
            open(marker, "w").close()
            return python
        return super().python_for(env)


# --------------------------------------------------------------------------------------------------
# blocks and recipes
# --------------------------------------------------------------------------------------------------
def key_of(entry: dict, name: str) -> str:
    return f"api:{entry['module']}.{name}" if entry["kind"] == "api" else f"{entry['kind']}:{name}"


def block_sha256(entry: dict) -> str:
    """The digest of a block as it parses (the order of its names does not matter; tests/test_knowledge_owners.py has the same function)."""
    return _canonical_sha256({**entry, "names": sorted(entry["names"])})


def load_items(paths: list, explore: bool) -> list:
    """One item per key of every `[[removed]]` block with owners (every block, with --explore)."""
    items, seen = [], {}
    for path in paths:
        data = tomllib.loads(open(path, encoding="utf-8").read())
        for entry in data.get("removed", []):
            if entry["kind"] not in ("api", "attribute") or (not entry.get("owners") and not explore):
                continue
            for name in entry["names"]:
                key = key_of(entry, name)
                if key in seen:
                    raise SystemExit(f"{key} is defined twice ({seen[key]} and {path})")
                seen[key] = path
                items.append({"key": key, "kind": entry["kind"], "module": entry.get("module", ""), "name": name,
                              "attribute": name.rsplit(".", 1)[-1], "distribution": entry["distribution"],
                              "version": entry["version"], "owners": list(entry.get("owners", [])),
                              "replacement": entry["replacement"], "source": entry["source"],
                              "block_sha256": block_sha256(entry), "source_file": os.path.basename(path)})
    return items


def shipped_entries(path: str) -> dict:
    """The removal index of a knowledge base file, shaped like fixfirst.domain.load()["removed_index"] (key -> entry with its `name`).
    The product's loader overwrites a key that two blocks define; here that is an error."""
    index = {}
    for entry in tomllib.loads(open(path, encoding="utf-8").read()).get("removed", []):
        for name in entry["names"]:
            key = key_of(entry, name)
            if key in index:
                raise SystemExit(f"{path}: {key} is defined by two blocks")
            index[key] = {**entry, "name": name, "id": key}
    return index


def by_attribute(index: dict) -> dict:
    """attribute name -> the api/attribute entries of the index that end in it (what a failing `obj.<name>` can be matched with)."""
    grouped = {}
    for entry in index.values():
        if entry["kind"] in ("api", "attribute"):
            grouped.setdefault(entry["name"].rsplit(".", 1)[-1], []).append(entry)
    return grouped


def declared_owners(entry: dict) -> set:
    """The owners the product matches a receiver with (removal_ownership._owners): explicit `owners`, or the qualified identity of the entry."""
    owners = entry.get("owners", [])
    if not owners:
        owners = [entry.get("module", "") if entry["kind"] == "api" else entry["name"].rpartition(".")[0]]
    return {owner for owner in owners if isinstance(owner, str) and "." in owner and all(part.isidentifier() for part in owner.split("."))}


def authorizing_entries(grouped: dict, attribute: str, result: dict) -> list:
    """Keys of EVERY entry of the knowledge base that the product's rule authorizes for the receiver of this run (not only the key under
    test): a receiver that two entries authorize would be shown the same step twice."""
    return sorted(entry["id"] for entry in grouped.get(attribute, [])
                  if evaluate({"owners": declared_owners(entry), "distribution": entry["distribution"]}, result)["authorized_by"])


def load_recipes(path: str) -> list:
    data = tomllib.loads(open(path, encoding="utf-8").read())
    snippets = data.get("snippets", {})
    recipes = []
    for raw in data["recipe"]:
        classes = raw.get("classes") or [None]
        for cls in classes:
            def fill(text):
                return text.replace("{cls}", cls) if cls else text
            prelude = "".join(snippets[name] for name in raw.get("include", []))
            recipes.append({"keys": [fill(k) for k in raw["keys"]], "setup": prelude + fill(raw["setup"]),
                            "extra": [prelude + fill(text) for text in raw.get("extra", [])],
                            "envs": {role: raw[role] for role in ("before", "after", "later") if role in raw}})
    return recipes


def find_recipe(recipes: list, key: str, strict: bool = True):
    exact = [r for r in recipes if key in r["keys"]]
    if len(exact) > 1:
        raise SystemExit(f"{key} is named by {len(exact)} recipes")
    if exact:
        return exact[0]
    patterns = [r for r in recipes if any(fnmatch.fnmatchcase(key, k) for k in r["keys"] if any(c in k for c in "*?["))]
    if len(patterns) != 1:
        if strict:
            raise SystemExit(f"{key}: {len(patterns)} recipes match (need exactly one)")
        return None
    return patterns[0]


def environments(item: dict, recipe: dict) -> dict:
    """role -> Env: the recipe's override, else the check of verify.py that covers the key."""
    envs = {}
    if recipe["envs"]:
        for role in ("before", "after"):
            if role in recipe["envs"]:
                envs[role] = verify.E(*recipe["envs"][role])
        for number, spec in enumerate(recipe["envs"].get("later", [])):
            envs[f"later{number}"] = verify.E(*spec)
        return envs
    check = next((c for c in list(verify.CHECKS) + list(verify.AUDIT) if item["key"] in c.covers), None)
    if check is None:
        raise SystemExit(f"{item['key']}: no check covers the key and the recipe gives no environments")
    envs["before"], envs["after"] = check.before, check.after
    for number, env in enumerate(check.later):
        envs[f"later{number}"] = env
    return envs


# --------------------------------------------------------------------------------------------------
# evaluation of one run
# --------------------------------------------------------------------------------------------------
def provider_ok(result: dict, top: str, distribution: str) -> bool | None:
    """True/False, or None when the interpreter cannot tell (Python before 3.10 has no packages_distributions)."""
    if "stdlib" not in result:
        return None
    if verify.canon(distribution) == "python":
        return bool(result.get("stdlib", {}).get(top)) and not result["providers"].get(top)
    return {verify.canon(name) for name in result["providers"].get(top, [])} == {verify.canon(distribution)}


def evaluate(item: dict, result: dict) -> dict:
    """What the product's rule would conclude from this run (the same conditions as removal_ownership.evidence_facts)."""
    rows = result.get("rows", [])
    expected = set(item["owners"])
    hits = [row for row in rows if f"{row[0]}.{row[1]}" in expected]
    needs_direct = bool(result.get("dynamic") or result.get("member_present"))
    authorized = []
    for module, owner, direct in hits:
        ok = provider_ok(result, module.split(".")[0], item["distribution"])
        if (not needs_direct or direct) and ok is not False:
            authorized.append(f"{module}.{owner}")
    return {"hits": [f"{m}.{o}{'*' if d else ''}" for m, o, d in hits], "authorized_by": sorted(set(authorized)),
            "needs_direct": needs_direct}


def run_recipe(ws, env, item: dict, setup: str, probe_path: str) -> dict:
    py = ws.python_for(env)
    spec = {"probe": probe_path, "setup": setup, "name": item["attribute"]}
    r = subprocess.run([py, "-I", "-B", "-c", RUNNER], input=json.dumps(spec), capture_output=True, text=True,
                       cwd=ws.neutral, env=ws.env_vars, timeout=600)
    for line in reversed(r.stdout.splitlines()):
        if line.startswith(MARK):
            result = json.loads(line[len(MARK):])
            result["env"] = env.label()
            return result
    return {"env": env.label(), "crash": verify.sanitize((r.stderr or r.stdout)[-600:])}


def installed(ws, env) -> dict:
    """Versions of the distributions the environment carries (from the requirement names)."""
    py = ws.python_for(env)
    names = [re.split(r"[<>=!~\[; ]", p, maxsplit=1)[0] for p in env.pkgs]
    code = ("import json,sys\nimport importlib.metadata as m\nout={}\nfor n in json.loads(sys.argv[1]):\n"
            "    try: out[n]=m.version(n)\n    except Exception: pass\nprint(json.dumps(out))")
    r = subprocess.run([py, "-I", "-B", "-c", code, json.dumps(names)], capture_output=True, text=True, cwd=ws.neutral)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {}


def names_attribute(text, name: str) -> bool:
    """The text names the attribute as a word of its own: a substring is not enough ('failUnless' is inside 'failUnlessEqual', 'c' inside 'Select')."""
    return isinstance(text, str) and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


def python_at_least(version, minimum: tuple) -> bool:
    try:
        return tuple(int(part) for part in str(version).split(".")[:2]) >= minimum
    except ValueError:
        return False


def check_rows(item: dict, runs: dict, phantom_check: bool = True) -> list:
    """Problems of the receiver runs of one key. Empty = pass. `phantom_check`: every declared owner must also be an identity of the
    receiver in some release (a block's own recipe); the receivers of a MERGED key need only be authorized by the entry that covers them."""
    problems = []
    name = item["attribute"]
    seen = set()
    if not runs:
        return ["no release was recorded"]
    for needed in ("before", "after"):
        if needed not in {role.partition("#")[0] for role in runs}:
            problems.append(f"the record holds no run of the '{needed}' release")
    for role, result in runs.items():
        label = f"{role} ({result.get('env')})"
        variant = role.partition("#")[2]
        role = role.partition("#")[0]
        label += f" receiver {variant}" if variant else ""
        if "crash" in result or "setup_error" in result:
            problems.append(f"{label}: the recipe did not run: {result.get('crash') or result.get('setup_error')}")
            continue
        if "probe_error" in result:
            problems.append(f"{label}: the product's probe cannot be loaded here: {result['probe_error']}")
            continue
        if role == "before":
            if result.get("access") != "ok":
                problems.append(f"{label}: expected the attribute to exist before the removal, got {result.get('access')} {result.get('message', '')}")
            continue
        if result.get("access") != "AttributeError" or not names_attribute(result.get("message", ""), name):
            problems.append(f"{label}: expected AttributeError for '{name}', got {result.get('access')} {result.get('message', '')}")
            continue
        if result.get("plain") is not True:
            problems.append(f"{label}: the receiver is not a registered plain class")
        if python_at_least(result.get("python"), (3, 10)) and (not isinstance(result.get("stdlib"), dict) or not isinstance(result.get("providers"), dict)):
            problems.append(f"{label}: no evidence of which distribution provides the module of the owner (the interpreter can tell it since Python 3.10)")
            continue
        verdict = evaluate(item, result)
        seen.update(row.rstrip("*") for row in verdict["hits"])
        if not verdict["authorized_by"]:
            rows = ", ".join(f"{m}.{o}{'*' if d else ''}" for m, o, d in result.get("rows", [])) or "none"
            reason = "the receiver is not a registered plain class" if not result.get("plain") else (
                "no declared owner is an identity of the receiver" if not verdict["hits"]
                else "the receiver is dynamic or already has the member, so only its own class counts" if verdict["needs_direct"]
                else "the module is not provided by the block's distribution")
            problems.append(f"{label}: no declared owner authorizes the receiver ({reason}); receiver identities: {rows}")
    if phantom_check:
        for owner in item["owners"]:
            if owner not in seen:
                problems.append(f"declared owner {owner} is not an identity of the receiver in any release")
    return problems


# --------------------------------------------------------------------------------------------------
# the product itself
# --------------------------------------------------------------------------------------------------
def prepare_source(ws, src_dir: str, merge: list) -> str:
    """A COPY of the fixfirst package (nothing under the repository is touched), optionally with blocks merged into its knowledge base."""
    tmp = os.path.join(ws.base, "ff-src")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(os.path.join(src_dir, "fixfirst"), os.path.join(tmp, "fixfirst"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    kb = os.path.join(tmp, "fixfirst", "knowledge", "domain.toml")
    shipped = tomllib.loads(open(kb, encoding="utf-8").read())
    known = {key_of(e, n) for e in shipped.get("removed", []) for n in e["names"]}
    extra = []
    for path in merge:
        text = open(path, encoding="utf-8").read()
        data = tomllib.loads(text)
        if any(key_of(e, n) in known for e in data.get("removed", []) for n in e["names"]):
            raise SystemExit(f"{path}: a key is already in the knowledge base copy")
        extra.append(text)
    if extra:
        with open(kb, "a", encoding="utf-8") as stream:
            stream.write("\n\n" + "\n\n".join(extra))
    return tmp


def e2e_code(item: dict, setup: str) -> str:
    return setup.rstrip("\n") + f"\nobj.{item['attribute']}\n"


def twin_class(item: dict) -> str:
    """The name of the project class that stands in for the library class (the receiver's class name; a merged key has its own: `twin_class`)."""
    return item.get("twin_class") or (item["module"] if item["kind"] == "api" else item["owners"][0].rsplit(".", 1)[-1])


def twin_code(item: dict) -> str:
    cls = twin_class(item)
    return f"class {cls}:\n    def other(self):\n        return 1\n\nobj = {cls}()\nobj.{item['attribute']}\n"


def run_product(ws, src_copy: str, jobs: list):
    """FixFirst on every job. Returns (id -> record, the modules of the product (relative paths) that the runs loaded)."""
    py = ws.python_for(verify.E("3.13", "pydantic>=2.8,<3", "Jinja2>=3.1,<4", "scikit-learn>=1.5,<2", "packaging>=24.2,<27", "PyYAML>=6,<7"))
    out, loaded = {}, set()
    for start in range(0, len(jobs), 20):
        spec = {"src": src_copy, "items": jobs[start:start + 20]}
        r = subprocess.run([py, "-I", "-B", "-c", E2E_RUNNER], input=json.dumps(spec), capture_output=True, text=True,
                           cwd=ws.neutral, env=ws.env_vars, timeout=3600)
        for line in reversed(r.stdout.splitlines()):
            if line.startswith(MARK):
                batch = json.loads(line[len(MARK):])
                for record in batch["records"]:
                    out[record["id"]] = record
                loaded.update(batch["loaded"])
                break
        else:
            raise verify.EnvError(f"the product run crashed: {(r.stderr or r.stdout)[-800:]}")
    return out, sorted(loaded)


def target_env(envs: dict):
    """The release the product is shown: the newest later release, else the first without the attribute."""
    later = [role for role in envs if role.startswith("later")]
    return (envs[later[-1]], later[-1]) if later else (envs["after"], "after")


def removal_step(item: dict, record: dict, first_only: bool = False) -> bool:
    """The plan holds the removal action of rule P10 for this entry: 'Replace <name>: removed in <distribution> <version>', its text says the
    entry's removal version and carries the replacement text of the entry (all of it). `first_only`: it is the first step, the one the user is shown."""
    steps = record.get("steps", [])
    version = re.escape(str(item["version"]))
    for step in (steps[:1] if first_only else steps):
        if not (isinstance(step, list) and len(step) == 2):
            continue
        title, text = str(step[0]), str(step[1])
        if (re.search(r"^Replace .+: removed in \S+ " + version + "$", title) and f"(removed in {item['version']})" in text
                and item["replacement"] in text):
            return True
    return False


def shows_replacement(item: dict, record: dict) -> bool:
    """Some step of the plan carries the replacement text of the entry."""
    return any(isinstance(step, list) and len(step) == 2 and item["replacement"] in str(step[1]) for step in record.get("steps", []))


def judge_product(item: dict, record, expected_id=None) -> list:
    """FixFirst on a script that ends in `obj.<name>` with a receiver of the library class: exactly this entry, decided by its own rule (not by the
    classifier), and the plan that shows its removal and its replacement."""
    if not isinstance(record, dict):
        return ["no product record"]
    if "error" in record:
        return [f"the product failed on the script: {record['error']}"]
    problems = []
    if expected_id is not None and record.get("id") != expected_id:
        problems.append(f"the product record is the one of {record.get('id')!r}, not of {expected_id!r}")
    owned = record.get("removal_owner", [])
    if item["key"] not in owned:
        problems.append(f"the product did not authorize {item['key']} (authorized: {owned}; issues: {record.get('issues')})")
    elif owned != [item["key"]]:
        problems.append(f"also authorized by the product (overlap): {[k for k in owned if k != item['key']]}")
    rule, issues = RULE_OF_KIND[item["kind"]], record.get("issues", [])
    if not any(isinstance(i, list) and len(i) == 4 and i[1] == "version_incompatibility" and i[2] == "rule" and i[3] == rule
               and names_attribute(i[0], item["attribute"]) for i in issues):
        problems.append(f"no issue about '{item['attribute']}' is diagnosed as a version incompatibility by rule {rule}: {issues}")
    if not removal_step(item, record, first_only=True):
        problems.append("the first step of the plan is not the removal action of the entry ('Replace ...: removed in ...') with its replacement text")
    return problems


def judge_twin(item: dict, twin, expected_id=None) -> list:
    """The project class of the same name: its run must really fail on the attribute of that class (a missing record is not a negative), and the
    product must not authorize it, diagnose it as a version problem or show it the replacement of the library entry."""
    if not isinstance(twin, dict):
        return ["the same-name project class was not run"]
    if "error" in twin:
        return [f"the same-name project class could not be run: {twin['error']}"]
    problems = []
    if expected_id is not None and twin.get("id") != expected_id:
        problems.append(f"the project class record is the one of {twin.get('id')!r}, not of {expected_id!r}")
    issues = twin.get("issues", [])
    cls = twin_class(item)
    if not any(isinstance(i, list) and len(i) > 0 and names_attribute(i[0], item["attribute"]) and f"'{cls}'" in str(i[0]) for i in issues):
        problems.append(f"the project run of the same-name class holds no failure of '{cls}' about '{item['attribute']}' ({issues}): that is no negative evidence")
    if twin.get("removal_owner"):
        problems.append(f"a project class with the same name was authorized: {twin['removal_owner']}")
    if any(isinstance(i, list) and len(i) > 1 and i[1] == "version_incompatibility" for i in issues):
        problems.append(f"a project class with the same name was diagnosed as a version incompatibility: {issues}")
    if shows_replacement(item, twin):
        problems.append("a project class with the same name was shown the replacement of the library entry")
    return problems


def judge_e2e(item: dict, record, twin) -> list:
    return judge_product(item, record) + judge_twin(item, twin)


# --------------------------------------------------------------------------------------------------
# merged keys, and the judgement of a record from what it stores (the run and the offline tests use the same functions)
# --------------------------------------------------------------------------------------------------
def load_merged(dispositions: dict, candidates: dict, index: dict) -> list:
    """The keys of the `[[merged]]` groups of owners/dispositions.toml, each with the enabled entry that covers it.

    `candidates` maps a key to its candidate item (candidates-parked.toml); `index` is the removal index of the shipped knowledge base. The
    covering entry (`target`) is the one entry of the group's covered_by that ends in the same attribute. `view` is the item that check_rows()
    and judge_product() judge the receivers of the merged key with: the covering entry's owners, distribution, version and replacement.
    `problems` holds what is wrong with the relation itself (a unique covering entry of the same attribute, distribution, removal version,
    source and replacement; a different replacement needs a `replacement_note`; a key is merged once)."""
    merged, seen = [], {}
    for number, group in enumerate(dispositions.get("merged", []), 1):
        covered = list(group.get("covered_by", []))
        note = str(group.get("replacement_note", "")).strip()
        shared = []
        if not covered or len(set(covered)) != len(covered):
            shared.append(f"covered_by of group {number} is empty or names an entry twice")
        if not str(group.get("why", "")).strip():
            shared.append(f"group {number} says nothing about why it is merged")
        for key in group.get("keys", []):
            entry = {"key": key, "group": number, "target": None, "source": None, "view": None, "problems": list(shared),
                     "replacement_note": note}
            if key in seen:
                entry["problems"].append(f"{key} is merged twice (groups {seen[key]} and {number})")
            seen[key] = number
            source = candidates.get(key)
            if source is None:
                entry["problems"].append(f"{key} is not a candidate of candidates-parked.toml")
                merged.append(entry)
                continue
            entry["source"] = source
            targets = [t for t in covered if t.rsplit(".", 1)[-1] == source["attribute"]]
            if len(targets) != 1:
                entry["problems"].append(f"{key}: covered_by must hold exactly one entry that ends in '{source['attribute']}', it holds {targets}")
                merged.append(entry)
                continue
            target = index.get(targets[0])
            entry["target"] = targets[0]
            if target is None or target["kind"] not in ("api", "attribute"):
                entry["problems"].append(f"{key}: {targets[0]} is not an enabled api/attribute entry")
                merged.append(entry)
                continue
            for field, same in (("distribution", verify.canon(target["distribution"]) == verify.canon(source["distribution"])),
                                ("version", target["version"] == source["version"]), ("source", target["source"] == source["source"])):
                if not same:
                    entry["problems"].append(f"{key} and {targets[0]} differ in {field}: the covering entry is not the same removal")
            if target["replacement"] != source["replacement"] and not note:
                entry["problems"].append(f"{key} and {targets[0]} give different replacements and the group has no replacement_note")
            if target["replacement"] == source["replacement"] and note:
                entry["problems"].append(f"group {number} has a replacement_note but the replacements are identical")
            if not declared_owners(target):
                entry["problems"].append(f"{targets[0]} has no qualified owner that could authorize a receiver")
            entry["view"] = {"key": targets[0], "kind": target["kind"], "module": source["module"], "name": source["name"], "twin_class": source["module"],
                             "attribute": source["attribute"], "distribution": target["distribution"], "version": target["version"],
                             "owners": sorted(declared_owners(target)), "replacement": target["replacement"],
                             "block_sha256": block_sha256({k: v for k, v in target.items() if k not in ("name", "id")})}
            merged.append(entry)
    return merged


def decode_release(raw: dict) -> dict:
    """A release record as the receipt stores it, in the shape evaluate() and check_rows() take (rows: [module, owner, direct])."""
    run = dict(raw)
    rows = []
    for row in raw.get("rows", []):
        module, _, owner = row.rstrip("*").rpartition(".")
        rows.append([module, owner, row.endswith("*")])
    run["rows"] = rows
    return run


def expected_releases(recipe: dict, envs: dict) -> dict:
    """role -> label of the environment of every release a record must hold: the first receiver, and each further one (`#n`), in every release."""
    return {(role if number == 0 else f"{role}#{number}"): env.label()
            for number in range(1 + len(recipe["extra"])) for role, env in envs.items()}


def judge_releases(item: dict, recipe: dict, envs: dict, result: dict, grouped: dict, phantom_check: bool = True) -> list:
    """The receiver runs of a record, judged again: the releases are exactly those the recipe and the verifying checks call for (each with
    the stored identities the rule would have produced), the lookup behaves, the declared owner authorizes the receiver, and no other entry of
    the knowledge base authorizes it."""
    problems = []
    expected = expected_releases(recipe, envs)
    releases = result.get("releases")
    releases = releases if isinstance(releases, dict) else {}
    if set(releases) != set(expected):
        problems.append(f"the record holds the releases {sorted(releases)}, expected {sorted(expected)}")
    for role, label in expected.items():
        if role in releases and releases[role].get("env") != label:
            problems.append(f"release {role} ran in {releases[role].get('env')!r}, expected {label!r}")
    runs = {role: decode_release(raw) for role, raw in releases.items() if role in expected}
    for role in runs:
        env, run = envs[role.partition("#")[0]], runs[role]
        if "crash" in run or "setup_error" in run or "probe_error" in run:
            continue
        if not str(run.get("python", "")).startswith(env.python + "."):
            problems.append(f"release {role} ran on Python {run.get('python')!r}, the environment is {env.label()!r}")
        installed_versions = {verify.canon(name): version for name, version in (run.get("dists") or {}).items()} if isinstance(run.get("dists"), dict) else {}
        for requirement in env.pkgs:
            match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?(?:\s*[<>=!~;].*)?", requirement.strip())
            if not match:
                continue
            name = verify.canon(match.group(1))
            pinned = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9.!+_-]+)", requirement.strip())
            if name not in installed_versions:
                problems.append(f"release {role}: the record does not say which version of {match.group(1)} ran")
            elif pinned and installed_versions[name] != pinned.group(1):
                problems.append(f"release {role}: {match.group(1)} {installed_versions[name]} ran, the environment pins {pinned.group(1)}")
    problems += check_rows(item, runs, phantom_check)
    for role, run in runs.items():
        if "rows" not in run or "crash" in run or "setup_error" in run:
            continue
        if sorted(run.get("authorized_by", [])) != evaluate(item, run)["authorized_by"]:
            problems.append(f"release {role}: the stored authorization differs from the one the rule gives for the stored identities")
        if role.partition("#")[0] != "before" and run.get("access") == "AttributeError":
            entries = authorizing_entries(grouped, item["attribute"], run)
            if entries != [item["key"]]:
                problems.append(f"release {role}: the receiver is authorized by {entries}, not by exactly {item['key']}")
    return problems


def judge_result(item: dict, recipe: dict, envs: dict, result: dict, grouped: dict, with_product: bool = True) -> list:
    """Judge the record of one shipped key again from what it stores (`with_product`: the run of the product too)."""
    problems = []
    for field in ("key", "kind", "distribution", "version", "owners", "block_sha256"):
        if result.get(field) != item[field]:
            problems.append(f"the record's {field} ({result.get(field)!r}) is not that of the shipped block ({item[field]!r})")
    if (result.get("recipe") != recipe["setup"] or result.get("extra_receivers") != recipe["extra"]
            or result.get("recipe_sha256") != hashlib.sha256("\n@@\n".join([recipe["setup"], *recipe["extra"]]).encode("utf-8")).hexdigest()):
        problems.append("the recipe of the record is not the recipe of recipes.toml")
    problems += judge_releases(item, recipe, envs, result, grouped)
    return problems + (judge_product_runs(item, recipe, envs, result, result.get("key"), "", "twin:") if with_product else [])


def judge_product_runs(item: dict, recipe: dict, envs: dict, result: dict, job_key, prefix: str, twin_prefix: str) -> list:
    """The runs of FixFirst of a record: the release it was shown, the receiver (and each further one) and the project class of the same name,
    each the record of the job that was meant (the job ids are `<prefix><key>`, `<prefix><key>#<n>` and `<twin prefix><key>`)."""
    product = result.get("product")
    if not isinstance(product, dict):
        return ["the record holds no run of the product"]
    problems = []
    if product.get("release") != target_env(envs)[1]:
        problems.append(f"the product ran in release {product.get('release')}, expected {target_env(envs)[1]}")
    problems += judge_product(item, product.get("product"), f"{prefix}{job_key}") + judge_twin(item, product.get("twin"), f"{twin_prefix}{job_key}")
    extras = product.get("extra")
    if not isinstance(extras, list) or len(extras) != len(recipe["extra"]):
        problems.append(f"the product record holds {len(extras) if isinstance(extras, list) else 0} further receivers, the recipe has {len(recipe['extra'])}")
    else:
        for number, record in enumerate(extras, 1):
            problems += [f"receiver {number}: {p}" for p in judge_product(item, record, f"{prefix}{job_key}#{number}")]
    return problems


def judge_merged_result(entry: dict, recipe: dict, envs: dict, result: dict, grouped: dict, with_product: bool = True) -> list:
    """Judge the record of a merged key again: the receiver of the MERGED key, authorized by the covering entry and by no other."""
    problems = list(entry["problems"])
    view = entry["view"]
    if view is None:
        return problems
    for field, wanted in (("key", entry["key"]), ("target", entry["target"]), ("distribution", view["distribution"]), ("version", view["version"]),
                          ("owners", view["owners"]), ("source_block_sha256", entry["source"]["block_sha256"]),
                          ("target_block_sha256", view["block_sha256"]), ("replacement_note", entry["replacement_note"])):
        if result.get(field) != wanted:
            problems.append(f"the record's {field} ({result.get(field)!r}) is not {wanted!r}")
    if (result.get("recipe") != recipe["setup"] or result.get("extra_receivers") != recipe["extra"]
            or result.get("recipe_sha256") != hashlib.sha256("\n@@\n".join([recipe["setup"], *recipe["extra"]]).encode("utf-8")).hexdigest()):
        problems.append("the recipe of the record is not the recipe of recipes.toml")
    problems += judge_releases(view, recipe, envs, result, grouped, phantom_check=False)
    releases = result.get("releases") if isinstance(result.get("releases"), dict) else {}
    cls = view["twin_class"]
    for role, raw in releases.items():
        if not isinstance(raw, dict) or "crash" in raw or "setup_error" in raw or "probe_error" in raw:
            continue
        kind = raw.get("type")
        if not (isinstance(kind, list) and len(kind) == 2 and kind[1] == cls):
            problems.append(f"release {role}: the receiver is a {kind!r}, not an object of the merged class {cls}")
        elif role.partition("#")[0] != "before" and not any(isinstance(row, str) and row.endswith("*") and row.rstrip("*").rpartition(".")[2] == cls
                                                            for row in raw.get("rows", [])):
            problems.append(f"release {role}: the identities of the receiver do not include its own class {cls}")
    return problems + (judge_product_runs(view, recipe, envs, result, entry["key"], "merged:", "mtwin:") if with_product else [])


def _same(value, wanted) -> bool:
    """Equal and of the same type (True is not 1, False is not 0)."""
    return type(value) is type(wanted) and value == wanted


def _passes(record: dict) -> bool:
    return record.get("status") == "pass" and isinstance(record.get("problems"), list) and record["problems"] == []


def audit_receipt(receipt: dict, items: list, recipes: list, index: dict, merged: list) -> list:
    """Every problem the receipt has when it is judged again from the details it stores. [] means the verdict and the evidence agree.

    items = load_items([shipped domain.toml]) (the blocks with owners), recipes = load_recipes(...), index = shipped_entries(domain.toml),
    merged = load_merged(...). Nothing here needs the network or an interpreter other than this one."""
    problems = []
    if not isinstance(receipt, dict) or not isinstance(receipt.get("results"), list) or not isinstance(receipt.get("merged"), list):
        return ["the receipt holds no list of results and no list of merged records"]
    grouped = by_attribute(index)

    def by_key(records: list, label: str) -> dict:
        found = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("key"), str):
                problems.append(f"the receipt holds a {label} that is not the record of a key")
                continue
            found.setdefault(record["key"], []).append(record)
        for key, several in sorted(found.items()):
            if len(several) > 1:
                problems.append(f"{key}: the receipt holds {len(several)} {label}s of the key")
        return found

    seen = by_key(receipt["results"], "record")
    for key in sorted(set(seen) - {item["key"] for item in items}):
        problems.append(f"{key}: a record of a key that is not shipped with owners")
    for item in items:
        records = seen.get(item["key"], [])
        if not records:
            problems.append(f"{item['key']}: has owners but no record")
            continue
        recipe = find_recipe(recipes, item["key"], strict=False)
        if recipe is None:
            problems.append(f"{item['key']}: no recipe")
            continue
        try:
            found = judge_result(item, recipe, environments(item, recipe), records[0], grouped)
        except Exception as error:      # a malformed record is a problem of the record, not a crash of the audit
            found = [f"the record cannot be judged ({type(error).__name__}: {error})"]
        if not _passes(records[0]):
            found.append("the record is not a pass")
        problems += [f"{item['key']}: {p}" for p in found]
    records_of_merged = by_key(receipt["merged"], "merged record")
    for key in sorted(set(records_of_merged) - {m["key"] for m in merged}):
        problems.append(f"{key}: a merged record of a key that no [[merged]] group names")
    for entry in merged:
        records = records_of_merged.get(entry["key"], [])
        if not records:
            problems.append(f"{entry['key']}: is merged but has no record")
            continue
        source = entry["source"]
        recipe = find_recipe(recipes, entry["key"], strict=False) if source else None
        if recipe is None:
            problems.append(f"{entry['key']}: no recipe for the receiver of the merged key")
            continue
        try:
            found = judge_merged_result(entry, recipe, environments(source, recipe), records[0], grouped)
        except Exception as error:
            found = [f"the record cannot be judged ({type(error).__name__}: {error})"]
        if not _passes(records[0]):
            found.append("the record is not a pass")
        problems += [f"{entry['key']} (merged): {p}" for p in found]
    summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}
    passed = sum(1 for records in seen.values() for r in records if _passes(r))
    merged_passed = sum(1 for records in records_of_merged.values() for r in records if _passes(r))
    for field, wanted_value in (("keys", len(items)), ("passed", passed), ("failed", len(seen) - passed),
                                ("e2e", True), ("reference", True)):
        if not _same(summary.get(field), wanted_value):
            problems.append(f"summary.{field} is {summary.get(field)!r}, the records say {wanted_value!r}")
    if not isinstance(summary.get("merged"), dict) or not (_same(summary["merged"].get("keys"), len(merged)) and _same(summary["merged"].get("passed"), merged_passed)):
        problems.append(f"summary.merged is {summary.get('merged')!r}, the records say {{'keys': {len(merged)}, 'passed': {merged_passed}}}")
    if len(seen) != len(items) or passed != len(items) or not _same(summary.get("failed"), 0):
        problems.append("the receipt is not a complete pass")
    return problems


# --------------------------------------------------------------------------------------------------
def run_releases(ws, probe: str, item: dict, recipe: dict, envs: dict) -> dict:
    """The receiver runs of one key: the recipe (and each further receiver, `#n`) in every release."""
    runs = {}
    for number, setup in enumerate([recipe["setup"], *recipe["extra"]]):
        for role, env in envs.items():
            name = role if number == 0 else f"{role}#{number}"
            try:
                runs[name] = run_recipe(ws, env, item, setup, probe)
            except verify.MissingInterpreter as error:
                runs[name] = {"env": env.label(), "crash": f"NOT CHECKED: {error}"}
            except verify.EnvError as error:
                runs[name] = {"env": env.label(), "crash": str(error)[:400]}
    return runs


def release_records(ws, item: dict, envs: dict, runs: dict) -> dict:
    """The runs as the receipt stores them (redacted; rows as 'module.owner', '*' = the receiver's own class)."""
    versions = ws.__dict__.setdefault("_owners_dists", {})

    def dists(env) -> dict:
        key = (env.python, env.pkgs, env.only_binary)
        if key not in versions:
            versions[key] = installed(ws, env)
        return versions[key]

    return {role: {**verify._clean({k: v for k, v in runs[role].items() if k != "rows"}),
                   "rows": [f"{m}.{o}{'*' if d else ''}" for m, o, d in runs[role].get("rows", [])],
                   "authorized_by": evaluate(item, runs[role])["authorized_by"] if "rows" in runs[role] else [],
                   "dists": dists(envs[role.partition("#")[0]])} for role in runs}


def recipe_fields(recipe: dict) -> dict:
    return {"recipe_sha256": hashlib.sha256("\n@@\n".join([recipe["setup"], *recipe["extra"]]).encode("utf-8")).hexdigest(),
            "recipe": recipe["setup"], "extra_receivers": recipe["extra"]}


def extend_index(path: str, merge: list) -> dict:
    """The removal index of the knowledge base the product runs on: the shipped one plus the blocks of --merge."""
    index = shipped_entries(path)
    for extra in merge:
        for key, entry in shipped_entries(extra).items():
            if key in index:
                raise SystemExit(f"{extra}: {key} is already in the knowledge base copy")
            index[key] = entry
    return index


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixfirst-src", required=True, help="directory that contains the `fixfirst` package (read only)")
    ap.add_argument("--blocks", nargs="+", help="TOML file(s) whose [[removed]] blocks are verified (default: the shipped domain.toml)")
    ap.add_argument("--merge", nargs="*", default=[], help="TOML file(s) merged into a COPY of the knowledge base before the product runs "
                                                           "(blocks that are not shipped yet)")
    ap.add_argument("--recipes", default=os.path.join(HERE, "owners", "recipes.toml"))
    ap.add_argument("--dispositions", default=os.path.join(HERE, "owners", "dispositions.toml"),
                    help="the [[merged]] groups of this file are verified too (reference run)")
    ap.add_argument("--merged-candidates", default=os.path.join(HERE, "candidates", "candidates-parked.toml"),
                    help="the file that holds the blocks the [[merged]] keys come from")
    ap.add_argument("--no-merged", action="store_true", help="skip the merged keys")
    ap.add_argument("--only", default="", help="verify only keys that contain one of these texts (separated by '|')")
    ap.add_argument("--explore", action="store_true", help="print what the product sees for each key; do not judge")
    ap.add_argument("--explore-json", help="with --explore: also write every run to this JSON file")
    ap.add_argument("--no-e2e", action="store_true", help="skip the runs of FixFirst itself")
    ap.add_argument("--receipts", help="write the full, redacted record to this JSON file")
    ap.add_argument("--keep-envs", action="store_true")
    ap.add_argument("--base", help="directory for the throwaway environments; with it they are kept and reused (authoring)")
    a = ap.parse_args(argv)
    t0 = time.time()
    src = os.path.abspath(a.fixfirst_src)
    package = os.path.join(src, "fixfirst")
    probe = os.path.join(package, "_runtime_evidence.py")
    domain_toml = os.path.join(package, "knowledge", "domain.toml")
    blocks = a.blocks or [domain_toml]
    wanted = a.only.split("|")
    # a reference run verifies every block of the shipped knowledge base that has owners, and every merged key, with the product
    reference = not (a.blocks or a.merge or a.only or a.explore or a.no_e2e or a.no_merged or a.base)
    items = [i for i in load_items(blocks, a.explore) if any(text in i["key"] for text in wanted)]
    recipes = load_recipes(a.recipes)
    index = extend_index(domain_toml, [os.path.abspath(p) for p in a.merge])
    grouped = by_attribute(index)
    merged = []
    if not a.explore and not a.no_merged and not a.blocks:
        candidates = {i["key"]: i for i in load_items([a.merged_candidates], True)}
        dispositions = tomllib.loads(open(a.dispositions, encoding="utf-8").read())
        merged = [m for m in load_merged(dispositions, candidates, index) if any(text in m["key"] or text in str(m["target"]) for text in wanted)]
    if a.base:
        os.makedirs(a.base, exist_ok=True)
        ws = PersistentWorkspace(base=os.path.abspath(a.base), keep=True)
    else:
        ws = verify.Workspace(keep=a.keep_envs)
    lines = []

    def out(text=""):
        text = verify.sanitize(text)
        lines.append(text)
        print(text, flush=True)

    out("FixFirst knowledge owners: verification log")
    out(f"generated   : {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC by verify_owners.py")
    out(f"tooling     : {subprocess.run([verify.UV, '--version'], capture_output=True, text=True).stdout.strip()}; Python {sys.version.split()[0]}")
    out(f"keys        : {len(items)} from {', '.join(os.path.basename(b) for b in blocks)}")
    out(f"merged keys : {len(merged)}")
    records, merged_records, results = {}, {}, []
    try:
        if a.explore:                       # blocks without a recipe (most of the shipped knowledge base) are simply not explored
            items = [i for i in items if find_recipe(recipes, i["key"], strict=False)]
        for number, item in enumerate(items, 1):
            recipe = find_recipe(recipes, item["key"])
            envs = environments(item, recipe)
            runs = run_releases(ws, probe, item, recipe, envs)
            records[item["key"]] = (item, recipe, envs, runs)
            if not a.explore:
                print(f"[{number}/{len(items)}] {item['key']}: {len(runs)} releases", file=sys.stderr, flush=True)
            if a.explore:
                out(f"\n[{number}/{len(items)}] {item['key']}  ({item['distribution']} {item['version']}; owners {item['owners'] or '-'})")
                for role, result in runs.items():
                    if "crash" in result or "setup_error" in result or "probe_error" in result:
                        out(f"    {role:7} {result.get('env')}: {result.get('crash') or result.get('setup_error') or result.get('probe_error')}")
                        continue
                    shown = ", ".join(f"{m}.{o}{'*' if d else ''}" for m, o, d in result["rows"]) or "(no identity)"
                    flags = f"plain={result['plain']} dynamic={result.get('dynamic')} present={result.get('member_present')}"
                    out(f"    {role:7} {result['env']}: {result['access']}; type {'.'.join(result['type'])}; {flags}")
                    out(f"            rows: {shown}")
                    out(f"            providers: {result.get('providers')}")
        for number, entry in enumerate(merged, 1):
            if entry["view"] is None:
                continue
            recipe = find_recipe(recipes, entry["key"])
            envs = environments(entry["source"], recipe)
            merged_records[entry["key"]] = (entry, recipe, envs, run_releases(ws, probe, entry["source"], recipe, envs))
            print(f"[merged {number}/{len(merged)}] {entry['key']} -> {entry['target']}", file=sys.stderr, flush=True)
    except BaseException:
        ws.close()
        raise
    if a.explore:
        if a.explore_json:
            with open(a.explore_json, "w", encoding="utf-8") as stream:
                json.dump({key: {"item": item, "runs": runs} for key, (item, recipe, envs, runs) in records.items()}, stream, indent=1)
        ws.close()
        return 0

    product, loaded_modules = {}, []
    if not a.no_e2e:
        out("\nrunning FixFirst on every key (this starts the target interpreters)")
        jobs = []
        prepared = set()

        def target_python(envs: dict) -> str:
            env, _role = target_env(envs)
            python = ws.python_for(env)
            if python not in prepared:
                subprocess.run([verify.UV, "pip", "install", "--quiet", "--python", python, "pip"], capture_output=True, env=ws.env_vars)
                prepared.add(python)
            return python

        for key, (item, recipe, envs, runs) in records.items():
            python = target_python(envs)
            jobs.append({"id": key, "python": python, "code": e2e_code(item, recipe["setup"])})
            for number_v, setup in enumerate(recipe["extra"], 1):
                jobs.append({"id": f"{key}#{number_v}", "python": python, "code": e2e_code(item, setup)})
            jobs.append({"id": "twin:" + key, "python": python, "code": twin_code(item)})
        for key, (entry, recipe, envs, runs) in merged_records.items():
            python = target_python(envs)
            jobs.append({"id": "merged:" + key, "python": python, "code": e2e_code(entry["view"], recipe["setup"])})
            for number_v, setup in enumerate(recipe["extra"], 1):
                jobs.append({"id": f"merged:{key}#{number_v}", "python": python, "code": e2e_code(entry["view"], setup)})
            jobs.append({"id": "mtwin:" + key, "python": python, "code": twin_code(entry["source"])})
        src_copy = prepare_source(ws, src, [os.path.abspath(p) for p in a.merge])
        product, loaded_modules = run_product(ws, src_copy, jobs)

    def product_record(prefix: str, twin_prefix: str, key: str, envs: dict, recipe: dict):
        if a.no_e2e:
            return None
        extra = [product.get(f"{prefix}{key}#{n}", {"error": "no result"}) for n in range(1, len(recipe["extra"]) + 1)]
        return verify._clean({"release": target_env(envs)[1], "product": product.get(prefix + key, {"error": "no result"}),
                              "twin": product.get(twin_prefix + key, {"error": "no result"}), "extra": extra})

    failed = 0
    for key, (item, recipe, envs, runs) in records.items():
        result = {"key": key, "kind": item["kind"], "distribution": item["distribution"], "version": item["version"], "owners": item["owners"],
                  "block_sha256": item["block_sha256"], **recipe_fields(recipe), "status": None, "problems": None,
                  "releases": release_records(ws, item, envs, runs), "product": product_record("", "twin:", key, envs, recipe)}
        problems = judge_result(item, recipe, envs, result, grouped, with_product=not a.no_e2e)
        result["status"], result["problems"] = ("pass" if not problems else "fail"), verify._clean(problems)
        failed += bool(problems)
        out(f"\n{result['status'].upper():5} {key}  owners={item['owners']}")
        for role, release in result["releases"].items():
            if "rows" in runs[role]:
                out(f"      {role:7} {release['env']}: {release['access']}; authorized by {release['authorized_by'] or 'nobody'}")
        for problem in problems:
            out(f"      PROBLEM: {problem}")
        results.append(result)
    merged_results = []
    for entry in merged:
        view = entry["view"]
        if entry["key"] not in merged_records:        # the relation itself is wrong: there is nothing to run
            out(f"\nFAIL  {entry['key']} (merged)")
            for problem in entry["problems"]:
                out(f"      PROBLEM: {problem}")
            failed += 1
            continue
        _entry, recipe, envs, runs = merged_records[entry["key"]]
        result = {"key": entry["key"], "target": entry["target"], "kind": view["kind"],
                  "distribution": view["distribution"], "version": view["version"], "owners": view["owners"],
                  "source_block_sha256": entry["source"]["block_sha256"], "target_block_sha256": view["block_sha256"],
                  "replacement_note": entry["replacement_note"], **recipe_fields(recipe), "status": None, "problems": None,
                  "releases": release_records(ws, view, envs, runs), "product": product_record("merged:", "mtwin:", entry["key"], envs, recipe)}
        problems = judge_merged_result(entry, recipe, envs, result, grouped, with_product=not a.no_e2e)
        result["status"], result["problems"] = ("pass" if not problems else "fail"), verify._clean(problems)
        failed += bool(problems)
        out(f"\n{result['status'].upper():5} {entry['key']} (merged into {entry['target']})")
        for role, release in result["releases"].items():
            if "rows" in runs[role]:
                out(f"      {role:7} {release['env']}: {release['access']}; authorized by {release['authorized_by'] or 'nobody'}")
        for problem in problems:
            out(f"      PROBLEM: {problem}")
        merged_results.append(result)
    passed_merged = sum(1 for r in merged_results if r["status"] == "pass")
    out(f"\n{len(records) - sum(1 for r in results if r['status'] != 'pass')} of {len(records)} keys and "
        f"{passed_merged} of {len(merged)} merged keys passed in {time.time() - t0:.0f} s")
    if a.receipts:
        receipt = {
            "summary": {"keys": len(records), "passed": sum(1 for r in results if r["status"] == "pass"),
                        "failed": sum(1 for r in results if r["status"] != "pass"), "e2e": not a.no_e2e, "reference": reference,
                        "merged": {"keys": len(merged), "passed": passed_merged}},
            "tool": {"verify_owners_py_sha256": hashlib.sha256(open(__file__, "rb").read().replace(b"\r\n", b"\n")).hexdigest(),
                     "recipes_sha256": data_sha256(a.recipes),
                     **product_digests(package, loaded_modules),
                     "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "python": sys.version.split()[0]},
            "results": results, "merged": merged_results}
        text = json.dumps(receipt, indent=1, ensure_ascii=False) + "\n"
        leaked = verify.leaked_paths(text)
        if leaked:
            out(f"LEAK: the receipt contains local paths: {leaked[:3]}")
            failed += 1
        if reference:       # judge the receipt as it is stored, with the functions the offline tests use
            audit = audit_receipt(json.loads(text), load_items([domain_toml], False), recipes, index, merged)
            for problem in audit:
                out(f"AUDIT: {problem}")
            out(f"audit of the stored receipt: {len(audit)} problems")
            failed += bool(audit)
        with open(a.receipts, "w", encoding="utf-8") as stream:
            stream.write(text)
    ws.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

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
    authorized (a `removal_owner` fact; a second entry that matches the same receiver would show the same step twice) and the
    issue must be a version incompatibility; and a project class of the same name that calls the same attribute must NOT be
    authorized or diagnosed as a version problem.

It does not prove that a replacement text is right (verify.py's probes do that for some blocks) and it does not prove that every failing
statement in the wild is observable. The recipes exercise the simplest shape, `obj.<name>`. The product observes the receiver of a failing
attribute load that is a name or an attribute of a name (`engine.t()`, `self.engine.t()`), but not a call result (`make_engine().t()`), not a
decorator line (`@app.t`) and not a lookup that fails inside a library; and only for classes that a module holds under their qualified name
and that have at most 16 base classes. A block that cannot be authorized for `obj.<name>` stays parked.

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
import json
import os
import re
import shutil
import subprocess
import sys
import time
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
print(MARK + json.dumps(results))
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
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


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
                              "block_sha256": block_sha256(entry), "source_file": os.path.basename(path)})
    return items


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


def check_rows(item: dict, runs: dict) -> list:
    """Problems of the receiver runs of one key. Empty = pass."""
    problems = []
    name = item["attribute"]
    seen = set()
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
        if result.get("access") != "AttributeError" or name not in result.get("message", ""):
            problems.append(f"{label}: expected AttributeError for '{name}', got {result.get('access')} {result.get('message', '')}")
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


def twin_code(item: dict) -> str:
    cls = item["module"] if item["kind"] == "api" else item["owners"][0].rsplit(".", 1)[-1]
    return f"class {cls}:\n    def other(self):\n        return 1\n\nobj = {cls}()\nobj.{item['attribute']}\n"


def run_product(ws, src_copy: str, jobs: list) -> dict:
    py = ws.python_for(verify.E("3.13", "pydantic>=2.8,<3", "Jinja2>=3.1,<4", "scikit-learn>=1.5,<2", "packaging>=24.2,<27", "PyYAML>=6,<7"))
    out = {}
    for start in range(0, len(jobs), 20):
        spec = {"src": src_copy, "items": jobs[start:start + 20]}
        r = subprocess.run([py, "-I", "-B", "-c", E2E_RUNNER], input=json.dumps(spec), capture_output=True, text=True,
                           cwd=ws.neutral, env=ws.env_vars, timeout=3600)
        for line in reversed(r.stdout.splitlines()):
            if line.startswith(MARK):
                for record in json.loads(line[len(MARK):]):
                    out[record["id"]] = record
                break
        else:
            raise verify.EnvError(f"the product run crashed: {(r.stderr or r.stdout)[-800:]}")
    return out


def target_env(envs: dict):
    """The release the product is shown: the newest later release, else the first without the attribute."""
    later = [role for role in envs if role.startswith("later")]
    return (envs[later[-1]], later[-1]) if later else (envs["after"], "after")


def judge_e2e(item: dict, record: dict, twin: dict) -> list:
    problems = []
    if "error" in record:
        return [f"the product failed on the script: {record['error']}"]
    if item["key"] not in record.get("removal_owner", []):
        problems.append(f"the product did not authorize {item['key']} (authorized: {record.get('removal_owner')}; issues: {record.get('issues')})")
    elif not any(i[1] == "version_incompatibility" for i in record.get("issues", [])):
        problems.append("the key is authorized but the issue is not diagnosed as a version incompatibility")
    others = [k for k in record.get("removal_owner", []) if k != item["key"]]
    if others:
        problems.append(f"also authorized by the product (overlap): {others}")
    if twin is None or "error" in twin:
        problems.append(f"the same-name project class could not be run: {(twin or {}).get('error')}")
    else:
        if twin.get("removal_owner"):
            problems.append(f"a project class with the same name was authorized: {twin['removal_owner']}")
        if any(i[1] == "version_incompatibility" for i in twin.get("issues", [])):
            problems.append(f"a project class with the same name was diagnosed as a version incompatibility: {twin['issues']}")
    return problems


# --------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixfirst-src", required=True, help="directory that contains the `fixfirst` package (read only)")
    ap.add_argument("--blocks", nargs="+", help="TOML file(s) whose [[removed]] blocks are verified (default: the shipped domain.toml)")
    ap.add_argument("--merge", nargs="*", default=[], help="TOML file(s) merged into a COPY of the knowledge base before the product runs "
                                                           "(blocks that are not shipped yet)")
    ap.add_argument("--recipes", default=os.path.join(HERE, "owners", "recipes.toml"))
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
    probe = os.path.join(src, "fixfirst", "_runtime_evidence.py")
    blocks = a.blocks or [os.path.join(src, "fixfirst", "knowledge", "domain.toml")]
    wanted = a.only.split("|")
    items = [i for i in load_items(blocks, a.explore) if any(text in i["key"] for text in wanted)]
    recipes = load_recipes(a.recipes)
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
    records, results = {}, []
    try:
        if a.explore:                       # blocks without a recipe (most of the shipped knowledge base) are simply not explored
            items = [i for i in items if find_recipe(recipes, i["key"], strict=False)]
        for number, item in enumerate(items, 1):
            recipe = find_recipe(recipes, item["key"])
            envs = environments(item, recipe)
            runs = {}
            for number_v, setup in enumerate([recipe["setup"], *recipe["extra"]]):
                for role, env in envs.items():
                    name = role if number_v == 0 else f"{role}#{number_v}"
                    try:
                        runs[name] = run_recipe(ws, env, item, setup, probe)
                    except verify.MissingInterpreter as error:
                        runs[name] = {"env": env.label(), "crash": f"NOT CHECKED: {error}"}
                    except verify.EnvError as error:
                        runs[name] = {"env": env.label(), "crash": str(error)[:400]}
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
    except BaseException:
        ws.close()
        raise
    if a.explore:
        if a.explore_json:
            with open(a.explore_json, "w", encoding="utf-8") as stream:
                json.dump({key: {"item": item, "runs": runs} for key, (item, recipe, envs, runs) in records.items()}, stream, indent=1)
        ws.close()
        return 0

    problems_by_key = {key: check_rows(item, runs) for key, (item, recipe, envs, runs) in records.items()}
    e2e = {}
    if not a.no_e2e:
        out("\nrunning FixFirst on every key (this starts the target interpreters)")
        jobs = []
        for key, (item, recipe, envs, runs) in records.items():
            env, role = target_env(envs)
            python = ws.python_for(env)
            subprocess.run([verify.UV, "pip", "install", "--quiet", "--python", python, "pip"], capture_output=True, env=ws.env_vars)
            jobs.append({"id": key, "python": python, "code": e2e_code(item, recipe["setup"])})
            for number_v, setup in enumerate(recipe["extra"], 1):
                jobs.append({"id": f"{key}#{number_v}", "python": python, "code": e2e_code(item, setup)})
            jobs.append({"id": "twin:" + key, "python": python, "code": twin_code(item)})
        src_copy = prepare_source(ws, src, [os.path.abspath(p) for p in a.merge])
        product = run_product(ws, src_copy, jobs)
        for key, (item, recipe, envs, runs) in records.items():
            problems_by_key[key] += judge_e2e(item, product.get(key, {"error": "no result"}), product.get("twin:" + key))
            extra = [product.get(f"{key}#{n}", {"error": "no result"}) for n in range(1, len(recipe["extra"]) + 1)]
            for number_v, record in enumerate(extra, 1):
                problems_by_key[key] += [f"receiver {number_v}: {p}" for p in judge_e2e(item, record, product.get("twin:" + key))
                                         if "project class" not in p]
            e2e[key] = {"release": target_env(envs)[1], "product": product.get(key), "twin": product.get("twin:" + key), "extra": extra}

    failed = 0
    for key, (item, recipe, envs, runs) in records.items():
        problems = problems_by_key[key]
        status = "pass" if not problems else "fail"
        failed += bool(problems)
        out(f"\n{status.upper():5} {key}  owners={item['owners']}")
        for role, result in runs.items():
            if "rows" in result:
                verdict = evaluate(item, result)
                out(f"      {role:7} {result['env']}: {result['access']}; authorized by {verdict['authorized_by'] or 'nobody'}")
        for problem in problems:
            out(f"      PROBLEM: {problem}")
        results.append({
            "key": key, "kind": item["kind"], "distribution": item["distribution"], "version": item["version"], "owners": item["owners"],
            "block_sha256": item["block_sha256"], "recipe_sha256": hashlib.sha256("\n@@\n".join([recipe["setup"], *recipe["extra"]]).encode("utf-8")).hexdigest(),
            "recipe": recipe["setup"], "extra_receivers": recipe["extra"], "status": status, "problems": verify._clean(problems),
            "releases": {role: {**verify._clean({k: v for k, v in runs[role].items() if k != "rows"}),
                                "rows": [f"{m}.{o}{'*' if d else ''}" for m, o, d in runs[role].get("rows", [])],
                                "authorized_by": evaluate(item, runs[role])["authorized_by"] if "rows" in runs[role] else [],
                                "dists": installed(ws, envs[role.partition("#")[0]])} for role in runs},
            "product": verify._clean(e2e.get(key)) if e2e else None})
    out(f"\n{len(records) - failed} of {len(records)} keys passed in {time.time() - t0:.0f} s")
    if a.receipts:
        text = json.dumps({
            "summary": {"keys": len(records), "passed": len(records) - failed, "failed": failed, "e2e": not a.no_e2e},
            "tool": {"verify_owners_py_sha256": hashlib.sha256(open(__file__, "rb").read().replace(b"\r\n", b"\n")).hexdigest(),
                     "recipes_sha256": hashlib.sha256(open(a.recipes, "rb").read().replace(b"\r\n", b"\n")).hexdigest(),
                     "identity_functions_sha256": identity_functions_sha256(probe),
                     "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "python": sys.version.split()[0]},
            "results": results}, indent=1, ensure_ascii=False) + "\n"
        leaked = verify.leaked_paths(text)
        if leaked:
            out(f"LEAK: the receipt contains local paths: {leaked[:3]}")
            failed += 1
        with open(a.receipts, "w", encoding="utf-8") as stream:
            stream.write(text)
    ws.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

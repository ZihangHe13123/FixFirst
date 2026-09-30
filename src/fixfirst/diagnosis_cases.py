"""Real-execution root-cause dataset: five project templates x single-fault scenarios.

Each case copies a template whose healthy state was verified, injects exactly one fault,
runs the real environment, project and pytest checks in the target interpreter and keeps
the recorded session. The label comes from the scenario definition, never from FixFirst's
rules or model. Libraries are the versions actually installed; nothing is mocked.

Some scenarios deliberately use removed APIs and packages that the knowledge base does not
list, and several pairs look alike on the surface but have different causes (for example a
KeyError on os.environ versus a KeyError on a data dict), so rules and the learned model
can be compared honestly.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
import time

from .models import Session, now
from .runner import environment_id
from .service import create_session, scan

CHECKS = ["environment", "project", "pytest_run"]
PORTABLE_PYTHON = "/venv/bin/python"


@dataclass(frozen=True)
class Template:
    name: str
    service: str
    module: str
    helper: str
    helper_module: str
    helper_fn: str
    func: str
    cls: str
    test: str
    conftest: str
    path_dir: str
    env: str
    cfg: str
    key: str
    setting: str
    renamed: str
    circular: tuple
    unknown_module: str
    ini: str = ""
    packages: tuple = ()
    unittest_style: bool = False
    fixture_style: bool = False


TEMPLATES = (
    Template(
        "flat-shop", "app.py", "app", "helper.py", "helper", "double", "order_total", "Cart",
        "test_app.py", "conftest.py", ".", "SHOP_API_TOKEN", "settings.yaml", "price",
        "payment_url", "helpers.py", ("pricing", "discounts"), "humanize",
    ),
    Template(
        "src-billing", "src/billing/invoice.py", "billing.invoice", "src/billing/rates.py",
        "billing.rates", "scale", "invoice_amount", "Invoice", "tests/test_invoice.py",
        "tests/conftest.py", "src", "BILLING_DB_URL", "billing.json", "amount", "ledger_dsn",
        "src/billing/rate.py", ("ledger", "journal"), "tomlkit",
        ini="[pytest]\npythonpath = src\ntestpaths = tests\n", packages=("src/billing",),
    ),
    Template(
        "pkg-inventory", "inventory/stock.py", "inventory.stock", "inventory/utils/numbers.py",
        "inventory.utils.numbers", "twice", "stock_value", "Warehouse", "tests/test_stock.py",
        "conftest.py", ".", "INVENTORY_REGION", "inventory.ini", "quantity", "warehouse_id",
        "inventory/utils/number.py", ("suppliers", "shipments"), "rapidfuzz",
        packages=("inventory", "inventory/utils"),
    ),
    Template(
        "unittest-grades", "grades.py", "grades", "grading_helpers.py", "grading_helpers",
        "weighted", "final_grade", "Student", "tests/test_grades.py", "tests/conftest.py", ".",
        "GRADES_SERVICE_KEY", "grading.toml", "score", "term_code", "grading_helper.py",
        ("rubric", "courses"), "orjson", ini="[pytest]\npythonpath = .\ntestpaths = tests\n",
        unittest_style=True,
    ),
    Template(
        "fixture-orders", "orders/service.py", "orders.service", "orders/tax.py", "orders.tax",
        "with_rate", "checkout_total", "Basket", "tests/test_service.py", "tests/conftest.py",
        ".", "ORDERS_QUEUE_URL", "orders.env", "sku", "queue_name", "orders/taxes.py",
        ("catalog", "promotions"), "xxhash", ini="[pytest]\npythonpath = .\ntestpaths = tests\n",
        packages=("orders",), fixture_style=True,
    ),
)

IMPORTS, BODY, TEST_IMPORTS, FIXTURES = (
    "# scenario-imports",
    "    # scenario-body",
    "# scenario-test-imports",
    "# scenario-fixtures",
)


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_template(root: Path, t: Template):
    if root.exists():
        raise ValueError(f"Template directory already exists: {root}")
    for package in t.packages:
        write(root / package / "__init__.py", "")
    write(root / t.helper, f"def {t.helper_fn}(value):\n    return value * 2\n")
    write(
        root / t.service,
        f"from {t.helper_module} import {t.helper_fn}\n{IMPORTS}\n\n\n"
        f"class {t.cls}:\n    def __init__(self, values):\n        self.values = list(values)\n\n"
        f"    def total(self):\n        return sum(self.values)\n\n\n"
        f"def {t.func}(values):\n{BODY}\n    return {t.helper_fn}({t.cls}(values).total())\n",
    )
    if t.unittest_style:
        test = (
            f"import unittest\n\nfrom {t.module} import {t.cls}, {t.func}\n{TEST_IMPORTS}\n\n\n"
            f"class Test{t.cls}(unittest.TestCase):\n"
            f"    def test_{t.func}(self):\n        self.assertEqual({t.func}([1, 2]), 6)\n\n"
            f"    def test_total(self):\n        self.assertEqual({t.cls}([1, 2]).total(), 3)\n"
        )
    else:
        argument = "sample_values" if t.fixture_style else ""
        values = "sample_values" if t.fixture_style else "[1, 2]"
        test = (
            f"from {t.module} import {t.cls}, {t.func}\n{TEST_IMPORTS}\n\n\n"
            f"def test_{t.func}({argument}):\n    assert {t.func}({values}) == 6\n\n\n"
            f"def test_{t.cls.lower()}_total():\n    assert {t.cls}([1, 2]).total() == 3\n"
        )
    write(root / t.test, test)
    write(
        root / t.conftest,
        f"import pytest\n\n\n@pytest.fixture\ndef sample_values():\n    return [1, 2]\n{FIXTURES}\n",
    )
    if t.ini:
        write(root / "pytest.ini", t.ini)
    write(root / "requirements.txt", "pytest>=8\n")
    write(
        root / "pyproject.toml",
        f'[project]\nname = "{t.name}"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
        'dependencies = []\n',
    )
    write(root / "LICENSE", "Generated fixture code: CC0-1.0.\n")


class Project:
    """Small editing helper used by scenarios; paths are relative to the case project."""

    def __init__(self, root: Path, template: Template, index: int):
        self.root, self.t, self.k = root, template, index

    def pick(self, options):
        return options[self.k % len(options)]

    def inject(self, rel, marker, code):
        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            raise ValueError(f"{rel} has no {marker}")
        path.write_text(text.replace(marker, code.rstrip("\n") + "\n" + marker, 1), encoding="utf-8")

    def imports(self, code):
        self.inject(self.t.service, IMPORTS, code)

    def body(self, code):
        self.inject(self.t.service, BODY, code)

    def test_imports(self, code):
        self.inject(self.t.test, TEST_IMPORTS, code)

    def fixture(self, code):
        self.inject(self.t.conftest, FIXTURES, code)

    def add_test(self, code):
        path = self.root / self.t.test
        path.write_text(path.read_text(encoding="utf-8") + "\n\n" + code, "utf-8")

    def write(self, rel, text):
        write(self.root / rel, text)

    def top_level(self, name):
        return self.t.path_dir.rstrip("/") + "/" + name if self.t.path_dir != "." else name


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    label: str
    knowledge: bool  # whether the knowledge base covers this fault
    description: str
    apply: object


def s(scenario_id, label, knowledge, description):
    def register(function):
        SCENARIOS.append(Scenario(scenario_id, label, knowledge, description, function))
        return function

    return register


SCENARIOS: list[Scenario] = []

# ----- missing third-party dependencies -------------------------------------------------


@s("md_known_import", "missing_dependency", True, "Import of a known third-party package that is not installed")
def _(p):
    p.imports(f"import {p.pick(['requests', 'cv2', 'bs4', 'jwt', 'dotenv'])}")


@s("md_known_runtime", "missing_dependency", True, "Runtime import of a known package with a different distribution name")
def _(p):
    p.body(f"    import {p.pick(['dateutil', 'PIL', 'serial', 'magic', 'zmq'])}")


@s("md_declared", "missing_dependency", False, "Dependency declared in requirements.txt but not installed")
def _(p):
    name = p.pick(["tabulate", "simplejson", "ujson", "cachetools", "wrapt"])
    path = p.root / "requirements.txt"
    path.write_text(path.read_text(encoding="utf-8") + f"{name}>=0.1\n")
    p.imports(f"import {name}")


@s("md_declared_alias", "missing_dependency", True, "Declared distribution whose import name differs, not installed")
def _(p):
    module, dist = p.pick(
        [("bs4", "beautifulsoup4"), ("dateutil", "python-dateutil"), ("jwt", "PyJWT"),
         ("dotenv", "python-dotenv"), ("attr", "attrs")]
    )
    path = p.root / "requirements.txt"
    path.write_text(path.read_text(encoding="utf-8") + f"{dist}>=0.1\n")
    p.imports(f"import {module}")


@s("md_unknown_runtime", "missing_dependency", False, "Undeclared package unknown to the knowledge base, imported at run time")
def _(p):
    p.body(f"    import {p.t.unknown_module}")


@s("md_unknown_test", "missing_dependency", False, "Undeclared package unknown to the knowledge base, imported by a test module")
def _(p):
    p.test_imports(f"import {p.pick(['pendulum', 'arrow', 'boltons', 'toolz', 'parse'])}")


# ----- local module problems -----------------------------------------------------------


@s("lm_renamed", "local_module", False, "Helper module renamed; imports still use the old name")
def _(p):
    (p.root / p.t.helper).rename(p.root / p.t.renamed)


@s("lm_src_layout", "local_module", False, "Package moved under src/ without putting src on the path")
def _(p):
    if p.t.path_dir == "src":
        (p.root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        return
    (p.root / "src").mkdir()
    top = {p.t.service.split("/")[0], p.t.helper.split("/")[0]}
    for name in sorted(top):
        shutil.move(str(p.root / name), str(p.root / "src" / name))


@s("lm_shadow_library", "local_module", True, "Project file named like an installed library hides it")
def _(p):
    name, call = p.pick(
        [("yaml", "safe_load('a: 1')"), ("click", "echo('total')"), ("jinja2", "Template('x')"),
         ("markupsafe", "escape('x')"), ("yaml", "dump({})")]
    )
    p.write(p.top_level(f"{name}.py"), '"""Project notes."""\nVALUE = 1\n')
    p.body(f"    import {name}\n    {name}.{call}")


@s("lm_shadow_stdlib", "local_module", False, "Project file named like a standard-library module hides it")
def _(p):
    name, call = p.pick(
        [("statistics", "mean([1, 2])"), ("colorsys", "rgb_to_hsv(0.1, 0.2, 0.3)"),
         ("graphlib", "TopologicalSorter()"), ("sched", "scheduler()"),
         ("statistics", "median([1, 2])")]
    )
    p.write(p.top_level(f"{name}.py"), '"""Project helpers."""\nVALUE = 1\n')
    p.body(f"    import {name}\n    {name}.{call}")


@s("lm_circular", "local_module", False, "Two project modules import each other")
def _(p):
    a, b = p.t.circular
    p.write(p.top_level(f"{a}.py"), f"from {b} import {b}_rule\n\n\ndef {a}_rule():\n    return 1\n")
    p.write(p.top_level(f"{b}.py"), f"from {a} import {a}_rule\n\n\ndef {b}_rule():\n    return {a}_rule()\n")
    p.imports(f"from {a} import {a}_rule")


@s("lm_relative", "local_module", False, "Relative import in a test module that is not in a package")
def _(p):
    p.test_imports(f"from .{p.t.helper_module.rsplit('.', 1)[-1]} import {p.t.helper_fn}")


# ----- version incompatibilities covered by the knowledge base -------------------------


@s("vi_stdlib_module", "version_incompatibility", True, "Standard-library module removed in Python 3.12")
def _(p):
    p.imports(f"import {p.pick(['imp', 'asyncore', 'asynchat', 'smtpd', 'asyncore'])}")


@s("vi_collections_abc", "version_incompatibility", True, "collections ABC alias removed in Python 3.10")
def _(p):
    p.imports(f"from collections import {p.pick(['Mapping', 'MutableMapping', 'Sequence', 'Iterable', 'Callable'])}")


@s("vi_numpy_alias", "version_incompatibility", True, "NumPy type alias removed in 1.24")
def _(p):
    p.body(f"    import numpy\n    numpy.{p.pick(['float', 'int', 'object', 'str', 'complex'])}(1)")


@s("vi_numpy2", "version_incompatibility", True, "NumPy name removed in 2.0")
def _(p):
    p.body(f"    import numpy as np\n    np.{p.pick(['NaN', 'Inf', 'product', 'alltrue', 'round_'])}")


@s("vi_jinja2", "version_incompatibility", True, "Jinja2 name removed in 3.1")
def _(p):
    p.imports(f"from jinja2 import {p.pick(['Markup', 'escape', 'contextfunction', 'contextfilter', 'environmentfilter'])}")


@s("vi_library_import", "version_incompatibility", True, "Name removed from MarkupSafe, packaging, pydantic or SciPy")
def _(p):
    module, name = p.pick(
        [("markupsafe", "soft_unicode"), ("packaging.version", "LegacyVersion"),
         ("packaging.specifiers", "LegacySpecifier"), ("pydantic", "BaseSettings"),
         ("scipy.integrate", "simps")]
    )
    p.imports(f"from {module} import {name}")


@s("vi_library_runtime", "version_incompatibility", True, "Removed scikit-learn or SciPy function imported at run time")
def _(p):
    module, name = p.pick(
        [("sklearn.datasets", "load_boston"), ("sklearn.metrics", "plot_confusion_matrix"),
         ("sklearn.metrics", "plot_roc_curve"), ("scipy.integrate", "trapz"),
         ("scipy.integrate", "cumtrapz")]
    )
    p.body(f"    from {module} import {name}")


@s("vi_removed_kwarg", "version_incompatibility", True, "scikit-learn keyword argument removed")
def _(p):
    if p.k % 2 == 0:
        p.body("    from sklearn.preprocessing import OneHotEncoder\n    OneHotEncoder(sparse=False)")
    else:
        p.body("    from sklearn.metrics import mean_squared_error\n    mean_squared_error([1, 2], [1, 3], squared=False)")


@s("vi_unittest_alias", "version_incompatibility", True, "unittest alias removed in Python 3.12")
def _(p):
    call = p.pick(
        ["assertEquals(1, 1)", "assertNotEquals(1, 2)", "assertRegexpMatches('abc', 'a')",
         "assertAlmostEquals(1.0, 1.0)", "failUnless(True)"]
    )
    p.add_test(
        "import unittest as _legacy_unittest\n\n\n"
        "class TestLegacyAssertions(_legacy_unittest.TestCase):\n"
        f"    def test_legacy_alias(self):\n        self.{call}\n"
    )


@s("vi_asyncio_coroutine", "version_incompatibility", True, "asyncio.coroutine removed in Python 3.11")
def _(p):
    p.body("    import asyncio\n    asyncio.coroutine")


# ----- version incompatibilities the knowledge base does not list ----------------------


@s("vi_unknown_attribute", "version_incompatibility", False, "NumPy function removed but absent from the knowledge base")
def _(p):
    p.body(f"    import numpy as np\n    np.{p.pick(['msort', 'in1d', 'row_stack', 'cast', 'mat'])}")


@s("vi_unknown_import", "version_incompatibility", False, "SciPy or scikit-learn name removed but absent from the knowledge base")
def _(p):
    module, name = p.pick(
        [("scipy.stats", "itemfreq"), ("sklearn.utils", "safe_indexing"),
         ("sklearn.metrics", "jaccard_similarity_score"), ("scipy.misc", "comb"),
         ("scipy.stats", "binom_test")]
    )
    p.imports(f"from {module} import {name}")


@s("vi_unknown_submodule", "version_incompatibility", False, "Library submodule removed but absent from the knowledge base")
def _(p):
    p.imports(
        f"import {p.pick(['sklearn.cross_validation', 'sklearn.grid_search', 'sklearn.learning_curve', 'numpy.distutils', 'scipy.weave'])}"
    )


@s("vi_private_moved", "version_incompatibility", False, "Private name imported from a path the installed library moved or removed")
def _(p):
    # Each name still exists elsewhere in the installed library (docs/B4_SCENARIOS.md).
    module, name = p.pick(
        [("sklearn.utils", "_print_elapsed_time"), ("pydantic.fields", "ModelField"),
         ("scipy.sparse.sputils", "isdense"), ("numpy.lib.function_base", "iterable"),
         ("sklearn.metrics.scorer", "_check_multimetric_scoring")]
    )
    p.imports(f"from {module} import {name}")


# ----- missing configuration ------------------------------------------------------------


@s("cm_environ", "config_missing", False, "Required environment variable read with os.environ")
def _(p):
    p.imports("import os")
    p.body(f'    token = os.environ["{p.t.env}"]')


@s("cm_config_file", "config_missing", False, "Configuration file missing")
def _(p):
    p.body(f'    with open("{p.t.cfg}", encoding="utf-8") as handle:\n        handle.read()')


@s("cm_explicit", "config_missing", False, "Project raises an explicit missing-configuration error")
def _(p):
    p.body(f'    raise RuntimeError("Missing configuration: {p.t.env}")')


@s("cm_getenv_none", "config_missing", False, "os.getenv returns None and the value is used")
def _(p):
    p.imports("import os")
    p.body(f'    os.getenv("{p.t.env}").split(":")')


@s("cm_fixture_env", "config_missing", False, "Fixture needs an environment variable")
def _(p):
    p.fixture(
        f'\n\n@pytest.fixture\ndef service_credentials():\n    import os\n\n    return os.environ["{p.t.env}"]'
    )
    p.add_test("def test_uses_credentials(service_credentials):\n    assert service_credentials\n")


@s("cm_settings_key", "config_missing", False, "Settings file lacks a required key")
def _(p):
    p.write("config.json", '{"name": "demo"}\n')
    p.body(
        '    import json\n\n    with open("config.json", encoding="utf-8") as handle:\n'
        f'        settings = json.load(handle)\n    settings["{p.t.setting}"]'
    )


# ----- defects in project code ----------------------------------------------------------


@s("cd_assertion", "code_defect", False, "Wrong result makes an assertion fail")
def _(p):
    p.body("    values = list(values) + [1]")


@s("cd_zero_division", "code_defect", False, "Division by zero in project code")
def _(p):
    p.body("    average = sum(values) / len([])")


@s("cd_name_error", "code_defect", False, "Misspelt variable")
def _(p):
    p.body("    count = len(valeus)")


@s("cd_index_error", "code_defect", False, "Index out of range")
def _(p):
    p.body("    first = list(values)[10]")


@s("cd_syntax_error", "code_defect", False, "Syntax error in a project module")
def _(p):
    path = p.root / p.t.service
    path.write_text(path.read_text(encoding="utf-8") + "\n\ndef broken(:\n    pass\n")


@s("cd_wrong_arguments", "code_defect", False, "Project function called with too many arguments")
def _(p):
    p.body(f"    {p.t.helper_fn}(1, 2)")


@s("cd_local_kwarg", "code_defect", False, "Project function called with an unknown keyword argument")
def _(p):
    p.body(f"    {p.t.helper_fn}(1, verbose=True)")


@s("cd_attribute_typo", "code_defect", False, "Misspelt method on a project class")
def _(p):
    p.body(f"    {p.t.cls}(values).totl()")


@s("cd_dict_key", "code_defect", False, "Missing key in a data dictionary")
def _(p):
    p.body(f'    item = {{"name": "widget"}}\n    item["{p.t.key}"]')


@s("cd_value_error", "code_defect", False, "Invalid literal converted in project code")
def _(p):
    p.body(f'    int("{p.pick(["abc", "12x", "n/a", "", "one"])}")')


@s("cd_fixture_bug", "code_defect", False, "Fixture raises because of a bug in its data preparation")
def _(p):
    p.fixture(
        "\n\n@pytest.fixture\ndef prepared_rows():\n    rows = []\n"
        '    if not rows:\n        raise ValueError("sample data must not be empty")\n    return rows'
    )
    p.add_test("def test_prepared_rows(prepared_rows):\n    assert prepared_rows\n")


@s("cd_missing_name", "code_defect", False, "Test imports a name the project module does not define")
def _(p):
    p.test_imports(f"from {p.t.module} import {p.t.func}_v2")


def portable(session: Session, project: Path) -> dict:
    """Replace machine-specific paths while keeping environment ids consistent."""
    text = session.model_dump_json()
    replacements = [
        (session.target_python, PORTABLE_PYTHON),
        (str(project), "/project"),
        (sys.prefix, "/venv"),
        (str(Path.home()), "/home/user"),
        (environment_id(session.target_python), environment_id(PORTABLE_PYTHON)),
    ]
    for private, public in replacements:
        # Also match the JSON-escaped form: Windows paths contain backslashes.
        escaped = json.dumps(private, ensure_ascii=False)[1:-1]
        text = text.replace(escaped, json.dumps(public)[1:-1]).replace(private, public)
    data = json.loads(text)
    for run in data["runs"]:
        if run["tool"] == "environment":
            run["stdout"] = "(snapshot stored once in environment.json)"
    # Every case uses the same interpreter; keep one copy of the snapshot for the dataset.
    shared = {k: v for k, v in data["environment"].items() if not k.startswith("_")}
    data["environment"] = {
        "$shared": "environment.json",
        **{k: v for k, v in data["environment"].items() if k.startswith("_")},
    }
    data["facts"], data["actions"] = [], []  # recomputed by the evaluation
    return data, shared


def load_session(dataset: Path, data: dict, cache={}) -> Session:
    """Re-attach the shared environment snapshot to a stored case session."""
    environment = data["environment"]
    if "$shared" in environment:
        path = dataset / environment["$shared"]
        if path not in cache:
            cache[path] = json.loads(path.read_text(encoding="utf-8"))
        data = {**data, "environment": {**cache[path], **{
            k: v for k, v in environment.items() if k.startswith("_")}}}
    return Session.model_validate(data)


def build_dataset(output: Path, python: str | None = None, templates=TEMPLATES, scenarios=None):
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("Dataset directory already exists; choose a new --output")
    python = python or sys.executable
    scenarios = SCENARIOS if scenarios is None else scenarios
    output.mkdir(parents=True)
    pristine = output / "_templates"
    started = time.monotonic()
    manifest = {
        "schema_version": 1,
        "created_at": now(),
        "origin": "diagnosis_injection",
        "python": sys.version.split()[0],
        "license": "CC0-1.0 for generated fixture code",
        "templates": [t.name for t in templates],
        "scenarios": [
            {"id": x.scenario_id, "label": x.label, "knowledge": x.knowledge, "description": x.description}
            for x in scenarios
        ],
        "cases": [],
        "rejected": [],
        "limitations": (
            "Synthetic projects with one injected fault each, executed against real installed "
            "libraries. They are not a sample of naturally occurring failures."
        ),
    }
    cases = output / "cases.jsonl"
    try:
        for t in templates:
            root = pristine / t.name
            build_template(root, t)
            baseline = create_session(root, python, t.name, goal="pass_tests")
            scan(baseline, CHECKS)
            if baseline.goal_status != "achieved" or any(i.status == "open" for i in baseline.issues):
                raise ValueError(f"Template {t.name} is not healthy: {[i.title for i in baseline.issues]}")
            manifest.setdefault("library_versions", {
                p["name"]: p["version"] for p in baseline.environment.get("packages", [])
                if p["name"].lower() in {"numpy", "scipy", "scikit-learn", "jinja2", "markupsafe",
                                          "packaging", "pydantic", "pytest", "click", "pyyaml"}
            })
            for k, scenario in enumerate(scenarios):
                case_id = f"{t.name}--{scenario.scenario_id}"
                project = output / "projects" / case_id
                shutil.copytree(root, project)
                scenario.apply(Project(project, t, TEMPLATES.index(t) if t in TEMPLATES else k))
                session = create_session(project, python, case_id, goal="pass_tests")
                scan(session, CHECKS)
                failures = [
                    i for i in session.issues
                    if i.status == "open" and i.tool == "pytest_run" and i.kind != "tool_failure"
                ]
                if not failures:
                    manifest["rejected"].append(
                        {"case_id": case_id, "reason": "fault not observed",
                         "issues": [f"{i.tool}:{i.kind}:{i.title[:120]}" for i in session.issues]}
                    )
                    print(f"  {case_id}: rejected (fault not observed)", flush=True)
                    continue
                stored, environment = portable(session, project)
                shared = output / "environment.json"
                if not shared.exists():
                    write(shared, json.dumps(environment, ensure_ascii=False, indent=1))
                elif json.loads(shared.read_text(encoding="utf-8")) != environment:
                    raise ValueError("The interpreter's environment changed during generation")
                row = {
                    "case_id": case_id,
                    "template": t.name,
                    "scenario": scenario.scenario_id,
                    "label": scenario.label,
                    "knowledge_covered": scenario.knowledge,
                    "session": stored,
                }
                with cases.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                manifest["cases"].append(
                    {"case_id": case_id, "template": t.name, "scenario": scenario.scenario_id,
                     "label": scenario.label, "issues": len(failures)}
                )
                print(f"  {case_id}: {scenario.label} ({len(failures)} issue(s))", flush=True)
    finally:
        manifest["seconds"] = round(time.monotonic() - started, 1)
        write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return output / "manifest.json"

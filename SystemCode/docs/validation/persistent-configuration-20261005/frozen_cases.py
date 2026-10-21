"""Product acceptance fixtures fixed before implementation; not an experiment task pool."""

FORMATS = {
    "ini": ("pytest.ini", "pytest", False),
    "hidden_ini": (".pytest.ini", "pytest", False),
    "tox": ("tox.ini", "pytest", False),
    "cfg": ("setup.cfg", "tool:pytest", False),
    "toml_ini": ("pyproject.toml", "tool.pytest.ini_options", True),
    "toml_native": ("pyproject.toml", "tool.pytest", True),
    "pytest_toml": ("pytest.toml", "pytest", True),
    "none": ("pytest.ini", "pytest", False),
}


def content(fmt, key=None, value=None):
    filename, section, toml = FORMATS[fmt]
    text = f"[{section}]\n"
    text += 'addopts = ["-q"]\n' if fmt in {"toml_native", "pytest_toml"} else 'addopts = "-q"\n' if toml else "addopts = -q\n"
    if key:
        import json
        rendered = json.dumps(value) if toml else ' '.join(json.dumps(s) for s in value) if isinstance(value, list) else value
        text += f"{key} = {rendered}\n"
    return text


def build(root, kind, fmt, *, preserve=False):
    root.mkdir(parents=True)
    filename = FORMATS[fmt][0]
    if fmt != "none":
        (root / filename).write_text(content(fmt, "pythonpath", ["helpers"]) if preserve else content(fmt))
    if kind == "local":
        (root / "src" / "ledger").mkdir(parents=True)
        (root / "src" / "ledger" / "__init__.py").write_text("VALUE = 17\n")
        test = "from ledger import VALUE\ndef test_value():\n    assert VALUE == 17\n"
        if preserve:
            (root / "helpers").mkdir()
            (root / "helpers" / "aux.py").write_text("EXTRA = 19\n")
            test = "from aux import EXTRA\n" + test + "def test_extra():\n    assert EXTRA == 19\n"
        (root / "test_import.py").write_text(test)
        reference = content(fmt, "pythonpath", ["helpers", "src"] if preserve else ["src"])
    else:
        (root / "suite_config.py").write_text("SECRET_KEY='synthetic-only'\nINSTALLED_APPS=[]\n")
        if filename == "tox.ini" and fmt != "none":
            (root / filename).write_text((root / filename).read_text() + "[testenv]\nsetenv=DJANGO_SETTINGS_MODULE=suite_config\n")
        else:
            (root / "runtests.py").write_text("import os\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', 'suite_config')\n")
        (root / "test_config.py").write_text("from django.conf import settings\nfrom django.apps import apps\n"
            "def test_value():\n    assert settings.SECRET_KEY == 'synthetic-only'\n"
            "def test_apps():\n    assert list(apps.get_app_configs()) == []\n")
        reference = content(fmt, "DJANGO_SETTINGS_MODULE", "suite_config")
        if filename == "tox.ini":
            reference += "[testenv]\nsetenv=DJANGO_SETTINGS_MODULE=suite_config\n"
    return filename, reference

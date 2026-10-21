"""Reference fixes for the user-study tasks (task B8). For the experimenter only.

Each function makes the change a participant would make; prepare.py --self-test applies them
to check that every task can be solved and that grade.py recognises the result. Any other fix
counts as long as grade.py passes (README.md lists the common ones).
"""

from pathlib import Path
import shutil


def fix_t1(folder: Path):
    """Jinja2 3.1 removed jinja2.Markup: import it from MarkupSafe, which Jinja2 depends on."""
    path = folder / "report" / "render.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("from jinja2 import Environment, Markup",
                                 "from jinja2 import Environment\nfrom markupsafe import Markup"), encoding="utf-8")


def fix_t2(folder: Path):
    """src layout: tell pytest where the package is (offline; `pip install -e .` works too)."""
    with (folder / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.pytest.ini_options]\npythonpath = ["src"]\n')


def fix_t3(folder: Path):
    """Python 3.12 removed distutils: compare with packaging.version (installed with pytest)."""
    path = folder / "checker" / "versions.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace("from distutils.version import LooseVersion", "from packaging.version import Version")
    path.write_text(text.replace("LooseVersion", "Version"), encoding="utf-8")


def fix_t4(folder: Path):
    """The settings file was never created: copy the example, as the README says."""
    shutil.copyfile(folder / "settings.example.toml", folder / "settings.toml")


FIXES = {"T1": fix_t1, "T2": fix_t2, "T3": fix_t3, "T4": fix_t4}

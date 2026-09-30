"""Read a bounded environment.yml subset without executing Conda or project code."""

import re

import yaml


# These upstreams document the same package name for pip and Conda. This is an
# explicit PyPI alternative, not a general conversion of Conda channel packages.
SOURCES = {
    "imageio": "https://imageio.readthedocs.io/en/stable/user_guide/installation.html",
    "numpy": "https://numpy.org/install/",
    "scipy": "https://scipy.org/install/",
    "scikit-learn": "https://scikit-learn.org/stable/install.html",
    "matplotlib": "https://matplotlib.org/stable/install/index.html",
    "pandas": "https://pandas.pydata.org/docs/getting_started/install.html",
    "pillow": "https://pillow.readthedocs.io/en/stable/installation/basic-installation.html",
    "joblib": "https://joblib.readthedocs.io/en/latest/user_guide/installing.html",
}
CONDA_SOURCES = {
    "pillow": "https://github.com/conda-forge/pillow-feedstock",
    "joblib": "https://github.com/conda-forge/joblib-feedstock",
}
PYPI_EQUIVALENTS = {name: name for name in SOURCES}


def read(text: str, source: str, limit: int = 2000) -> dict:
    result = {"pip": [], "python": [], "notes": [], "conda": [], "mappings": []}
    try:
        value = yaml.safe_load(text)
    except (yaml.YAMLError, RecursionError, ValueError):
        result["notes"].append(f"{source}: invalid or overly nested YAML")
        return result
    if not isinstance(value, dict) or not isinstance(value.get("dependencies"), list):
        result["notes"].append(f"{source}: dependencies must be a list")
        return result
    dependencies = value["dependencies"]
    if len(dependencies) > limit:
        result["notes"].append(f"{source}: dependency list exceeds the limit")
    budget = limit
    for index, item in enumerate(dependencies[:limit]):
        if budget <= 0:
            result["notes"].append(f"{source}: total dependency limit reached")
            break
        budget -= 1
        location = f"{source} dependencies[{index}]"
        if isinstance(item, dict):
            if set(item) != {"pip"} or not isinstance(item["pip"], list):
                result["notes"].append(f"{location}: unsupported installer section")
                continue
            entries = item["pip"][:budget]
            if len(item["pip"]) > budget:
                result["notes"].append(f"{location}: pip list exceeds the limit")
            budget -= len(entries)
            for line, requirement in enumerate(entries):
                if isinstance(requirement, str):
                    result["pip"].append((requirement, f"{location}.pip[{line}]"))
                else:
                    result["notes"].append(f"{location}: pip requirements must be strings")
            continue
        if not isinstance(item, str):
            result["notes"].append(f"{location}: non-string Conda requirement")
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*((?:[<>=!~].*)?)", item.strip())
        if not match:
            result["notes"].append(f"{location}: channel/build syntax is not converted to pip")
            result["conda"].append({"requirement": item, "source": location})
            continue
        name, spec = match.groups()
        name = name.lower().replace("_", "-")
        if spec.startswith("=") and not spec.startswith("=="):
            version = spec[1:]
            if not re.fullmatch(r"\d+(?:\.\d+)*(?:\.\*)?", version):
                result["notes"].append(f"{location}: Conda build/version syntax is not converted to pip")
                result["conda"].append({"requirement": item, "source": location})
                continue
            spec = "==" + version + ("" if version.endswith(".*") else ".*")
        if name == "python":
            if spec:
                result["python"].append({"specifier": spec, "source": location})
        elif name in PYPI_EQUIVALENTS:
            result["pip"].append((PYPI_EQUIVALENTS[name] + spec,
                                  f"{location} (Conda declaration; documented PyPI alternative)"))
            result["mappings"].append({"declaration": location, "distribution": PYPI_EQUIVALENTS[name],
                                       "source": SOURCES[name], "conda_source": CONDA_SOURCES.get(name, SOURCES[name])})
        elif name != "pip":
            result["conda"].append({"requirement": item, "source": location})
            result["notes"].append(f"{location}: {name} is a Conda requirement; no PyPI name is assumed")
    return result

"""Read a bounded environment.yml subset without executing Conda or project code."""

import re

import yaml


# These upstreams document the same package name for pip and Conda. This is an
# explicit PyPI alternative, not a general conversion of Conda channel packages.
PYPI_EQUIVALENTS = {"imageio": "imageio", "numpy": "numpy"}
SOURCES = {
    "imageio": "https://imageio.readthedocs.io/en/stable/user_guide/installation.html",
    "numpy": "https://numpy.org/install/",
}


def read(text: str, source: str, limit: int = 2000) -> dict:
    result = {"pip": [], "python": [], "notes": [], "conda": []}
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
    for index, item in enumerate(dependencies[:limit]):
        location = f"{source} dependencies[{index}]"
        if isinstance(item, dict):
            if set(item) != {"pip"} or not isinstance(item["pip"], list):
                result["notes"].append(f"{location}: unsupported installer section")
                continue
            if len(item["pip"]) > limit:
                result["notes"].append(f"{location}: pip list exceeds the limit")
            for line, requirement in enumerate(item["pip"][:limit]):
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
                continue
            spec = "==" + version + ("" if version.endswith(".*") else ".*")
        if name == "python":
            if spec:
                result["python"].append({"specifier": spec, "source": location})
        elif name in PYPI_EQUIVALENTS:
            result["pip"].append((PYPI_EQUIVALENTS[name] + spec,
                                  f"{location} (Conda declaration; documented PyPI alternative)"))
        elif name != "pip":
            result["conda"].append({"requirement": item, "source": location})
            result["notes"].append(f"{location}: {name} is a Conda requirement; no PyPI name is assumed")
    return result

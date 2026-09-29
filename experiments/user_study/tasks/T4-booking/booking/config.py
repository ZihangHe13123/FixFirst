from pathlib import Path
import tomllib

SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"


def load():
    with SETTINGS.open("rb") as handle:
        return tomllib.load(handle)["booking"]

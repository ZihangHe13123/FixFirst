from packaging.markers import Marker


def test_untagged_python_version():
    condition = Marker("python_full_version < '3.12'")
    assert condition.evaluate({"python_full_version": "3.11.1+"})

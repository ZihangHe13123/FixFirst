from checker.versions import is_newer, latest


def test_numeric_parts_are_compared_as_numbers():
    assert is_newer("1.10", "1.9")


def test_equal_versions_are_not_newer():
    assert not is_newer("2.0", "2.0")


def test_older_version():
    assert not is_newer("0.9.1", "1.0")


def test_latest():
    assert latest(["1.2", "1.10", "1.9"]) == "1.10"

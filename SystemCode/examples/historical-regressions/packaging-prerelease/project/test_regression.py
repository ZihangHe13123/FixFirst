from packaging.specifiers import Specifier


def test_prerelease_is_accepted():
    requirement = Specifier("<3.0.0a8")
    actual = requirement.contains("3.0.0a7")
    assert actual, "An earlier prerelease should match the exclusive prerelease bound"

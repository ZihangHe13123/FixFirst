from distutils.version import LooseVersion


def is_newer(candidate, current):
    return LooseVersion(candidate) > LooseVersion(current)


def latest(versions):
    return max(versions, key=LooseVersion)

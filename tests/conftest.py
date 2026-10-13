import sys

import pytest


@pytest.fixture
def make_symlink():
    """Run link tests on Windows whenever its permissions/filesystem support them."""
    def create(link, target, **kwargs):
        try:
            link.symlink_to(target, **kwargs)
        except OSError as exc:
            if sys.platform == "win32" and getattr(exc, "winerror", None) in (50, 1314):
                pytest.skip("Windows cannot create symlinks: enable Developer Mode/privilege "
                            "and use a filesystem with symlink support")
            raise
    return create

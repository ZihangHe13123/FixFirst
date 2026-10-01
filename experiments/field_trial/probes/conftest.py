"""Load a checkout's own test fixtures for the probes in this folder (FF_TESTS=<checkout>/tests)."""
import os
import sys

sys.path.insert(0, os.environ["FF_TESTS"])
from test_dependency_resolution import offline_resolver  # noqa: E402,F401

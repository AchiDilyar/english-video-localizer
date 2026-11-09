"""Keep pytest's generated files under tests/tmp (architecture v1.2.0)."""
from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp is None:
        config.option.basetemp = str(Path(__file__).resolve().parent / "tmp/pytest")

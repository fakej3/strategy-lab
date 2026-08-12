"""Root conftest.py — project-wide pytest configuration."""
from __future__ import annotations

import warnings


def pytest_configure(config):
    """Register warning filters for third-party library warnings we can't fix.

    StarletteDeprecationWarning: raised by fastapi.testclient itself (which
    re-exports starlette.testclient) when the installed httpx version predates
    the starlette 1.x migration to httpx2.  This is a library compatibility
    issue in the installed packages, not in our code; filter it so it doesn't
    pollute test output while we wait for a compatible release combination.
    """
    from starlette.exceptions import StarletteDeprecationWarning
    warnings.filterwarnings(
        "ignore",
        message=r"Using `httpx` with `starlette\.testclient` is deprecated",
        category=StarletteDeprecationWarning,
    )

"""Keep cache isolation violations fatal even if a test catches the exception."""

import pytest

from tests import _cache_violations


@pytest.fixture(autouse=True)
def private_cache_guard():
    yield
    assert not _cache_violations, "\n".join(_cache_violations)

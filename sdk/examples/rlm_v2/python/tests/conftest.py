from __future__ import annotations

import pytest

from rlm_v2.repl import REPLRegistry


@pytest.fixture(autouse=True)
def _clear_repl_registry() -> None:
    REPLRegistry.clear()
    yield
    REPLRegistry.clear()

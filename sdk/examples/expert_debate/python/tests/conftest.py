from __future__ import annotations

import sys
from pathlib import Path

import pytest


_THIS = Path(__file__).resolve()
_PYTHON_DIR = _THIS.parents[1]
_EXAMPLE_DIR = _THIS.parents[2]
_PROJECT_ROOT = _THIS.parents[5]


def _prepend(path: Path) -> None:
    p = str(path)
    if p not in sys.path:
        sys.path.insert(0, p)


# Ensure example package and local SDKs are importable when running tests directly.
_prepend(_PYTHON_DIR / "src")
_prepend(_PROJECT_ROOT / "sdk" / "python" / "flatagents")
_prepend(_PROJECT_ROOT / "sdk" / "python" / "flatmachines")


@pytest.fixture(scope="session")
def example_dir() -> Path:
    return _EXAMPLE_DIR


@pytest.fixture(scope="session")
def config_dir(example_dir: Path) -> Path:
    return example_dir / "config"

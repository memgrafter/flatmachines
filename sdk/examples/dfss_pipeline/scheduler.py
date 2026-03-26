"""Compatibility wrapper for python/src/flatagent_dfss_pipeline/scheduler.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "python" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from flatagent_dfss_pipeline.scheduler import *  # noqa: F401,F403

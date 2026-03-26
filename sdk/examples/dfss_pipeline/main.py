#!/usr/bin/env python3
"""Compatibility wrapper for the DFSS pipeline Python package.

This keeps the historical top-level entrypoint working while the example now
lives under python/src/flatagent_dfss_pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "python" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from importlib import import_module

_impl = import_module("flatagent_dfss_pipeline.main")
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})


if __name__ == "__main__":
    _impl.main()

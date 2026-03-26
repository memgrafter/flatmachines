from __future__ import annotations

import importlib
import sys
from pathlib import Path


def package_src_root() -> Path:
    # .../sdk/examples/dfss_pipeline/python/tests/unit -> .../sdk/examples/dfss_pipeline/python/src
    return Path(__file__).resolve().parents[2] / "src"


def load_dfss_module(filename: str, module_name: str):
    if not filename.endswith(".py"):
        raise AssertionError(f"Expected python filename, got: {filename}")

    mod = filename[:-3]
    module_path = f"flatagent_dfss_pipeline.{mod}"

    src_root = package_src_root()
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    module = importlib.import_module(module_path)
    return importlib.reload(module)

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def dfss_examples_dir() -> Path:
    # .../sdk/examples/dfss_pipeline/python/tests/unit -> .../sdk/examples/dfss_pipeline
    return Path(__file__).resolve().parents[3]


def load_dfss_module(filename: str, module_name: str):
    path = dfss_examples_dir() / filename
    if not path.exists():
        raise AssertionError(f"Expected DFSS example file missing: {path}")

    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load module spec: {path}")

    module = importlib.util.module_from_spec(spec)
    # Ensure module is discoverable during execution (e.g. dataclass annotation resolution).
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

#!/usr/bin/env python3
"""
Structure validation test for Zig + Python C-API demo.

This validates the demo structure without requiring Zig to be installed.
"""

import sys
from pathlib import Path


def test_structure():
    """Validate demo directory structure."""
    demo_dir = Path(__file__).parent

    required_files = [
        "README.md",
        "DEMO.md",
        "run.sh",
        "pyproject.toml",
        ".gitignore",
        "config/task_generator.yml",
        "config/analyzer.yml",
        "config/machine.yml",
        "zig_src/prime_compute.zig",
        "zig_src/build.zig",
        "zig_src/Makefile",
        "src/zig_python_capi/__init__.py",
        "src/zig_python_capi/main.py",
    ]

    print("Validating demo structure...")
    print("=" * 60)

    all_ok = True
    for file_path in required_files:
        full_path = demo_dir / file_path
        exists = full_path.exists()
        status = "✓" if exists else "✗"
        print(f"{status} {file_path}")
        if not exists:
            all_ok = False

    print("=" * 60)

    if all_ok:
        print("✓ All required files present")
        return 0
    else:
        print("✗ Some required files missing")
        return 1


def test_imports():
    """Test that Python files can be imported (syntax check)."""
    print("\nValidating Python syntax...")
    print("=" * 60)

    demo_dir = Path(__file__).parent
    sys.path.insert(0, str(demo_dir / "src"))

    try:
        # This will fail if zigprimes module doesn't exist, but that's expected
        # We're just checking Python syntax
        import zig_python_capi

        print("✓ Package imports successfully")
        print(f"  Version: {zig_python_capi.__version__}")
    except ImportError as e:
        if "zigprimes" in str(e):
            print(
                "✓ Package structure valid (zigprimes module not built yet - expected)"
            )
        else:
            print(f"✗ Import error: {e}")
            return 1

    print("=" * 60)
    return 0


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ZIG + PYTHON C-API DEMO - STRUCTURE TEST")
    print("=" * 60 + "\n")

    exit_code = 0

    exit_code |= test_structure()
    exit_code |= test_imports()

    print("\n" + "=" * 60)
    if exit_code == 0:
        print("✓ ALL TESTS PASSED")
        print("\nTo build and run the demo:")
        print("  1. Install Zig: https://ziglang.org/download/")
        print("  2. Run: ./run.sh")
    else:
        print("✗ SOME TESTS FAILED")
    print("=" * 60 + "\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

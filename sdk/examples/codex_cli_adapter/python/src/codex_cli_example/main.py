"""
Codex CLI Adapter — Cache Demos

--test-cache:        Sequential resume cache demo
--test-fanout-cache: Parallel foreach fanout cache demo

Usage:
    python -m codex_cli_example.main --test-cache
    python -m codex_cli_example.main --test-fanout-cache
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from flatmachines import FlatMachine

from .hooks import CodexCliHooks

_log_level = os.environ.get("LOG_LEVEL", "WARNING").upper()
logging.getLogger().setLevel(_log_level)
for _name in ("flatagents", "flatmachines"):
    logging.getLogger(_name).setLevel(_log_level)

_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"

# Expected answers for validation (unique values only in demo_context.md)
_EXPECTED = {
    "68B201E19CB8F6B8": "build hash",
    "TRIDENT-APEX-9047": "authorization code",
    "moonshot-cardinal-7": "cluster name",
}


def _validate_answer(answer: str, label: str) -> bool:
    """Check if the answer contains the expected unique value."""
    if not answer:
        return False
    for expected_value, expected_label in _EXPECTED.items():
        if expected_label == label and expected_value.lower() in answer.lower():
            return True
    return False


async def run(config_name: str):
    """Run a cache demo."""
    machine = FlatMachine(
        config_file=str(_CONFIG_DIR / config_name),
        hooks=CodexCliHooks(),
    )

    result = await machine.execute(input={})

    print()
    print("=" * 60)

    if not isinstance(result, dict):
        print(f"Unexpected result type: {type(result)}")
        return 1

    failures = 0

    # Cache demo validation
    verify = result.get("verify_result", "")
    if verify:
        ok = "68B201E19CB8F6B8" in str(verify).upper()
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{status} — verify_result: {verify}")
        if not ok:
            failures += 1

    # Fanout demo validation
    fanout = result.get("fanout_results")
    if fanout:
        print(f"Fanout results type: {type(fanout).__name__}")
        print(f"Fanout results: {json.dumps(fanout, indent=2, default=str)[:2000]}")
        print()

        # Extract answers from whatever shape the output is
        answers = {}
        if isinstance(fanout, dict):
            for key, val in fanout.items():
                if isinstance(val, dict):
                    q = val.get("question", key)
                    a = val.get("answer", "")
                    answers[q] = a
                elif isinstance(val, str):
                    answers[key] = val
        elif isinstance(fanout, list):
            for item in fanout:
                if isinstance(item, dict):
                    q = item.get("question", "?")
                    a = item.get("answer", "")
                    answers[q] = a

        # Validate each expected value appears in some answer
        for expected_value, label in _EXPECTED.items():
            found = any(expected_value.lower() in str(a).lower() for a in answers.values())
            status = "✅ PASS" if found else "❌ FAIL"
            print(f"{status} — {label}: expected '{expected_value}' in answers")
            if not found:
                failures += 1

        if not answers:
            print("❌ FAIL — no answers extracted from fanout_results")
            failures += 1

    print("=" * 60)
    if failures:
        print(f"❌ {failures} validation(s) failed")
    else:
        print("✅ All validations passed")

    return failures


def main():
    parser = argparse.ArgumentParser(
        description="Codex CLI adapter cache demos"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--test-cache",
        action="store_true",
        help="Run sequential resume cache demo",
    )
    group.add_argument(
        "--test-fanout-cache",
        action="store_true",
        help="Run parallel foreach fanout cache demo",
    )
    args = parser.parse_args()

    if args.test_fanout_cache:
        config = "machine_fanout_cache_demo.yml"
    else:
        config = "machine_cache_demo.yml"

    failures = asyncio.run(run(config))
    sys.exit(failures)


if __name__ == "__main__":
    main()

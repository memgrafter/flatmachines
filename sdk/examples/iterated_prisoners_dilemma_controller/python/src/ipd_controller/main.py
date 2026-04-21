from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from flatmachines import FlatMachine, HooksRegistry, get_logger, setup_logging

from .hooks import IPDMatchHooks, IPDPlayerHooks

setup_logging(level=os.getenv("FLATAGENTS_LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


def _config_path(name: str) -> Path:
    return Path(__file__).parent.parent.parent.parent / "config" / name


def _print_summary(result: dict, show_raw: bool = False) -> None:
    history = result.get("history") or []
    rounds_total = result.get("rounds_total", len(history))
    print(f"\n=== Iterated Prisoner's Dilemma ({rounds_total} rounds) ===")
    print("Rnd | A | B | +A | +B | TotA | TotB")
    print("----+---+---+----+----+------+------")
    for r in history:
        print(
            f"{r.get('round', 0):>3} | {r.get('move_a', '?'):>1} | {r.get('move_b', '?'):>1} | "
            f"{r.get('score_a', 0):>2} | {r.get('score_b', 0):>2} | "
            f"{r.get('total_a', 0):>4} | {r.get('total_b', 0):>4}"
        )
        if show_raw:
            print(
                "     raw_a="
                f"{r.get('decision_raw_a')!r} raw_b={r.get('decision_raw_b')!r}"
            )

    totals = result.get("totals") or {}
    coop = result.get("cooperation_rate") or {}
    defect = result.get("defection_rate") or {}

    print("\nTotals:")
    print(f"  A: {totals.get('A', 0)}")
    print(f"  B: {totals.get('B', 0)}")
    print("Rates:")
    print(f"  A cooperate={coop.get('A', 0)} defect={defect.get('A', 0)}")
    print(f"  B cooperate={coop.get('B', 0)} defect={defect.get('B', 0)}")


async def run(rounds: int = 10, debug_messages: bool = False) -> dict:
    registry = HooksRegistry()
    registry.register("ipd-player-hooks", lambda: IPDPlayerHooks(debug_messages=debug_messages))
    registry.register("ipd-match-hooks", IPDMatchHooks)

    machine = FlatMachine(
        config_file=str(_config_path("match_machine.yml")),
        hooks_registry=registry,
    )

    logger.info("Running IPD match with rounds=%s", rounds)
    result = await machine.execute(input={"rounds_total": rounds})

    _print_summary(result, show_raw=debug_messages)
    logger.info("API calls=%s cost=$%.4f", machine.total_api_calls, machine.total_cost)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Iterated Prisoner's Dilemma controller demo")
    parser.add_argument("--rounds", type=int, default=10, help="Number of rounds (default: 10)")
    parser.add_argument("--debug", action="store_true", help="Print per-agent input/output messages")
    args = parser.parse_args()

    debug_messages = args.debug or str(os.getenv("IPD_DEBUG_MESSAGES", "")).lower() in {"1", "true", "yes", "on"}
    asyncio.run(run(rounds=args.rounds, debug_messages=debug_messages))


if __name__ == "__main__":
    main()

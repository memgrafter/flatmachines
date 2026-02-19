"""CLI and runtime entrypoint for RLM v2 example."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from flatmachines import FlatMachine, get_logger, setup_logging

setup_logging(level="INFO")
logger = get_logger(__name__)


def _config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "machine.yml"


async def run_rlm_v2(
    *,
    task: str,
    long_context: str,
    current_depth: int = 0,
    max_depth: int = 5,
    timeout_seconds: int = 300,
    max_iterations: int = 20,
    max_steps: int = 80,
    sub_model_profile: str | None = None,
    model_override: str | None = None,
) -> dict[str, Any]:
    """Run the minimal recursive RLM machine."""
    config_path = _config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Machine config not found: {config_path}")

    machine = FlatMachine(config_file=str(config_path))

    input_payload: dict[str, Any] = {
        "task": task,
        "long_context": long_context,
        "current_depth": current_depth,
        "max_depth": max_depth,
        "timeout_seconds": timeout_seconds,
        "max_iterations": max_iterations,
        "max_steps": max_steps,
        "machine_config_path": str(config_path),
        "sub_model_profile": sub_model_profile,
        "model_override": model_override,
    }

    logger.info(
        "Starting RLM v2: context_len=%s depth=%s/%s max_iterations=%s",
        len(long_context),
        current_depth,
        max_depth,
        max_iterations,
    )

    result = await machine.execute(input=input_payload, max_steps=max_steps)

    logger.info(
        "Completed RLM v2: reason=%s iteration=%s depth=%s api_calls=%s cost=$%.4f",
        result.get("reason"),
        result.get("iteration"),
        result.get("depth"),
        machine.total_api_calls,
        machine.total_cost,
    )

    return result


async def run_from_file(
    *,
    file_path: str,
    task: str,
    max_depth: int = 5,
    timeout_seconds: int = 300,
    max_iterations: int = 20,
    max_steps: int = 80,
    sub_model_profile: str | None = None,
    model_override: str | None = None,
) -> dict[str, Any]:
    """Load context from file and run RLM v2."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    long_context = path.read_text(encoding="utf-8")
    return await run_rlm_v2(
        task=task,
        long_context=long_context,
        max_depth=max_depth,
        timeout_seconds=timeout_seconds,
        max_iterations=max_iterations,
        max_steps=max_steps,
        sub_model_profile=sub_model_profile,
        model_override=model_override,
    )


def _build_demo_context() -> str:
    sections: list[str] = []
    for i in range(1, 7):
        sections.append(
            f"""
### Chapter {i}: Position {chr(64+i)}

Main claim: Chapter {i} argues a distinct thesis around theme {i % 3}.
Evidence A: Example detail {i * 11}.
Evidence B: Counterpoint {i * 7} with caveat {i * 3}.
Long-form narrative paragraph: This chapter contains nuanced semantic information that often needs summarization
rather than direct lexical counting. It references policy, trade-offs, and synthesis markers.
""".strip()
        )

    return "\n\n".join(sections)


def demo() -> None:
    """Run local demo with synthetic long context."""
    context = _build_demo_context()
    task = (
        "For each chapter, extract the primary argument and one supporting detail, "
        "then produce a cross-chapter thesis. Set Final when done."
    )

    print("=" * 72)
    print("RLM v2 Demo")
    print("=" * 72)
    print(f"Context length: {len(context)} chars")
    print(f"Task: {task}")
    print("=" * 72)

    result = asyncio.run(
        run_rlm_v2(
            task=task,
            long_context=context,
            max_depth=5,
            timeout_seconds=300,
            max_iterations=20,
            max_steps=80,
        )
    )

    print("\nResult")
    print("-" * 72)
    print(f"Answer: {result.get('answer')}")
    print(f"Reason: {result.get('reason')}")
    print(f"Iteration: {result.get('iteration')}")
    print(f"Depth: {result.get('depth')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RLM v2: minimal recursive machine around a persistent REPL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--file", "-f", help="Path to long context file")
    parser.add_argument("--task", "-t", help="Task/instruction")

    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=80)

    parser.add_argument("--sub-model-profile", default=None)
    parser.add_argument("--model-override", default=None)

    parser.add_argument("--demo", "-d", action="store_true", help="Run demo")

    args = parser.parse_args()

    if args.demo:
        demo()
        return

    if args.file and args.task:
        result = asyncio.run(
            run_from_file(
                file_path=args.file,
                task=args.task,
                max_depth=args.max_depth,
                timeout_seconds=args.timeout_seconds,
                max_iterations=args.max_iterations,
                max_steps=args.max_steps,
                sub_model_profile=args.sub_model_profile,
                model_override=args.model_override,
            )
        )
        print(f"Answer: {result.get('answer')}")
        print(f"Reason: {result.get('reason')}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()

"""CLI and runtime entrypoint for RLM v2 example."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import platform
import uuid
from pathlib import Path
from typing import Any

from flatmachines import FlatMachine, get_logger, setup_logging

from .trace import TraceRecorder, normalize_inspect_level, parse_tag_items, utc_now_iso

setup_logging(level="INFO")
logger = get_logger(__name__)


def _config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "machine.yml"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _build_manifest(
    *,
    task: str,
    long_context: str,
    config_path: Path,
    current_depth: int,
    max_depth: int,
    timeout_seconds: int,
    max_iterations: int,
    max_steps: int,
    inspect_level: str,
    trace_dir: str,
    experiment: str | None,
    tags: dict[str, str],
) -> dict[str, Any]:
    return {
        "created_at": utc_now_iso(),
        "mode": "rlm_v2_inspect",
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "sdk_versions": {
            "flatmachines": _safe_version("flatmachines"),
            "flatagents": _safe_version("flatagents"),
            "rlm_v2_example": _safe_version("rlm-v2-example"),
        },
        "config": {
            "machine_config_path": str(config_path),
            "machine_config_sha256": _sha256_file(config_path),
            "inspect_level": inspect_level,
            "trace_dir": str(Path(trace_dir).expanduser().resolve()),
        },
        "input": {
            "task": task,
            "task_length": len(task),
            "task_preview": task[:300],
            "long_context_length": len(long_context),
            "long_context_sha256": hashlib.sha256(long_context.encode("utf-8")).hexdigest(),
            "long_context_prefix": long_context[:300],
        },
        "limits": {
            "current_depth": current_depth,
            "max_depth": max_depth,
            "timeout_seconds": timeout_seconds,
            "max_iterations": max_iterations,
            "max_steps": max_steps,
        },
        "experiment": experiment,
        "tags": tags,
    }


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
    inspect: bool = False,
    inspect_level: str = "summary",
    trace_dir: str = "./traces",
    root_run_id: str | None = None,
    parent_call_id: str | None = None,
    print_iterations: bool = False,
    experiment: str | None = None,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run the minimal recursive RLM machine."""
    config_path = _config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Machine config not found: {config_path}")

    inspect_level = normalize_inspect_level(inspect_level)
    tags = tags or {}

    if inspect and not root_run_id:
        root_run_id = str(uuid.uuid4())

    if inspect and current_depth == 0 and root_run_id:
        recorder = TraceRecorder(trace_dir=trace_dir, run_id=root_run_id)
        recorder.write_manifest(
            _build_manifest(
                task=task,
                long_context=long_context,
                config_path=config_path,
                current_depth=current_depth,
                max_depth=max_depth,
                timeout_seconds=timeout_seconds,
                max_iterations=max_iterations,
                max_steps=max_steps,
                inspect_level=inspect_level,
                trace_dir=trace_dir,
                experiment=experiment,
                tags=tags,
            )
        )

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
        "inspect": inspect,
        "inspect_level": inspect_level,
        "trace_dir": trace_dir,
        "root_run_id": root_run_id,
        "parent_call_id": parent_call_id,
        "print_iterations": print_iterations,
        "experiment": experiment,
        "tags": tags,
    }

    logger.info(
        "Starting RLM v2: context_len=%s depth=%s/%s max_iterations=%s inspect=%s",
        len(long_context),
        current_depth,
        max_depth,
        max_iterations,
        inspect,
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

    if inspect and root_run_id:
        trace_path = Path(trace_dir).expanduser().resolve() / root_run_id
        result["trace_run_id"] = root_run_id
        result["trace_path"] = str(trace_path)
        if current_depth == 0:
            logger.info("Inspect trace written to: %s", trace_path)

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
    inspect: bool = False,
    inspect_level: str = "summary",
    trace_dir: str = "./traces",
    print_iterations: bool = False,
    experiment: str | None = None,
    tags: dict[str, str] | None = None,
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
        inspect=inspect,
        inspect_level=inspect_level,
        trace_dir=trace_dir,
        print_iterations=print_iterations,
        experiment=experiment,
        tags=tags,
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


def demo(
    *,
    inspect: bool = False,
    inspect_level: str = "summary",
    trace_dir: str = "./traces",
    print_iterations: bool = False,
    experiment: str | None = None,
    tags: dict[str, str] | None = None,
) -> None:
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
            inspect=inspect,
            inspect_level=inspect_level,
            trace_dir=trace_dir,
            print_iterations=print_iterations,
            experiment=experiment,
            tags=tags,
        )
    )

    print("\nResult")
    print("-" * 72)
    print(f"Answer: {result.get('answer')}")
    print(f"Reason: {result.get('reason')}")
    print(f"Iteration: {result.get('iteration')}")
    print(f"Depth: {result.get('depth')}")
    if inspect:
        print(f"Trace: {result.get('trace_path')}")


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

    parser.add_argument("--inspect", action="store_true", help="Enable structured trace capture")
    parser.add_argument("--inspect-level", default="summary", choices=["summary", "full"])
    parser.add_argument("--trace-dir", default="./traces")
    parser.add_argument("--print-iterations", action="store_true", help="Print concise live loop progress")
    parser.add_argument("--experiment", default=None)
    parser.add_argument("--tag", action="append", default=[], help="Tag in key=value format; can be repeated")

    parser.add_argument("--demo", "-d", action="store_true", help="Run demo")

    args = parser.parse_args()
    tags = parse_tag_items(args.tag)

    if args.demo:
        demo(
            inspect=args.inspect,
            inspect_level=args.inspect_level,
            trace_dir=args.trace_dir,
            print_iterations=args.print_iterations,
            experiment=args.experiment,
            tags=tags,
        )
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
                inspect=args.inspect,
                inspect_level=args.inspect_level,
                trace_dir=args.trace_dir,
                print_iterations=args.print_iterations,
                experiment=args.experiment,
                tags=tags,
            )
        )
        print(f"Answer: {result.get('answer')}")
        print(f"Reason: {result.get('reason')}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()

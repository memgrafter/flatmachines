from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class DockerRunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        parts = []
        if self.stdout:
            parts.append(f"STDOUT:\n{self.stdout}")
        if self.stderr:
            parts.append(f"STDERR:\n{self.stderr}")
        return "\n\n".join(parts)


def example_root() -> Path:
    return Path(__file__).resolve().parents[3]


def python_dir() -> Path:
    return example_root() / "python"


def docker_dir() -> Path:
    return python_dir() / "tests" / "integration" / "docker"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False

    probe = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return probe.returncode == 0


def ensure_docker_integration_enabled(pytestconfig: pytest.Config) -> None:
    enabled = pytestconfig.getoption("run_docker_integration") or os.getenv("RUN_DOCKER_INTEGRATION") == "1"
    if not enabled:
        pytest.skip("docker integration tests are disabled; pass --run-docker-integration or set RUN_DOCKER_INTEGRATION=1")
    if not docker_available():
        pytest.skip("docker is unavailable on this host")


def build_test_image(*, dockerfile_name: str, tag_prefix: str) -> str:
    tag = f"{tag_prefix}:{uuid.uuid4().hex[:12]}"
    subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(docker_dir() / dockerfile_name),
            "-t",
            tag,
            str(docker_dir()),
        ],
        check=True,
    )
    return tag


def run_container(*, image: str, volumes: dict[Path, str], env: dict[str, str] | None = None) -> DockerRunResult:
    command = ["docker", "run", "--rm"]

    for host_path, container_path in volumes.items():
        command.extend(["-v", f"{host_path}:{container_path}"])

    for key, value in (env or {}).items():
        command.extend(["-e", f"{key}={value}"])

    command.append(image)
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    return DockerRunResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def latest_dist_dir() -> Path:
    dist_root = example_root() / "dist" / "python"
    candidates = [path for path in dist_root.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"no build artifacts found under {dist_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def assert_success(result: DockerRunResult) -> None:
    assert result.returncode == 0, result.combined_output

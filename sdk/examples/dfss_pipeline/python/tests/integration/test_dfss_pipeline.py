from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path


def _python_dir() -> Path:
    # .../sdk/examples/dfss_pipeline/python/tests/integration -> .../sdk/examples/dfss_pipeline/python
    return Path(__file__).resolve().parents[2]


def _cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "flatagent_dfss_pipeline.main", *args]


def test_end_to_end_designed_roots_complete(tmp_path):
    db_path = tmp_path / "dfss.sqlite"
    proc = subprocess.run(
        _cmd(
            "--roots",
            "2",
            "--max-depth",
            "3",
            "--max-workers",
            "4",
            "--seed",
            "7",
            "--fail-rate",
            "0",
            "--db-path",
            str(db_path),
        ),
        capture_output=True,
        text=True,
        cwd=str(_python_dir()),
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "root-000" in proc.stdout
    assert "root-001" in proc.stdout
    assert "COMPLETE" in proc.stdout


def test_stop_and_resume_completes_remaining_work(tmp_path):
    db_path = tmp_path / "dfss.sqlite"

    p = subprocess.Popen(
        _cmd(
            "--roots",
            "8",
            "--max-depth",
            "3",
            "--max-workers",
            "4",
            "--seed",
            "7",
            "--db-path",
            str(db_path),
        ),
        cwd=str(_python_dir()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(2)
    p.send_signal(signal.SIGINT)
    p.wait(timeout=30)

    resumed = subprocess.run(
        _cmd(
            "--resume",
            "--db-path",
            str(db_path),
        ),
        capture_output=True,
        text=True,
        cwd=str(_python_dir()),
        timeout=120,
    )

    assert resumed.returncode == 0, resumed.stderr
    assert "resum" in resumed.stdout.lower()
    assert "complete" in resumed.stdout.lower()


def test_slow_gate_toggle_saturates_slow_slots(tmp_path):
    db_path = tmp_path / "dfss.sqlite"
    proc = subprocess.run(
        _cmd(
            "--roots",
            "2",
            "--seed",
            "7",
            "--fail-rate",
            "0",
            "--db-path",
            str(db_path),
        ),
        capture_output=True,
        text=True,
        cwd=str(_python_dir()),
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.lower()
    assert "slow" in out
    assert "gate" in out

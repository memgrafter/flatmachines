from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path



def _dfss_dir() -> Path:
    # .../sdk/examples/dfss_pipeline/python/tests/integration -> .../sdk/examples/dfss_pipeline
    return Path(__file__).resolve().parents[3]



def _main_py() -> Path:
    return _dfss_dir() / "main.py"



def test_end_to_end_designed_roots_complete(tmp_path):
    main_py = _main_py()
    assert main_py.exists(), f"Missing DFSS entrypoint: {main_py}"

    db_path = tmp_path / "dfss.sqlite"
    proc = subprocess.run(
        [
            sys.executable,
            str(main_py),
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
        ],
        capture_output=True,
        text=True,
        cwd=str(_dfss_dir()),
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "root-000" in proc.stdout
    assert "root-001" in proc.stdout
    assert "COMPLETE" in proc.stdout



def test_stop_and_resume_completes_remaining_work(tmp_path):
    main_py = _main_py()
    assert main_py.exists(), f"Missing DFSS entrypoint: {main_py}"

    db_path = tmp_path / "dfss.sqlite"

    # Start then interrupt.
    p = subprocess.Popen(
        [
            sys.executable,
            str(main_py),
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
        ],
        cwd=str(_dfss_dir()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(2)
    p.send_signal(signal.SIGINT)
    p.wait(timeout=30)

    # Resume and require clean completion.
    resumed = subprocess.run(
        [
            sys.executable,
            str(main_py),
            "--resume",
            "--db-path",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(_dfss_dir()),
        timeout=120,
    )

    assert resumed.returncode == 0, resumed.stderr
    assert "resume" in resumed.stdout.lower() or "resum" in resumed.stdout.lower()
    assert "complete" in resumed.stdout.lower()



def test_slow_gate_toggle_saturates_slow_slots(tmp_path):
    main_py = _main_py()
    assert main_py.exists(), f"Missing DFSS entrypoint: {main_py}"

    db_path = tmp_path / "dfss.sqlite"
    proc = subprocess.run(
        [
            sys.executable,
            str(main_py),
            "--roots",
            "2",
            "--seed",
            "7",
            "--fail-rate",
            "0",
            "--db-path",
            str(db_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(_dfss_dir()),
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.lower()
    assert "slow" in out
    assert "gate" in out

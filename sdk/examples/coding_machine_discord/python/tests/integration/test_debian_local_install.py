from __future__ import annotations

import os

import pytest

from ._docker import assert_success, run_container


pytestmark = pytest.mark.integration


def test_local_bundle_install_in_minimal_debian(built_bundle_dir: Path, run_container_image: str) -> None:
    result = run_container(
        image=run_container_image,
        volumes={built_bundle_dir: "/artifacts"},
        env={
            "ARTIFACT_DIR": "/artifacts",
            "INSTALL_DIR": os.getenv("MK42_DEBIAN_INSTALL_DIR", "/tmp/mk42-test"),
        },
    )
    assert_success(result)

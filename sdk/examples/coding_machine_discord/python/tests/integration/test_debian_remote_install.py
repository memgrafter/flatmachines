from __future__ import annotations

import os

import pytest

from ._docker import assert_success, run_container


pytestmark = pytest.mark.integration


def test_remote_latest_release_install_in_minimal_debian(run_container_image: str) -> None:
    result = run_container(
        image=run_container_image,
        env={
            "INSTALL_MODE": "remote",
            "INSTALL_DIR": os.getenv("MK42_DEBIAN_REMOTE_INSTALL_DIR", "/tmp/mk42-remote-test"),
            "REMOTE_INSTALL_SCRIPT_URL": os.getenv(
                "MK42_REMOTE_INSTALL_SCRIPT_URL",
                "https://github.com/memgrafter/flatmachines/releases/download/mk42_dev-0.1.0-20260418T225211Z-f36ef8019476/install.sh",
            ),
            "REMOTE_MANIFEST_URL": os.getenv(
                "MK42_REMOTE_MANIFEST_URL",
                "https://github.com/memgrafter/flatmachines/releases/download/mk42_dev-0.1.0-20260418T225211Z-f36ef8019476/manifest.json",
            ),
        },
    )
    assert_success(result)

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ._docker import assert_success, build_test_image, ensure_docker_integration_enabled, example_root, latest_dist_dir, run_container


BUILD_IMAGE_TAG_PREFIX = "mk42-debian-build-test"
RUN_IMAGE_TAG_PREFIX = "mk42-debian-run-test"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--skip-docker-integration",
        action="store_true",
        default=False,
        help="skip docker-backed Debian integration tests",
    )


@pytest.fixture(scope="session")
def build_container_image(pytestconfig: pytest.Config) -> str:
    ensure_docker_integration_enabled(pytestconfig)
    return build_test_image(dockerfile_name="Dockerfile.debian-build", tag_prefix=BUILD_IMAGE_TAG_PREFIX)


@pytest.fixture(scope="session")
def run_container_image(pytestconfig: pytest.Config) -> str:
    ensure_docker_integration_enabled(pytestconfig)
    return build_test_image(dockerfile_name="Dockerfile.debian-run", tag_prefix=RUN_IMAGE_TAG_PREFIX)


@pytest.fixture(scope="session")
def built_bundle_dir(pytestconfig: pytest.Config, build_container_image: str) -> Path:
    ensure_docker_integration_enabled(pytestconfig)

    result = run_container(
        image=build_container_image,
        volumes={example_root(): "/workspace"},
        env={
            "BUILD_BUNDLE_ARGS": os.getenv("MK42_DEBIAN_BUILD_ARGS", ""),
        },
    )
    assert_success(result)
    return latest_dist_dir()

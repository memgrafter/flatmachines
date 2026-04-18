from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


REQUIRED_ARTIFACTS = (
    "install.sh",
    "manifest.json",
    "checksums.txt",
)


def test_build_bundle_in_minimal_debian(built_bundle_dir: Path) -> None:
    for relative_path in REQUIRED_ARTIFACTS:
        assert (built_bundle_dir / relative_path).is_file(), relative_path

    bundles = sorted(built_bundle_dir.glob("mk42-bundle-*.tar.gz"))
    assert bundles, f"no mk42 bundle tarball found in {built_bundle_dir}"

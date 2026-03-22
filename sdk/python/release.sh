#!/bin/bash
set -e

cd "$(dirname "$0")"
SDK_DIR="$(pwd)"
REPO_ROOT="$SDK_DIR/../.."
PACKAGES="flatagents flatmachines"

# Parse arguments
DRY_RUN=true  # Safe by default, note that dry run DOES change local assets.
while [[ $# -gt 0 ]]; do
    case $1 in
        --apply)
            DRY_RUN=false
            shift
            ;;
        *)
            echo "Unknown flag: $1"
            echo "Usage: $0 [--apply]"
            echo ""
            echo "Options:"
            echo "  --apply    Actually upload to PyPI (default is dry-run)"
            exit 1
            ;;
    esac
done

echo "=== Python SDK Release ==="
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  DRY RUN MODE (will not upload to PyPI)"
    echo "  Run with --apply to actually release"
    echo "════════════════════════════════════════════════════════════"
fi
echo ""

# Setup virtualenv with build tools
if [ ! -d ~/virtualenvs/twine ]; then
    python3 -m venv ~/virtualenvs/twine
    ~/virtualenvs/twine/bin/pip install --upgrade build twine
fi
source ~/virtualenvs/twine/bin/activate

# Sync and validate __version__ with pyproject.toml for each package
for PKG in $PACKAGES; do
export PKG
cd "$SDK_DIR/$PKG"
echo "Checking $PKG version..."

PYPROJECT_VERSION=$(python - <<'PY'
import pathlib
import re

text = pathlib.Path("pyproject.toml").read_text().splitlines()
in_project = False
version = ""
for line in text:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        in_project = stripped == "[project]"
        continue
    if not in_project:
        continue
    match = re.match(r'version\s*=\s*"([^"]+)"', stripped)
    if match:
        version = match.group(1)
        break
print(version)
PY
)
export PYPROJECT_VERSION

CURRENT_INIT_VERSION=$(python - <<'PY'
import pathlib
import re
import os

pkg = os.environ.get("PKG", "flatagents")
text = pathlib.Path(f"{pkg}/__init__.py").read_text()
match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "")
PY
)

if [[ -z "$PYPROJECT_VERSION" ]]; then
    echo "RELEASE ABORTED: Could not read [project] version from $PKG/pyproject.toml."
    exit 1
fi

if [[ -z "$CURRENT_INIT_VERSION" ]]; then
    echo "RELEASE ABORTED: __version__ not found in $PKG/$PKG/__init__.py."
    exit 1
fi

if [[ "$CURRENT_INIT_VERSION" != "$PYPROJECT_VERSION" ]]; then
    echo "Updating $PKG/$PKG/__init__.py __version__ to $PYPROJECT_VERSION"
    export PKG
    python - <<'PY'
import os
import pathlib
import re

pkg = os.environ["PKG"]
path = pathlib.Path(f"{pkg}/__init__.py")
text = path.read_text()
version = os.environ["PYPROJECT_VERSION"]
updated, count = re.subn(
    r'^__version__\s*=\s*"[^"]+"',
    f'__version__ = "{version}"',
    text,
    flags=re.M,
)
if count != 1:
    raise SystemExit(f"RELEASE ABORTED: __version__ not found or ambiguous in {pkg}/__init__.py")
path.write_text(updated)
PY
fi

UPDATED_INIT_VERSION=$(python - <<'PY'
import pathlib
import re
import os

pkg = os.environ.get("PKG", "flatagents")
text = pathlib.Path(f"{pkg}/__init__.py").read_text()
match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "")
PY
)

if [[ "$UPDATED_INIT_VERSION" != "$PYPROJECT_VERSION" ]]; then
    echo "RELEASE ABORTED: $PKG __version__ does not match pyproject.toml."
    exit 1
fi
done
cd "$SDK_DIR"

# Copy root TypeScript specs to sdk assets for each package
for PKG in $PACKAGES; do
    ASSETS_DIR="$SDK_DIR/$PKG/$PKG/assets"
    cp "$REPO_ROOT/flatagent.d.ts" "$REPO_ROOT/flatmachine.d.ts" "$REPO_ROOT/profiles.d.ts" "$ASSETS_DIR/"
done

# Extract versions from root TypeScript specs
echo "Extracting spec versions from TypeScript files..."
# Ensure dependencies are installed
if [ ! -d "$REPO_ROOT/scripts/node_modules" ]; then
    echo "Installing script dependencies..."
    (cd "$REPO_ROOT/scripts" && npm install --silent)
fi
FLATAGENT_VERSION=$(cd "$REPO_ROOT/scripts" && npx tsx generate-spec-assets.ts --extract-version "$REPO_ROOT/flatagent.d.ts")
FLATMACHINE_VERSION=$(cd "$REPO_ROOT/scripts" && npx tsx generate-spec-assets.ts --extract-version "$REPO_ROOT/flatmachine.d.ts")
PROFILES_VERSION=$(cd "$REPO_ROOT/scripts" && npx tsx generate-spec-assets.ts --extract-version "$REPO_ROOT/profiles.d.ts")
RUNTIME_VERSION=$(cd "$REPO_ROOT/scripts" && npx tsx generate-spec-assets.ts --extract-version "$REPO_ROOT/flatagents-runtime.d.ts")

echo "TypeScript spec versions:"
echo "  flatagent.d.ts:          $FLATAGENT_VERSION"
echo "  flatmachine.d.ts:        $FLATMACHINE_VERSION"
echo "  profiles.d.ts:           $PROFILES_VERSION"
echo "  flatagents-runtime.d.ts: $RUNTIME_VERSION"
echo ""

# Validate SDK __version__ matches spec versions (all specs unified to same version)
echo "Checking Python SDK version..."
echo "  __version__: $PYPROJECT_VERSION"

FAILED=0

if [[ "$PYPROJECT_VERSION" != "$FLATAGENT_VERSION" ]]; then
    echo "  ✗ SDK version ($PYPROJECT_VERSION) != flatagent.d.ts ($FLATAGENT_VERSION)"
    FAILED=1
else
    echo "  ✓ SDK version matches flatagent.d.ts ($FLATAGENT_VERSION)"
fi

if [[ "$PYPROJECT_VERSION" != "$FLATMACHINE_VERSION" ]]; then
    echo "  ✗ SDK version ($PYPROJECT_VERSION) != flatmachine.d.ts ($FLATMACHINE_VERSION)"
    FAILED=1
else
    echo "  ✓ SDK version matches flatmachine.d.ts ($FLATMACHINE_VERSION)"
fi

if [[ "$PYPROJECT_VERSION" != "$PROFILES_VERSION" ]]; then
    echo "  ✗ SDK version ($PYPROJECT_VERSION) != profiles.d.ts ($PROFILES_VERSION)"
    FAILED=1
else
    echo "  ✓ SDK version matches profiles.d.ts ($PROFILES_VERSION)"
fi

if [[ "$PYPROJECT_VERSION" != "$RUNTIME_VERSION" ]]; then
    echo "  ✗ SDK version ($PYPROJECT_VERSION) != flatagents-runtime.d.ts ($RUNTIME_VERSION)"
    FAILED=1
else
    echo "  ✓ SDK version matches flatagents-runtime.d.ts ($RUNTIME_VERSION)"
fi

if [[ "$FAILED" -eq 1 ]]; then
    echo ""
    echo "RELEASE ABORTED: SDK version mismatch with TypeScript specs."
    echo "Update version in pyproject.toml to match spec versions."
    exit 1
fi

echo ""

# Generate spec assets from root specs for each package
for PKG in $PACKAGES; do
    ASSETS_DIR="$SDK_DIR/$PKG/$PKG/assets"
    echo "Generating spec assets for $PKG..."
    "$REPO_ROOT/scripts/generate-spec-assets.sh" "$ASSETS_DIR"

    # Verify generated assets match root specs
    echo "Verifying $PKG spec assets..."
    FAILED=0

    for file in flatagent.d.ts flatmachine.d.ts profiles.d.ts flatagents-runtime.d.ts; do
        if [ ! -f "$ASSETS_DIR/$file" ]; then
            echo "  ✗ $file (missing)"
            FAILED=1
        elif ! diff -q "$REPO_ROOT/$file" "$ASSETS_DIR/$file" > /dev/null 2>&1; then
            echo "  ✗ $file (does not match root)"
            FAILED=1
        else
            echo "  ✓ $file"
        fi
    done

    for file in flatagent.slim.d.ts flatmachine.slim.d.ts profiles.slim.d.ts flatagents-runtime.slim.d.ts \
                flatagent.schema.json flatmachine.schema.json profiles.schema.json flatagents-runtime.schema.json; do
        if [ ! -f "$ASSETS_DIR/$file" ]; then
            echo "  ✗ $file (missing)"
            FAILED=1
        else
            echo "  ✓ $file"
        fi
    done

    if [ "$FAILED" -eq 1 ]; then
        echo ""
        echo "RELEASE ABORTED: Spec asset generation failed for $PKG."
        exit 1
    fi
done
echo "All spec assets verified."
echo ""

# Build and upload each package
for PKG in $PACKAGES; do
    cd "$SDK_DIR/$PKG"
    echo "Building $PKG..."
    rm -rf dist/ build/ *.egg-info
    python -m build

    if [ "$DRY_RUN" = true ]; then
        echo "DRY RUN: Skipping PyPI upload for $PKG."
        echo "Built: $(ls dist/*.whl | head -1 | xargs basename)"
    else
        twine upload dist/*
        echo "Released $(ls dist/*.whl | head -1 | xargs basename)"
    fi
    echo ""
done

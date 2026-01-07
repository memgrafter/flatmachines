#!/bin/bash
set -e

cd "$(dirname "$0")"
SDK_DIR="$(pwd)"
REPO_ROOT="$SDK_DIR/../.."
ASSETS_DIR="$SDK_DIR/flatagents/assets"

# Parse arguments
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run|-n)
            DRY_RUN=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo "=== Python SDK Release Validation ==="
if [ "$DRY_RUN" = true ]; then
    echo "(DRY RUN - will not upload to PyPI)"
fi
echo ""

# Sync and validate __version__ with pyproject.toml
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

text = pathlib.Path("flatagents/__init__.py").read_text()
match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "")
PY
)

if [[ -z "$PYPROJECT_VERSION" ]]; then
    echo "RELEASE ABORTED: Could not read [project] version from pyproject.toml."
    exit 1
fi

if [[ -z "$CURRENT_INIT_VERSION" ]]; then
    echo "RELEASE ABORTED: __version__ not found in flatagents/__init__.py."
    exit 1
fi

if [[ "$CURRENT_INIT_VERSION" != "$PYPROJECT_VERSION" ]]; then
    echo "Updating flatagents/__init__.py __version__ to $PYPROJECT_VERSION"
    python - <<'PY'
import os
import pathlib
import re

path = pathlib.Path("flatagents/__init__.py")
text = path.read_text()
version = os.environ["PYPROJECT_VERSION"]
updated, count = re.subn(
    r'^__version__\s*=\s*"[^"]+"',
    f'__version__ = "{version}"',
    text,
    flags=re.M,
)
if count != 1:
    raise SystemExit("RELEASE ABORTED: __version__ not found or ambiguous in flatagents/__init__.py")
path.write_text(updated)
PY
fi

UPDATED_INIT_VERSION=$(python - <<'PY'
import pathlib
import re

text = pathlib.Path("flatagents/__init__.py").read_text()
match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
print(match.group(1) if match else "")
PY
)

if [[ "$UPDATED_INIT_VERSION" != "$PYPROJECT_VERSION" ]]; then
    echo "RELEASE ABORTED: __version__ does not match pyproject.toml."
    exit 1
fi

# Copy root TypeScript specs to sdk assets
cp "$REPO_ROOT/flatagent.d.ts" "$REPO_ROOT/flatmachine.d.ts" "$ASSETS_DIR/"

# Copy root README for PyPI (hatchling requires readme in package dir)
cp "$REPO_ROOT/README.md" "$SDK_DIR/README.md"

# Validate README copy succeeded
if ! diff -q "$REPO_ROOT/README.md" "$SDK_DIR/README.md" > /dev/null 2>&1; then
    echo "RELEASE ABORTED: README.md does not match root. Ensure copy step is present."
    exit 1
fi
echo "✓ README.md synced from root"

# Extract versions from root TypeScript specs
echo "Extracting spec versions from TypeScript files..."
FLATAGENT_VERSION=$(npx -y tsx "$REPO_ROOT/scripts/generate-spec-assets.ts" --extract-version "$REPO_ROOT/flatagent.d.ts")
FLATMACHINE_VERSION=$(npx -y tsx "$REPO_ROOT/scripts/generate-spec-assets.ts" --extract-version "$REPO_ROOT/flatmachine.d.ts")

echo "TypeScript spec versions:"
echo "  flatagent.d.ts:   $FLATAGENT_VERSION"
echo "  flatmachine.d.ts: $FLATMACHINE_VERSION"
echo ""

# Extract versions from Python SDK
echo "Checking Python SDK versions..."
SDK_FLATAGENT_VERSION=$(grep -E '^\s*SPEC_VERSION\s*=\s*' flatagents/flatagent.py | grep -oE '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"')
SDK_FLATMACHINE_VERSION=$(grep -E '^\s*SPEC_VERSION\s*=\s*' flatagents/flatmachine.py | grep -oE '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"')

echo "Python SDK versions:"
echo "  flatagent.py:   $SDK_FLATAGENT_VERSION"
echo "  flatmachine.py: $SDK_FLATMACHINE_VERSION"
echo ""

# Validate versions match
FAILED=0

if [[ "$SDK_FLATAGENT_VERSION" != "$FLATAGENT_VERSION" ]]; then
    echo "  ✗ flatagent.py version ($SDK_FLATAGENT_VERSION) != spec version ($FLATAGENT_VERSION)"
    FAILED=1
else
    echo "  ✓ flatagent.py matches spec ($FLATAGENT_VERSION)"
fi

if [[ "$SDK_FLATMACHINE_VERSION" != "$FLATMACHINE_VERSION" ]]; then
    echo "  ✗ flatmachine.py version ($SDK_FLATMACHINE_VERSION) != spec version ($FLATMACHINE_VERSION)"
    FAILED=1
else
    echo "  ✓ flatmachine.py matches spec ($FLATMACHINE_VERSION)"
fi

if [[ "$FAILED" -eq 1 ]]; then
    echo ""
    echo "RELEASE ABORTED: SDK version mismatch with TypeScript specs."
    echo "Update SPEC_VERSION in flatagent.py and/or flatmachine.py to match."
    exit 1
fi

echo ""

# Generate spec assets from root specs
echo "Generating spec assets..."
"$REPO_ROOT/scripts/generate-spec-assets.sh" "$ASSETS_DIR"
echo ""

# Verify generated assets match root specs
echo "Verifying spec assets..."
FAILED=0

for file in flatagent.d.ts flatmachine.d.ts; do
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

for file in flatagent.slim.d.ts flatmachine.slim.d.ts \
            flatagent.schema.json flatmachine.schema.json; do
    if [ ! -f "$ASSETS_DIR/$file" ]; then
        echo "  ✗ $file (missing)"
        FAILED=1
    else
        echo "  ✓ $file"
    fi
done

if [ "$FAILED" -eq 1 ]; then
    echo ""
    echo "RELEASE ABORTED: Spec asset generation failed."
    exit 1
fi
echo "All spec assets verified."
echo ""

# Setup virtualenv with build tools
if [ ! -d ~/virtualenvs/twine ]; then
    python -m venv ~/virtualenvs/twine
    ~/virtualenvs/twine/bin/pip install --upgrade build twine
fi
source ~/virtualenvs/twine/bin/activate

# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build
python -m build

# Upload to PyPI (unless dry-run)
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "DRY RUN: Skipping PyPI upload."
    echo "Built: $(ls dist/*.whl | head -1 | xargs basename)"
else
    twine upload dist/*
    echo "Released $(ls dist/*.whl | head -1 | xargs basename)"
fi

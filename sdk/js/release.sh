#!/bin/bash
set -e

cd "$(dirname "$0")"
SDK_DIR="$(pwd)"
REPO_ROOT="$SDK_DIR/../.."

# Parse arguments
DRY_RUN=true
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
            echo "  --apply    Actually publish to npm (default is dry-run)"
            exit 1
            ;;
    esac
done

echo "=== JavaScript SDK Release (dual-package) ==="
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  DRY RUN MODE (will not publish to npm)"
    echo "  Run with --apply to actually release"
    echo "════════════════════════════════════════════════════════════"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Version validation
# ─────────────────────────────────────────────────────────────────────────────

AGENTS_VERSION=$(node -p "require('./packages/flatagents/package.json').version")
MACHINES_VERSION=$(node -p "require('./packages/flatmachines/package.json').version")
WORKSPACE_VERSION=$(node -p "require('./package.json').version")

echo "Package versions:"
echo "  @anthropic/flatagents:    $AGENTS_VERSION"
echo "  @anthropic/flatmachines:  $MACHINES_VERSION"
echo "  workspace:                $WORKSPACE_VERSION"

if [[ "$AGENTS_VERSION" != "$MACHINES_VERSION" ]]; then
    echo ""
    echo "RELEASE ABORTED: flatagents ($AGENTS_VERSION) != flatmachines ($MACHINES_VERSION)"
    exit 1
fi

if [[ "$AGENTS_VERSION" != "$WORKSPACE_VERSION" ]]; then
    echo ""
    echo "RELEASE ABORTED: package version ($AGENTS_VERSION) != workspace version ($WORKSPACE_VERSION)"
    exit 1
fi

PACKAGE_VERSION="$AGENTS_VERSION"

# Validate flatmachines depends on the same version of flatagents
MACHINES_AGENT_DEP=$(node -p "require('./packages/flatmachines/package.json').dependencies['@anthropic/flatagents']")
if [[ "$MACHINES_AGENT_DEP" != "$PACKAGE_VERSION" ]]; then
    echo ""
    echo "RELEASE ABORTED: flatmachines depends on flatagents@$MACHINES_AGENT_DEP, expected $PACKAGE_VERSION"
    exit 1
fi
echo "  ✓ flatmachines → flatagents dependency version matches"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Spec version validation
# ─────────────────────────────────────────────────────────────────────────────

if [ ! -d "$REPO_ROOT/scripts/node_modules" ]; then
    echo "Installing script dependencies..."
    (cd "$REPO_ROOT/scripts" && npm install --silent)
fi

echo "Extracting spec versions from TypeScript files..."
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

FAILED=0

for SPEC_NAME in FLATAGENT FLATMACHINE PROFILES RUNTIME; do
    SPEC_VAR="${SPEC_NAME}_VERSION"
    SPEC_VAL="${!SPEC_VAR}"
    if [[ "$PACKAGE_VERSION" != "$SPEC_VAL" ]]; then
        echo "  ✗ SDK version ($PACKAGE_VERSION) != ${SPEC_NAME,,}.d.ts ($SPEC_VAL)"
        FAILED=1
    else
        echo "  ✓ SDK version matches ${SPEC_NAME,,}.d.ts ($SPEC_VAL)"
    fi
done

if [[ "$FAILED" -eq 1 ]]; then
    echo ""
    echo "RELEASE ABORTED: SDK version mismatch with TypeScript specs."
    echo "Run: scripts/update-spec-versions.sh <version> --js --apply"
    exit 1
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Schema validation (check both package dirs)
# ─────────────────────────────────────────────────────────────────────────────

echo "Checking schemas/ folder versions..."
SCHEMA_SPECS=("flatagent" "flatmachine" "profiles" "flatagents-runtime")
SCHEMA_FAILED=0

for spec in "${SCHEMA_SPECS[@]}"; do
    # Check in root schemas/ (legacy) or package schemas/
    SCHEMA_FILE="schemas/${spec}.d.ts"
    if [[ ! -f "$SCHEMA_FILE" ]]; then
        echo "  ⚠ $SCHEMA_FILE not found (skipped)"
        continue
    fi
    SCHEMA_VERSION=$(cd "$REPO_ROOT/scripts" && npx tsx generate-spec-assets.ts --extract-version "$SDK_DIR/$SCHEMA_FILE")
    if [[ "$SCHEMA_VERSION" != "$PACKAGE_VERSION" ]]; then
        echo "  ✗ $SCHEMA_FILE version ($SCHEMA_VERSION) != package.json ($PACKAGE_VERSION)"
        SCHEMA_FAILED=1
    else
        echo "  ✓ $SCHEMA_FILE ($SCHEMA_VERSION)"
    fi
done

if [[ "$SCHEMA_FAILED" -eq 1 ]]; then
    echo ""
    echo "RELEASE ABORTED: schemas/ folder out of sync."
    echo "Run: npx tsx scripts/generate-spec-assets.ts"
    exit 1
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Install & Build
# ─────────────────────────────────────────────────────────────────────────────

echo "Installing dependencies..."
npm install --silent
echo ""

echo "Building @anthropic/flatagents..."
npm run build:agents
echo ""

echo "Building @anthropic/flatmachines..."
npm run build:machines
echo ""

# Verify build output
for PKG in flatagents flatmachines; do
    if [ ! -f "packages/$PKG/dist/index.js" ] || [ ! -f "packages/$PKG/dist/index.d.ts" ]; then
        echo "RELEASE ABORTED: packages/$PKG/dist missing build artifacts."
        exit 1
    fi
done
echo "  ✓ Build output verified for both packages."
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Publish
# ─────────────────────────────────────────────────────────────────────────────

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN: Running npm publish --dry-run for both packages..."
    echo ""

    echo "── @anthropic/flatagents ──"
    (cd packages/flatagents && npm publish --dry-run)
    echo ""

    echo "── @anthropic/flatmachines ──"
    (cd packages/flatmachines && npm publish --dry-run)
    echo ""

    echo "DRY RUN complete. Run with --apply to publish to npm."
else
    if [ -z "$NPMJS_TOKEN_MEMGRAFTER" ]; then
        echo "RELEASE ABORTED: NPMJS_TOKEN_MEMGRAFTER is not set."
        echo "Set NPMJS_TOKEN_MEMGRAFTER to an npm automation token before publishing."
        exit 1
    fi

    NPMRC_TMP="$(mktemp)"
    trap 'rm -f "$NPMRC_TMP"' EXIT
    echo "//registry.npmjs.org/:_authToken=${NPMJS_TOKEN_MEMGRAFTER}" > "$NPMRC_TMP"

    # Publish flatagents first (flatmachines depends on it)
    echo "Publishing @anthropic/flatagents@$PACKAGE_VERSION..."
    (cd packages/flatagents && NPM_CONFIG_USERCONFIG="$NPMRC_TMP" npm publish)
    echo ""

    echo "Publishing @anthropic/flatmachines@$PACKAGE_VERSION..."
    (cd packages/flatmachines && NPM_CONFIG_USERCONFIG="$NPMRC_TMP" npm publish)
    echo ""

    echo "Released:"
    echo "  @anthropic/flatagents@$PACKAGE_VERSION"
    echo "  @anthropic/flatmachines@$PACKAGE_VERSION"
fi

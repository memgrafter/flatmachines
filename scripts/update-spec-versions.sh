#!/bin/bash
# Update spec_version across source-of-truth files in lockstep
# Usage: update-spec-versions.sh <new-version> [options]
#
# By default, only updates root .d.ts specs and markdown docs.
# Use SDK flags to also update SDK-specific files.

set -e

if [[ "$(uname)" == "Darwin" ]]; then
    sed_i() { sed -i '' -E "$@"; }
else
    sed_i() { sed -i -E "$@"; }
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Parse arguments
NEW_VERSION=""
DRY_RUN=true
UPDATE_PYTHON=false
UPDATE_JS=false
UPDATE_EXAMPLES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --apply)
            DRY_RUN=false
            shift
            ;;
        --python)
            UPDATE_PYTHON=true
            shift
            ;;
        --js)
            UPDATE_JS=true
            shift
            ;;
        --examples)
            UPDATE_EXAMPLES=true
            shift
            ;;
        --*)
            echo "Error: Unknown flag: $1"
            exit 1
            ;;
        *)
            if [[ -z "$NEW_VERSION" ]]; then
                # Validate semver immediately
                if ! [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                    echo "Error: Version must be semver format (e.g., 0.8.0), got: $1"
                    exit 1
                fi
                NEW_VERSION="$1"
            else
                echo "Error: Unexpected argument: $1"
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$NEW_VERSION" ]]; then
    echo "Usage: update-spec-versions.sh <new-version> [options]"
    echo ""
    echo "Options:"
    echo "  --apply     Actually apply changes (default is dry-run)"
    echo "  --python    Also update Python SDK"
    echo "  --js        Also update JavaScript SDK (npm)"
    echo "  --examples  Also update shared examples (sdk/examples/*/config/*.yml)"
    echo ""
    echo "What gets updated:"
    echo "  Always:     Root .d.ts specs, README.md, MACHINES.md"
    echo "  --python:   sdk/python/flatagents/pyproject.toml, sdk/python/flatmachines/pyproject.toml"
    echo "              sdk/python/flatagents/flatagents/__init__.py"
    echo "              sdk/python/flatmachines/flatmachines/__init__.py"
    echo "  --js:       sdk/js/package.json"
    echo "  --examples: sdk/examples/**/*.yml"
    echo ""
    echo "NOT updated (generated from sources):"
    echo "  - assets/*.d.ts (run scripts/generate-spec-assets.sh)"
    echo "  - sdk/python/flatagents/flatagents/assets/*.d.ts (run sdk/python/release.sh)"
    echo "  - sdk/python/flatmachines/flatmachines/assets/*.d.ts (run sdk/python/release.sh)"
    echo ""
    echo "Examples:"
    echo "  update-spec-versions.sh 0.8.0              # dry-run, specs only"
    echo "  update-spec-versions.sh 0.8.0 --apply      # apply specs only"
    echo "  update-spec-versions.sh 0.8.0 --python --js --examples --apply"
    exit 1
fi

# Banner
if [[ "$DRY_RUN" == true ]]; then
    echo "════════════════════════════════════════════════════════════"
    echo "  DRY RUN MODE (no changes will be made)"
    echo "  Run with --apply to actually update files"
    echo "════════════════════════════════════════════════════════════"
    echo ""
fi

echo "Target version: $NEW_VERSION"
echo "Update Python SDK: $UPDATE_PYTHON"
echo "Update JavaScript SDK: $UPDATE_JS"
echo "Update shared examples: $UPDATE_EXAMPLES"
echo ""

cd "$REPO_ROOT"

# Counters
UPDATED=0
WOULD_UPDATE=0

# Update file if pattern matches (sed is idempotent if already at target)
update_file() {
    local file="$1"
    local pattern="$2"
    local replacement="$3"

    [[ -f "$file" ]] || return
    rg -q "$pattern" "$file" 2>/dev/null || return  # Pattern not found

    if [[ "$DRY_RUN" == true ]]; then
        echo "  Would update: $file"
        ((++WOULD_UPDATE))
    else
        sed_i "s/$pattern/$replacement/" "$file"
        echo "  Updated: $file"
        ((++UPDATED))
    fi
}

# Update yml files in a directory that have outdated spec_version
update_yml_files() {
    local search_path="$1"
    local pattern="(spec_version:[[:space:]]*[\"']?)[0-9]+\.[0-9]+\.[0-9]+([\"']?)"
    local escaped_version="${NEW_VERSION//./\\.}"

    # Find files with spec_version not at target version
    while read -r file; do
        # Skip if already at target version or in excluded dirs
        [[ "$file" == *".venv"* || "$file" == *"node_modules"* ]] && continue
        rg -q "spec_version.*$escaped_version" "$file" 2>/dev/null && continue
        update_file "$file" "$pattern" "\1$NEW_VERSION\2"
    done < <(rg -l 'spec_version.*[0-9]+\.[0-9]+\.[0-9]+' "$search_path" --glob '*.yml' 2>/dev/null)
}

# =============================================================================
# 1. ROOT .d.ts SPECS (source of truth)
# =============================================================================
echo "Root .d.ts specs:"
for file in flatagent.d.ts flatmachine.d.ts flatagents-runtime.d.ts profiles.d.ts; do
    update_file "$file" "(SPEC_VERSION = \")[0-9]+\.[0-9]+\.[0-9]+(\")" "\1$NEW_VERSION\2"
done
echo ""

# =============================================================================
# 2. MARKDOWN DOCS (inline examples)
# =============================================================================
echo "Markdown docs:"
for file in README.md MACHINES.md; do
    update_file "$file" "(spec_version:[[:space:]]*[\"'])[0-9]+\.[0-9]+\.[0-9]+([\"'])" "\1$NEW_VERSION\2"
done
echo ""

# =============================================================================
# 3. PYTHON SDK (if --python)
# =============================================================================
if [[ "$UPDATE_PYTHON" == true ]]; then
    echo "Python SDK:"

    # pyproject.toml
    update_file "sdk/python/flatagents/pyproject.toml" "(^version = \")[0-9]+\.[0-9]+\.[0-9]+(\")" "\1$NEW_VERSION\2"
    update_file "sdk/python/flatmachines/pyproject.toml" "(^version = \")[0-9]+\.[0-9]+\.[0-9]+(\")" "\1$NEW_VERSION\2"

    # __init__.py __version__
    update_file "sdk/python/flatagents/flatagents/__init__.py" "(__version__ = \")[0-9]+\.[0-9]+\.[0-9]+(\")" "\1$NEW_VERSION\2"
    update_file "sdk/python/flatmachines/flatmachines/__init__.py" "(__version__ = \")[0-9]+\.[0-9]+\.[0-9]+(\")" "\1$NEW_VERSION\2"
    echo ""
fi

# =============================================================================
# 4. JAVASCRIPT SDK (if --js)
# =============================================================================
if [[ "$UPDATE_JS" == true ]]; then
    echo "JavaScript SDK:"

    # package.json
    update_file "sdk/js/package.json" "(\"version\":[[:space:]]*\")[0-9]+\.[0-9]+\.[0-9]+(\")" "\1$NEW_VERSION\2"
    echo ""
fi

# =============================================================================
# 5. SHARED EXAMPLES (if --examples)
# =============================================================================
if [[ "$UPDATE_EXAMPLES" == true ]]; then
    echo "Shared examples (sdk/examples/**/*.yml):"
    update_yml_files "sdk/examples"
    echo ""
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo "════════════════════════════════════════════════════════════"
if [[ "$DRY_RUN" == true ]]; then
    echo "Would update $WOULD_UPDATE file(s)"
    echo ""
    echo "Run with --apply to make changes."
else
    echo "Updated $UPDATED file(s)"
    echo ""
    echo "Next steps:"
    echo "  1. Run 'scripts/generate-spec-assets.sh' to regenerate assets"
    echo "  2. Run 'scripts/lint-spec-versions.sh' to verify"
    if [[ "$UPDATE_PYTHON" == true ]]; then
        echo "  3. Run 'sdk/python/flatagents/release.sh' to build & verify Python SDK"
        echo "  3. Run 'sdk/python/flatmachines/release.sh' to build & verify Python SDK"
    fi
    if [[ "$UPDATE_JS" == true ]]; then
        echo "  3. Run 'cd sdk/js && npm publish' to publish to npm"
    fi
    if [[ "$UPDATE_EXAMPLES" == true ]]; then
        echo "  Note: Test shared examples with your SDK of choice"
    fi
fi
echo "════════════════════════════════════════════════════════════"

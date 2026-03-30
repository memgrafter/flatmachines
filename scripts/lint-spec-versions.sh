#!/bin/bash
# Lint spec_version references against .d.ts SPEC_VERSION constants
# Usage: lint-spec-versions.sh [repo-root]
# Exit: 0 if all versions match, 1 if mismatches found

set -e

# Get the repo root - script can be run from anywhere
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-.}"

# If relative path, make it relative to script location
if [[ ! "$REPO_ROOT" = /* ]]; then
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)/$REPO_ROOT"
fi

FLATAGENT_SPEC="$REPO_ROOT/flatagent.d.ts"
FLATMACHINE_SPEC="$REPO_ROOT/flatmachine.d.ts"
PROFILES_SPEC="$REPO_ROOT/profiles.d.ts"
EXTRACTOR="$SCRIPT_DIR/generate-spec-assets.ts"

# Verify spec files exist
if [[ ! -f "$FLATAGENT_SPEC" ]]; then
    echo "Error: flatagent.d.ts not found at $FLATAGENT_SPEC"
    exit 1
fi

if [[ ! -f "$FLATMACHINE_SPEC" ]]; then
    echo "Error: flatmachine.d.ts not found at $FLATMACHINE_SPEC"
    exit 1
fi

if [[ ! -f "$PROFILES_SPEC" ]]; then
    echo "Error: profiles.d.ts not found at $PROFILES_SPEC"
    exit 1
fi

# Extract spec versions using the TypeScript extractor
echo "Extracting spec versions from SPEC_VERSION constants..."
FLATAGENT_VERSION=$(cd "$SCRIPT_DIR" && npx tsx generate-spec-assets.ts --extract-version "$FLATAGENT_SPEC")
FLATMACHINE_VERSION=$(cd "$SCRIPT_DIR" && npx tsx generate-spec-assets.ts --extract-version "$FLATMACHINE_SPEC")
PROFILES_VERSION=$(cd "$SCRIPT_DIR" && npx tsx generate-spec-assets.ts --extract-version "$PROFILES_SPEC")

if [[ -z "$FLATAGENT_VERSION" || -z "$FLATMACHINE_VERSION" || -z "$PROFILES_VERSION" ]]; then
    echo "Error: Could not extract spec versions"
    exit 1
fi

echo "Source of truth:"
echo "  flatagent.d.ts:   $FLATAGENT_VERSION"
echo "  flatmachine.d.ts: $FLATMACHINE_VERSION"
echo "  profiles.d.ts:    $PROFILES_VERSION"
echo ""

# Find all YAML/JSON files with spec_version
cd "$REPO_ROOT"

FLATAGENT_MISMATCHES=()
FLATMACHINE_MISMATCHES=()
PROFILES_MISMATCHES=()

while IFS= read -r file; do
    # Extract spec and spec_version from the file
    SPEC=$(rg '^spec:\s*(\w+)' "$file" -o -r '$1' --no-heading | head -1)
    VERSION=$(rg 'spec_version.*([0-9]+\.[0-9]+\.[0-9]+)' "$file" -o -r '$1' --no-heading | head -1)

    if [[ -z "$VERSION" ]]; then
        continue
    fi

    # Check against appropriate spec version
    if [[ "$SPEC" == "flatagent" || "$SPEC" == "flatagents" ]]; then
        if [[ "$VERSION" != "$FLATAGENT_VERSION" ]]; then
            FLATAGENT_MISMATCHES+=("$file: $VERSION (should be $FLATAGENT_VERSION)")
        fi
    elif [[ "$SPEC" == "flatmachine" ]]; then
        if [[ "$VERSION" != "$FLATMACHINE_VERSION" ]]; then
            FLATMACHINE_MISMATCHES+=("$file: $VERSION (should be $FLATMACHINE_VERSION)")
        fi
    elif [[ "$SPEC" == "flatprofiles" ]]; then
        if [[ "$VERSION" != "$PROFILES_VERSION" ]]; then
            PROFILES_MISMATCHES+=("$file: $VERSION (should be $PROFILES_VERSION)")
        fi
    fi
done < <(rg 'spec_version' --type yaml --type json -l)

# Check inline examples in core markdown docs (README.md, AGENTS.md)
MARKDOWN_MISMATCHES=()

for mdfile in README.md AGENTS.md; do
    if [[ -f "$REPO_ROOT/$mdfile" ]]; then
        # Find all spec_version lines with actual versions (not X.X.X placeholders)
        while IFS= read -r line; do
            VERSION=$(echo "$line" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
            if [[ -n "$VERSION" && "$VERSION" != "$FLATAGENT_VERSION" ]]; then
                MARKDOWN_MISMATCHES+=("$mdfile: $VERSION (should be $FLATAGENT_VERSION)")
            fi
        done < <(rg 'spec_version.*"[0-9]+\.[0-9]+\.[0-9]+"' "$REPO_ROOT/$mdfile" --no-heading)
    fi
done

# Report results
TOTAL_MISMATCHES=$((${#FLATAGENT_MISMATCHES[@]} + ${#FLATMACHINE_MISMATCHES[@]} + ${#PROFILES_MISMATCHES[@]} + ${#MARKDOWN_MISMATCHES[@]}))

if [[ $TOTAL_MISMATCHES -gt 0 ]]; then
    echo "❌ Found $TOTAL_MISMATCHES file(s) with mismatched spec_version:"
    echo ""
    
    if [[ ${#FLATAGENT_MISMATCHES[@]} -gt 0 ]]; then
        echo "FlatAgent mismatches:"
        for mismatch in "${FLATAGENT_MISMATCHES[@]}"; do
            echo "  - $mismatch"
        done
        echo ""
    fi
    
    if [[ ${#FLATMACHINE_MISMATCHES[@]} -gt 0 ]]; then
        echo "FlatMachine mismatches:"
        for mismatch in "${FLATMACHINE_MISMATCHES[@]}"; do
            echo "  - $mismatch"
        done
        echo ""
    fi
    
    if [[ ${#PROFILES_MISMATCHES[@]} -gt 0 ]]; then
        echo "Profiles mismatches:"
        for mismatch in "${PROFILES_MISMATCHES[@]}"; do
            echo "  - $mismatch"
        done
        echo ""
    fi

    if [[ ${#MARKDOWN_MISMATCHES[@]} -gt 0 ]]; then
        echo "Markdown inline example mismatches:"
        for mismatch in "${MARKDOWN_MISMATCHES[@]}"; do
            echo "  - $mismatch"
        done
        echo ""
    fi

    SPEC_VERSION_FAILED=true
else
    echo "✓ All spec_version references match:"
    echo "  - flatagent configs use v$FLATAGENT_VERSION"
    echo "  - flatmachine configs use v$FLATMACHINE_VERSION"
    echo "  - profiles configs use v$PROFILES_VERSION"
    echo "  - README.md/AGENTS.md inline examples match"
    SPEC_VERSION_FAILED=false
fi

# =============================================================================
# BROAD SEMVER SCAN - Find any semver that doesn't match lockstep version
# =============================================================================
echo ""
echo "Running broad semver scan for non-lockstep versions..."

LOCKSTEP_VERSION="$FLATAGENT_VERSION"
STRAY_VERSIONS=()

# Use rg with negative lookahead workaround:
# Find semver NOT matching lockstep, excluding known noise patterns
#
# Exclusions built into the search:
# - node_modules, .git, __pycache__, .venv, local/, assets/
# - lock files
# - Historical version refs (vX.X.X)
# - npm dep versions (^X.X.X, ~X.X.X, >=X.X.X)
# - package.json "version" fields
# - pyproject.toml version fields in examples

# First find all semver matches, then filter
while IFS=: read -r file lineno content; do
    [[ -z "$file" ]] && continue

    # Extract semver from content
    VERSION=$(echo "$content" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    [[ -z "$VERSION" ]] && continue

    # Skip if matches lockstep
    [[ "$VERSION" == "$LOCKSTEP_VERSION" ]] && continue

    # Skip vX.X.X historical references (features added in vX.X.X)
    echo "$content" | grep -qE "v$VERSION" && continue

    # Skip npm/pip dependency patterns: ^X.X.X, ~X.X.X, >=X.X.X, etc
    echo "$content" | grep -qE '[\"\'"'"'][\^~><!=]+[0-9]+\.[0-9]+\.[0-9]+' && continue

    # Skip package.json "version" field
    [[ "$file" == *"package.json" ]] && echo "$content" | grep -qE '"version"' && continue

    # Skip pyproject.toml version in examples
    [[ "$file" == *"examples"*"pyproject.toml" ]] && echo "$content" | grep -qE '^version' && continue

    # Skip runtime spec (separate versioning)
    [[ "$file" == *"runtime"* ]] && echo "$content" | grep -qE 'VERSION' && continue

    # Skip sdk/examples README version examples
    [[ "$file" == *"sdk/examples/README.md" ]] && continue

    STRAY_VERSIONS+=("$file:$lineno: $VERSION (lockstep is $LOCKSTEP_VERSION)")
done < <(rg -n '[0-9]+\.[0-9]+\.[0-9]+' \
    --glob '*.yml' --glob '*.yaml' --glob '*.md' --glob '*.ts' --glob '*.py' --glob '*.toml' \
    --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/__pycache__/**' --glob '!**/.venv/**' \
    --glob '!*-lock.json' --glob '!*.lock' --glob '!local/**' --glob '!assets/**' \
    2>/dev/null || true)

if [[ ${#STRAY_VERSIONS[@]} -gt 0 ]]; then
    echo ""
    echo "⚠️  Found ${#STRAY_VERSIONS[@]} stray semver(s) not matching lockstep version ($LOCKSTEP_VERSION):"
    for stray in "${STRAY_VERSIONS[@]}"; do
        echo "  - $stray"
    done
    echo ""
    echo "Review these - they may be:"
    echo "  - Old versions that need updating"
    echo "  - Legitimate (historical docs, test fixtures, etc.)"
else
    echo "✓ No stray semver versions found"
fi

# =============================================================================
# FINAL EXIT
# =============================================================================
if [[ "$SPEC_VERSION_FAILED" == true ]]; then
    echo ""
    exit 1
else
    echo ""
    echo "All checks passed!"
    exit 0
fi

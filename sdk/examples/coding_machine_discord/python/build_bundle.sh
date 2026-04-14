#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST_ROOT="$EXAMPLE_DIR/dist/python"

RELEASE_MODE=false
VERSION_OVERRIDE=""
MANIFEST_BASE_URL=""
GITHUB_OWNER="memgrafter"
GITHUB_REPO="flatmachines"
RELEASE_TAG_PREFIX="${MK42_RELEASE_TAG_PREFIX:-mk42_}"

usage() {
  cat <<'EOF'
Build mk42 install bundle.

Usage:
  build_bundle.sh [options]

Options:
  --release                 Build release artifact (default: dev artifact)
  --version <value>         Override computed artifact version
  --dist-root <path>        Dist root (default: dist/python)
  --manifest-base-url <url> Prefix bundle URL in manifest.json
  --github-owner <name>     GitHub owner for NOTES one-liners (default: memgrafter)
  --github-repo <name>      GitHub repo for NOTES one-liners (default: flatmachines)
  --help                    Show help

Env:
  MK42_RELEASE_TAG_PREFIX   Prefix for GitHub release tag in NOTES one-liners (default: mk42_)

Examples:
  ./build_bundle.sh
  ./build_bundle.sh --release
  ./build_bundle.sh --release --version v0.1.0 --manifest-base-url https://host.example/mk42/v0.1.0
EOF
}

log() {
  printf '[build] %s\n' "$*"
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    fail "sha256 tool not found (need sha256sum or shasum)"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release)
      RELEASE_MODE=true
      shift
      ;;
    --version)
      [[ $# -ge 2 ]] || fail "--version requires a value"
      VERSION_OVERRIDE="$2"
      shift 2
      ;;
    --dist-root)
      [[ $# -ge 2 ]] || fail "--dist-root requires a value"
      DIST_ROOT="$2"
      shift 2
      ;;
    --manifest-base-url)
      [[ $# -ge 2 ]] || fail "--manifest-base-url requires a value"
      MANIFEST_BASE_URL="$2"
      shift 2
      ;;
    --github-owner)
      [[ $# -ge 2 ]] || fail "--github-owner requires a value"
      GITHUB_OWNER="$2"
      shift 2
      ;;
    --github-repo)
      [[ $# -ge 2 ]] || fail "--github-repo requires a value"
      GITHUB_REPO="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

need_cmd uv
need_cmd uvx
need_cmd python3
need_cmd tar

[[ -d "$EXAMPLE_DIR/config" ]] || fail "config directory not found: $EXAMPLE_DIR/config"
[[ -f "$EXAMPLE_DIR/AGENTS.md" ]] || fail "workspace AGENTS.md missing: $EXAMPLE_DIR/AGENTS.md"
[[ -f "$SCRIPT_DIR/install.sh" ]] || fail "installer not found: $SCRIPT_DIR/install.sh"
[[ -f "$SCRIPT_DIR/bundle/bin/mk42" ]] || fail "launcher template missing: $SCRIPT_DIR/bundle/bin/mk42"
[[ -f "$SCRIPT_DIR/bundle/SETUP.md" ]] || fail "setup doc missing: $SCRIPT_DIR/bundle/SETUP.md"

BASE_VERSION="$(python3 - <<'PY' "$SCRIPT_DIR/pyproject.toml"
import pathlib
import sys

pyproject = pathlib.Path(sys.argv[1])
text = pyproject.read_text(encoding='utf-8')
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith('version = '):
        value = stripped.split('=', 1)[1].strip().strip('"').strip("'")
        print(value)
        raise SystemExit(0)
raise SystemExit('version not found in pyproject.toml')
PY
)"

GIT_SHA="nogit"
if command -v git >/dev/null 2>&1; then
  if git -C "$EXAMPLE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    GIT_SHA="$(git -C "$EXAMPLE_DIR" rev-parse --short=12 HEAD)"
  fi
fi

UTC_TS="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ -n "$VERSION_OVERRIDE" ]]; then
  ARTIFACT_VERSION="$VERSION_OVERRIDE"
elif [[ "$RELEASE_MODE" == true ]]; then
  ARTIFACT_VERSION="v$BASE_VERSION"
else
  ARTIFACT_VERSION="dev-$BASE_VERSION-$UTC_TS-$GIT_SHA"
fi

RELEASE_TAG="${RELEASE_TAG_PREFIX}${ARTIFACT_VERSION}"

DIST_ROOT="$(python3 - <<'PY' "$DIST_ROOT"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"

OUT_DIR="$DIST_ROOT/$ARTIFACT_VERSION"
BUNDLE_NAME="mk42-bundle-$ARTIFACT_VERSION"
BUNDLE_TAR="$OUT_DIR/$BUNDLE_NAME.tar.gz"

log "artifact version: $ARTIFACT_VERSION"
log "output directory: $OUT_DIR"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

BUNDLE_ROOT="$TMP_DIR/$BUNDLE_NAME"
mkdir -p "$BUNDLE_ROOT"

log "staging workspace from $EXAMPLE_DIR"
(
  cd "$EXAMPLE_DIR"
  tar \
    --exclude='.git' \
    --exclude='python/.venv' \
    --exclude='python/.pytest_cache' \
    --exclude='dist' \
    --exclude='python/dist' \
    --exclude='python/*.swp' \
    --exclude='python/.install.sh.swp' \
    --exclude='python/src/tool_use_discord/__pycache__' \
    --exclude='python/tests/**/__pycache__' \
    --exclude='data/*.sqlite' \
    --exclude='data/*.sqlite-*' \
    --exclude='data/*.log' \
    -cf - .
) | (cd "$BUNDLE_ROOT" && tar -xf -)

mkdir -p "$BUNDLE_ROOT/bin" "$BUNDLE_ROOT/wheels"

log "building wheel"
uv build --wheel --out-dir "$TMP_DIR/wheels" "$SCRIPT_DIR"

WHEEL_FILE="$(find "$TMP_DIR/wheels" -maxdepth 1 -type f -name 'tool_use_discord-*.whl' | sort | tail -n1)"
[[ -n "$WHEEL_FILE" ]] || fail "wheel build failed"
cp "$WHEEL_FILE" "$BUNDLE_ROOT/wheels/"

log "overlaying bundle runtime files"
cp "$SCRIPT_DIR/bundle/bin/mk42" "$BUNDLE_ROOT/bin/mk42"
chmod +x "$BUNDLE_ROOT/bin/mk42"
cp "$SCRIPT_DIR/bundle/SETUP.md" "$BUNDLE_ROOT/SETUP.md"

RUNTIME_REQ_FILE="$TMP_DIR/runtime-requirements.txt"
cat > "$RUNTIME_REQ_FILE" <<EOF
flatmachines[flatagents]==2.6.0
flatagents[litellm]==2.6.0
requests==2.33.1
EOF

cp "$RUNTIME_REQ_FILE" "$BUNDLE_ROOT/runtime-requirements.txt"
cp "$RUNTIME_REQ_FILE" "$BUNDLE_ROOT/constraints.txt"

log "vendoring dependency wheels"
uvx pip download \
  --dest "$BUNDLE_ROOT/wheels" \
  --requirement "$RUNTIME_REQ_FILE" \
  --only-binary=:all:

cat > "$BUNDLE_ROOT/VERSION" <<EOF
$ARTIFACT_VERSION
EOF

cat > "$BUNDLE_ROOT/BUILD_INFO.json" <<EOF
{
  "artifact_version": "$ARTIFACT_VERSION",
  "base_version": "$BASE_VERSION",
  "git_sha": "$GIT_SHA",
  "built_at_utc": "$UTC_TS"
}
EOF

mkdir -p "$OUT_DIR"
cp "$SCRIPT_DIR/install.sh" "$OUT_DIR/install.sh"
chmod +x "$OUT_DIR/install.sh"

tar -czf "$BUNDLE_TAR" -C "$TMP_DIR" "$BUNDLE_NAME"
BUNDLE_SHA="$(sha256_file "$BUNDLE_TAR")"

cat > "$OUT_DIR/checksums.txt" <<EOF
$BUNDLE_SHA  $(basename "$BUNDLE_TAR")
EOF

if [[ -n "$MANIFEST_BASE_URL" ]]; then
  base="${MANIFEST_BASE_URL%/}"
  bundle_ref="$base/$(basename "$BUNDLE_TAR")"
else
  bundle_ref="$(basename "$BUNDLE_TAR")"
fi

cat > "$OUT_DIR/manifest.json" <<EOF
{
  "name": "mk42",
  "latest": "$ARTIFACT_VERSION",
  "artifacts": {
    "$ARTIFACT_VERSION": {
      "bundle": "$bundle_ref",
      "sha256": "$BUNDLE_SHA"
    }
  }
}
EOF

cat > "$OUT_DIR/NOTES.md" <<EOF
# mk42 $ARTIFACT_VERSION

GitHub release tag expected by these one-liners: \`$RELEASE_TAG\`

## One-liner install (GitHub Release)

Pinned release:

\`\`\`bash
curl -fsSL https://github.com/$GITHUB_OWNER/$GITHUB_REPO/releases/download/$RELEASE_TAG/install.sh | bash -s -- \\
  --manifest-url https://github.com/$GITHUB_OWNER/$GITHUB_REPO/releases/download/$RELEASE_TAG/manifest.json \\
  --yes
\`\`\`

Latest release:

\`\`\`bash
curl -fsSL https://github.com/$GITHUB_OWNER/$GITHUB_REPO/releases/latest/download/install.sh | bash -s -- \\
  --manifest-url https://github.com/$GITHUB_OWNER/$GITHUB_REPO/releases/latest/download/manifest.json \\
  --yes
\`\`\`

## Local install from this folder

\`\`\`bash
./install.sh --bundle ./$(basename "$BUNDLE_TAR") --sha256 $BUNDLE_SHA
\`\`\`

## Artifacts

- \`install.sh\`
- \`manifest.json\`
- \`checksums.txt\`
- \`$(basename "$BUNDLE_TAR")\`

## Notes

- Installer uses vendored wheels from bundle (offline install: no PyPI).
- Runtime config/secrets default outside workspace:
  - env: \`~/.agents/flatmachines/mk42.env\`
  - codex auth: \`~/.agents/flatmachines/auth.json\`
- If Codex auth is missing after non-interactive install, run:

\`\`\`bash
mk42 login codex
\`\`\`
EOF

cat <<EOF

Build complete
  Version:      $ARTIFACT_VERSION
  Release tag:  $RELEASE_TAG
  Folder:       $OUT_DIR
  Bundle:       $BUNDLE_TAR
  SHA256:       $BUNDLE_SHA

Install locally:
  $OUT_DIR/install.sh --bundle $BUNDLE_TAR --sha256 $BUNDLE_SHA

Release notes file:
  $OUT_DIR/NOTES.md

EOF

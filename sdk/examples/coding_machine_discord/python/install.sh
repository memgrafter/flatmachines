#!/usr/bin/env bash
set -euo pipefail

APP_NAME="mk42"
DEFAULT_INSTALL_DIR="$HOME/.agents/mk42"
DEFAULT_ENV_FILE="$HOME/.agents/flatmachines/mk42.env"
DEFAULT_AUTH_FILE="$HOME/.agents/flatmachines/auth.json"

INSTALL_DIR="$DEFAULT_INSTALL_DIR"
BUNDLE_SOURCE=""
BUNDLE_SHA256=""
MANIFEST_URL="${MK42_MANIFEST_URL:-}"
REQUESTED_VERSION=""
ASSUME_YES=false
FORCE=false
LINK_BIN=true
SKIP_AUTH_SETUP=false
ENV_FILE="$DEFAULT_ENV_FILE"
AUTH_FILE="$DEFAULT_AUTH_FILE"
CODEX_AUTH_READY=false

usage() {
  cat <<'EOF'
mk42 installer

Usage:
  install.sh [options]

Options:
  --dir <path>           Install root (default: ~/.agents/mk42)
  --bundle <path|url>    Bundle tarball to install (mk42-bundle-*.tar.gz)
  --sha256 <hex>         Expected sha256 for --bundle
  --manifest-url <url>   Manifest URL used when --bundle is omitted
  --version <id>         Version key to install from manifest (default: latest)
  --env-file <path>      Runtime env file path (default: ~/.agents/flatmachines/mk42.env)
  --auth-file <path>     Codex auth file path (default: ~/.agents/flatmachines/auth.json)
  --skip-auth-setup      Skip Codex auth onboarding
  --yes                  Non-interactive mode
  --force                Replace existing release directory if present
  --no-link-bin          Do not create ~/.local/bin/mk42 symlink
  --help                 Show help

Examples:
  ./install.sh --bundle ./dist/dev-.../mk42-bundle-dev-....tar.gz
  ./install.sh --manifest-url https://host.example/mk42/manifest.json --version v0.1.0
EOF
}

log() {
  printf '[install] %s\n' "$*"
}

warn() {
  printf '[install] warning: %s\n' "$*" >&2
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

UV_PYTHON_REQUEST="${MK42_UV_PYTHON_VERSION:-3.13}"

uv_python() {
  uv run --managed-python --no-project --python "$UV_PYTHON_REQUEST" python "$@"
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

download_to() {
  local url="$1"
  local out="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$out"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$out" "$url"
  else
    fail "neither curl nor wget is available for download"
  fi
}

resolve_script_dir() {
  local src="${BASH_SOURCE[0]}"
  while [[ -h "$src" ]]; do
    local dir
    dir="$(cd -P "$(dirname "$src")" >/dev/null 2>&1 && pwd)"
    src="$(readlink "$src")"
    [[ "$src" != /* ]] && src="$dir/$src"
  done
  cd -P "$(dirname "$src")" >/dev/null 2>&1 && pwd
}

resolve_path() {
  uv_python - <<'PY' "$1"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

to_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

select_bundle_from_manifest() {
  local manifest_file="$1"
  uv_python - "$manifest_file" "$REQUESTED_VERSION" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
requested_version = sys.argv[2].strip()

manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
artifacts = manifest.get('artifacts') or {}
if not isinstance(artifacts, dict) or not artifacts:
    raise SystemExit('manifest has no artifacts')

version = requested_version or str(manifest.get('latest') or '').strip()
if not version:
    version = sorted(artifacts.keys())[-1]

if version not in artifacts:
    raise SystemExit(f'version not found in manifest: {version}')

entry = artifacts[version]
if not isinstance(entry, dict):
    raise SystemExit(f'invalid manifest entry for {version}')

bundle = str(entry.get('bundle') or entry.get('bundle_url') or '').strip()
if not bundle:
    raise SystemExit(f'manifest entry missing bundle for {version}')
sha256 = str(entry.get('sha256') or '').strip()
print(version)
print(bundle)
print(sha256)
PY
}

set_kv_file_value() {
  local file="$1"
  local key="$2"
  local value="$3"

  uv_python - <<'PY' "$file" "$key" "$value"
from pathlib import Path
import re
import sys

path = Path(sys.argv[1]).expanduser().resolve()
key = sys.argv[2]
value = sys.argv[3]

path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    lines = path.read_text(encoding='utf-8').splitlines()
else:
    lines = []

pattern = re.compile(rf'^{re.escape(key)}\s*=')
replaced = False
out = []
for line in lines:
    if pattern.match(line.strip()):
        out.append(f"{key}={value}")
        replaced = True
    else:
        out.append(line)

if not replaced:
    if out and out[-1].strip() != "":
        out.append("")
    out.append(f"{key}={value}")

path.write_text("\n".join(out).rstrip() + "\n", encoding='utf-8')
PY
}

ensure_path_block_in_file() {
  local file="$1"
  local bin_dir="$2"
  local start="# >>> mk42 ~/.local/bin PATH >>>"
  local end="# <<< mk42 ~/.local/bin PATH <<<"

  mkdir -p "$(dirname "$file")"
  touch "$file"

  if grep -Fq "$start" "$file"; then
    return 0
  fi

  if [[ -s "$file" ]]; then
    printf '\n' >> "$file"
  fi

  cat >> "$file" <<EOF
$start
if [ -d "$bin_dir" ] && ! printf ':%s:' "\$PATH" | grep -Fq ":$bin_dir:"; then
  export PATH="$bin_dir:\$PATH"
fi
$end
EOF
}

has_tty() {
  if (exec 9<>/dev/tty) 2>/dev/null; then
    exec 9>&- 9<&-
    return 0
  fi

  return 1
}

prompt_yes_no() {
  local prompt="$1"
  local default_yes="$2"

  if [[ "$ASSUME_YES" == true ]]; then
    return 0
  fi

  local suffix="[y/N]"
  if [[ "$default_yes" == "yes" ]]; then
    suffix="[Y/n]"
  fi

  read -r -p "$prompt $suffix " reply
  reply="$(to_lower "$reply")"

  if [[ -z "$reply" ]]; then
    [[ "$default_yes" == "yes" ]] && return 0 || return 1
  fi

  [[ "$reply" == "y" || "$reply" == "yes" ]]
}

setup_codex_auth() {
  local auth_file="$1"
  CODEX_AUTH_READY=false

  if [[ "$SKIP_AUTH_SETUP" == true ]]; then
    if [[ -s "$auth_file" ]]; then
      CODEX_AUTH_READY=true
    fi
    warn "skipping Codex auth setup (--skip-auth-setup)"
    return 0
  fi

  mkdir -p "$(dirname "$auth_file")"

  if [[ -s "$auth_file" ]]; then
    log "Codex auth already present: $auth_file"
    chmod 600 "$auth_file" || true
    CODEX_AUTH_READY=true
    return 0
  fi

  warn "Codex auth missing: $auth_file"
  warn "Run 'mk42 login codex' after install to complete OAuth setup."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || fail "--dir requires a value"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --bundle)
      [[ $# -ge 2 ]] || fail "--bundle requires a value"
      BUNDLE_SOURCE="$2"
      shift 2
      ;;
    --sha256)
      [[ $# -ge 2 ]] || fail "--sha256 requires a value"
      BUNDLE_SHA256="$2"
      shift 2
      ;;
    --manifest-url)
      [[ $# -ge 2 ]] || fail "--manifest-url requires a value"
      MANIFEST_URL="$2"
      shift 2
      ;;
    --version)
      [[ $# -ge 2 ]] || fail "--version requires a value"
      REQUESTED_VERSION="$2"
      shift 2
      ;;
    --env-file)
      [[ $# -ge 2 ]] || fail "--env-file requires a value"
      ENV_FILE="$2"
      shift 2
      ;;
    --auth-file)
      [[ $# -ge 2 ]] || fail "--auth-file requires a value"
      AUTH_FILE="$2"
      shift 2
      ;;
    --skip-auth-setup)
      SKIP_AUTH_SETUP=true
      shift
      ;;
    --yes)
      ASSUME_YES=true
      shift
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --no-link-bin)
      LINK_BIN=false
      shift
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

need_cmd bash
need_cmd tar
need_cmd uv

INSTALL_DIR="$(resolve_path "$INSTALL_DIR")"
ENV_FILE="$(resolve_path "$ENV_FILE")"
AUTH_FILE="$(resolve_path "$AUTH_FILE")"

if [[ "$ASSUME_YES" != true ]]; then
  log "install directory: $INSTALL_DIR"
  log "env file: $ENV_FILE"
  log "auth file: $AUTH_FILE"

  if [[ ! -t 0 ]]; then
    warn "no interactive stdin; continuing in non-interactive mode"
    warn "Tip: pass --yes to suppress this warning in curl|bash installs"
    ASSUME_YES=true
  else
    read -r -p "Continue? [y/N] " reply
    reply="$(to_lower "$reply")"
    if [[ "$reply" != "y" && "$reply" != "yes" ]]; then
      fail "aborted by user"
    fi
  fi
fi

SCRIPT_DIR="$(resolve_script_dir)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

BUNDLE_FILE=""
EXPECTED_SHA="$(to_lower "$BUNDLE_SHA256")"

if [[ -n "$BUNDLE_SOURCE" ]]; then
  if [[ "$BUNDLE_SOURCE" =~ ^https?:// ]]; then
    BUNDLE_FILE="$TMP_DIR/$(basename "$BUNDLE_SOURCE")"
    log "downloading bundle: $BUNDLE_SOURCE"
    download_to "$BUNDLE_SOURCE" "$BUNDLE_FILE"
  else
    BUNDLE_FILE="$(resolve_path "$BUNDLE_SOURCE")"
  fi
else
  shopt -s nullglob
  local_bundles=("$SCRIPT_DIR"/mk42-bundle-*.tar.gz)
  shopt -u nullglob
  if [[ ${#local_bundles[@]} -gt 0 ]]; then
    last_index=$((${#local_bundles[@]} - 1))
    BUNDLE_FILE="${local_bundles[$last_index]}"
  else
    [[ -n "$MANIFEST_URL" ]] || fail "no bundle found next to installer; provide --bundle or --manifest-url"
    MANIFEST_FILE="$TMP_DIR/manifest.json"
    log "downloading manifest: $MANIFEST_URL"
    download_to "$MANIFEST_URL" "$MANIFEST_FILE"

    selected_output="$(select_bundle_from_manifest "$MANIFEST_FILE")"
    MANIFEST_VERSION="$(printf '%s\n' "$selected_output" | sed -n '1p')"
    MANIFEST_BUNDLE="$(printf '%s\n' "$selected_output" | sed -n '2p')"
    MANIFEST_SHA="$(to_lower "$(printf '%s\n' "$selected_output" | sed -n '3p')")"

    [[ -n "$MANIFEST_VERSION" && -n "$MANIFEST_BUNDLE" ]] || fail "invalid manifest selection"

    if [[ -z "$EXPECTED_SHA" && -n "$MANIFEST_SHA" ]]; then
      EXPECTED_SHA="$MANIFEST_SHA"
    fi

    if [[ "$MANIFEST_BUNDLE" =~ ^https?:// ]]; then
      BUNDLE_URL="$MANIFEST_BUNDLE"
    else
      BASE_URL="${MANIFEST_URL%/*}"
      BUNDLE_URL="$BASE_URL/$MANIFEST_BUNDLE"
    fi

    BUNDLE_FILE="$TMP_DIR/$(basename "$BUNDLE_URL")"
    log "downloading bundle for version $MANIFEST_VERSION: $BUNDLE_URL"
    download_to "$BUNDLE_URL" "$BUNDLE_FILE"
  fi
fi

[[ -f "$BUNDLE_FILE" ]] || fail "bundle not found: $BUNDLE_FILE"

if [[ -z "$EXPECTED_SHA" ]]; then
  CHECKSUM_FILE="$(dirname "$BUNDLE_FILE")/checksums.txt"
  if [[ -f "$CHECKSUM_FILE" ]]; then
    EXPECTED_SHA="$(grep " $(basename "$BUNDLE_FILE")$" "$CHECKSUM_FILE" | awk '{print $1}' | tr '[:upper:]' '[:lower:]' || true)"
  fi
fi

ACTUAL_SHA="$(sha256_file "$BUNDLE_FILE" | tr '[:upper:]' '[:lower:]')"
if [[ -n "$EXPECTED_SHA" ]]; then
  [[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || fail "sha256 mismatch for $(basename "$BUNDLE_FILE")"
  log "sha256 verified"
else
  warn "no expected sha256 provided; continuing without integrity check"
fi

bundle_name="$(basename "$BUNDLE_FILE")"
if [[ "$bundle_name" =~ ^mk42-bundle-(.+)\.tar\.gz$ ]]; then
  artifact_version="${BASH_REMATCH[1]}"
else
  fail "invalid bundle filename (expected mk42-bundle-<version>.tar.gz): $bundle_name"
fi

mkdir -p "$INSTALL_DIR/releases" "$INSTALL_DIR/logs"

EXTRACT_DIR="$TMP_DIR/extract"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$BUNDLE_FILE" -C "$EXTRACT_DIR"

BUNDLE_ROOT="$EXTRACT_DIR/mk42-bundle-$artifact_version"
if [[ ! -d "$BUNDLE_ROOT" ]]; then
  first_dir="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n1 || true)"
  [[ -n "$first_dir" ]] || fail "bundle did not contain a directory"
  BUNDLE_ROOT="$first_dir"
fi

RELEASE_DIR="$INSTALL_DIR/releases/$artifact_version"
if [[ -e "$RELEASE_DIR" ]]; then
  if [[ "$FORCE" == true ]]; then
    rm -rf "$RELEASE_DIR"
  else
    log "release already exists: $RELEASE_DIR"
    log "use --force to replace"
  fi
fi

if [[ ! -e "$RELEASE_DIR" ]]; then
  mv "$BUNDLE_ROOT" "$RELEASE_DIR"
fi

WORKSPACE_DIR="$INSTALL_DIR/workspaces/live"
if [[ "$FORCE" == true && -e "$WORKSPACE_DIR" ]]; then
  rm -rf "$WORKSPACE_DIR"
fi

if [[ ! -e "$WORKSPACE_DIR" ]]; then
  mkdir -p "$INSTALL_DIR/workspaces"
  cp -a "$RELEASE_DIR" "$WORKSPACE_DIR"
  cat > "$WORKSPACE_DIR/.mk42-base-release" <<EOF
$artifact_version
EOF
fi

ln -sfn "$WORKSPACE_DIR" "$INSTALL_DIR/current"

VENV_DIR="$INSTALL_DIR/.venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  log "creating virtualenv"
  uv venv --managed-python --python "$UV_PYTHON_REQUEST" "$VENV_DIR"
fi

WHEELS_DIR="$INSTALL_DIR/current/wheels"
WHEEL_FILE="$(find "$WHEELS_DIR" -maxdepth 1 -type f -name 'tool_use_discord-*.whl' | sort | tail -n1)"
[[ -n "$WHEEL_FILE" ]] || fail "tool_use_discord wheel missing in $WHEELS_DIR"

log "installing runtime dependencies from vendored wheelhouse (offline)"
uv pip install \
  --python "$VENV_DIR/bin/python" \
  --upgrade \
  --offline \
  --no-index \
  --find-links "$WHEELS_DIR" \
  "$WHEEL_FILE"

chmod +x "$WORKSPACE_DIR/bin/mk42"

# Persist runtime config that mk42 launcher consumes.
CONF_FILE="$INSTALL_DIR/conf"
set_kv_file_value "$CONF_FILE" "MK42_ENV_FILE" "$ENV_FILE"
set_kv_file_value "$CONF_FILE" "MK42_CODEX_AUTH_FILE" "$AUTH_FILE"
set_kv_file_value "$CONF_FILE" "MK42_CHAT_ROLLOVER_TOKEN_LIMIT" "50000"
chmod 600 "$CONF_FILE" || true

# Ensure env file exists with Discord placeholders.
if [[ ! -f "$ENV_FILE" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  cat > "$ENV_FILE" <<'EOF'
# mk42 runtime environment
DISCORD_BOT_TOKEN=
DISCORD_CHANNEL_ID=
CODING_MACHINE_DISCORD_DEBUG=true
EOF
  chmod 600 "$ENV_FILE" || true
  log "created env file template: $ENV_FILE"
fi

if [[ "$ASSUME_YES" != true ]]; then
  if prompt_yes_no "Set DISCORD_BOT_TOKEN now?" no; then
    read -r -p "DISCORD_BOT_TOKEN: " discord_bot_token
    set_kv_file_value "$ENV_FILE" "DISCORD_BOT_TOKEN" "$discord_bot_token"
  fi
  if prompt_yes_no "Set DISCORD_CHANNEL_ID now?" no; then
    read -r -p "DISCORD_CHANNEL_ID: " discord_channel_id
    set_kv_file_value "$ENV_FILE" "DISCORD_CHANNEL_ID" "$discord_channel_id"
  fi
fi

setup_codex_auth "$AUTH_FILE"

if [[ "$CODEX_AUTH_READY" != true ]]; then
  warn "Codex auth is not configured yet."

  if has_tty; then
    log "Starting Codex OAuth now (mk42 login codex)..."
    if "$INSTALL_DIR/current/bin/mk42" login codex </dev/tty >/dev/tty 2>&1; then
      if [[ -s "$AUTH_FILE" ]]; then
        CODEX_AUTH_READY=true
        log "Codex auth configured: $AUTH_FILE"
      else
        warn "Codex login completed but auth file is still missing: $AUTH_FILE"
      fi
    else
      warn "Codex login failed or was cancelled. Run: mk42 login codex"
    fi
  else
    warn "No TTY available to run Codex OAuth now; run later: mk42 login codex"
  fi
fi

PATH_UPDATE_NOTE=""
if [[ "$LINK_BIN" == true ]]; then
  BIN_DIR="$HOME/.local/bin"
  mkdir -p "$BIN_DIR"
  ln -sfn "$INSTALL_DIR/current/bin/mk42" "$BIN_DIR/mk42"
  ensure_path_block_in_file "$HOME/.profile" "$BIN_DIR"
  ensure_path_block_in_file "$HOME/.bashrc" "$BIN_DIR"
  log "linked launcher: $BIN_DIR/mk42"
  log "ensured $BIN_DIR is added to PATH in ~/.profile and ~/.bashrc"
  PATH_UPDATE_NOTE="Open a new shell (or run: . ~/.profile) before using 'mk42' by name if it is not yet on PATH in this session."
fi

cat <<EOF

Installed $APP_NAME
  Home:         $INSTALL_DIR
  Release:      $RELEASE_DIR
  Bundle sha:   $ACTUAL_SHA
  Workspace:    $WORKSPACE_DIR
  Config file:  $CONF_FILE
  Env file:     $ENV_FILE
  Codex auth:   $AUTH_FILE
  Auth ready:   $CODEX_AUTH_READY

Run:
  mk42 setup         # required once: codex login + discord setup + at least 1 Discord user ID (for admin)
  mk42 all
  mk42 cli -p "summarize this workspace"

Individual setup commands (optional):
  mk42 login codex
  mk42 setup discord

Setup doc:
  $INSTALL_DIR/current/SETUP.md

$PATH_UPDATE_NOTE
EOF

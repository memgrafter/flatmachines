#!/bin/bash
set -euo pipefail

# --- Configuration ---
VENV_PATH=".venv"
LOCAL_INSTALL=false
KEEP_ACTIVATION=false
AUTO_APPROVE=false
TIMEOUT_SECONDS=20
TASK_ID="demo-os-$$"

while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        --keep-activation)
            KEEP_ACTIVATION=true
            shift
            ;;
        --yes|-y)
            AUTO_APPROVE=true
            shift
            ;;
        --timeout)
            TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        --task-id)
            TASK_ID="$2"
            shift 2
            ;;
        *)
            echo "Unknown arg: $1" >&2
            exit 1
            ;;
    esac
done

echo "--- Listener OS Integration Demo Runner ---"

echo "(This script FAILS unless OS activation is working.)"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

find_project_root() {
    local dir="$1"
    while [[ "$dir" != "/" ]]; do
        if [[ -e "$dir/.git" ]]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo "Error: Could not find project root (no .git found)" >&2
    return 1
}

PROJECT_ROOT="$(find_project_root "$SCRIPT_DIR")"
FLATMACHINES_SDK_PATH="$PROJECT_ROOT/sdk/python/flatmachines"

echo "📁 Project root: $PROJECT_ROOT"
echo "📁 FlatMachines SDK: $FLATMACHINES_SDK_PATH"

cd "$SCRIPT_DIR"

if ! command -v uv &> /dev/null; then
    echo "📥 Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "🔧 Ensuring virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    uv venv "$VENV_PATH"
else
    echo "✅ Virtual environment already exists."
fi

echo "📦 Installing dependencies..."
if [ "$LOCAL_INSTALL" = true ]; then
    echo "  - Installing flatmachines from local source..."
    uv pip install --python "$VENV_PATH/bin/python" -e "$FLATMACHINES_SDK_PATH"
else
    echo "  - Installing flatmachines from PyPI..."
    uv pip install --python "$VENV_PATH/bin/python" "flatmachines"
fi

echo "  - Installing listener_os demo package..."
uv pip install --python "$VENV_PATH/bin/python" -e "$SCRIPT_DIR"

PY="$VENV_PATH/bin/python"

cleanup() {
    if [ "$KEEP_ACTIVATION" = false ] && [ "${INSTALLED_ACTIVATION:-0}" = "1" ]; then
        echo "🧹 Uninstalling OS activation..."
        "$PY" -m listener_os.main uninstall-activation --os auto >/dev/null || true
    fi
}
trap cleanup EXIT

INSTALLED_ACTIVATION=0

echo "🧼 Resetting demo state..."
"$PY" -m listener_os.main reset >/dev/null

if [ "$AUTO_APPROVE" = false ]; then
    echo "⚠️  This demo will modify OS service/login items temporarily:"
    echo "   - macOS: launchd agent under ~/Library/LaunchAgents"
    echo "   - Linux: systemd --user units under ~/.config/systemd/user"
    read -r -p "Approve these OS changes for this run? [y/N] " REPLY
    case "${REPLY:-}" in
        y|Y|yes|YES)
            ;;
        *)
            echo "❌ Aborted by user before OS changes."
            exit 1
            ;;
    esac
fi

echo "🧩 Installing OS activation..."
"$PY" -m listener_os.main install-activation --os auto --python "$PY"
INSTALLED_ACTIVATION=1

echo "🅿️  Parking machine on wait_for (task_id=$TASK_ID)..."
"$PY" -m listener_os.main park --task-id "$TASK_ID" >/dev/null

echo "📨 Sending file-triggered signal (OS must wake dispatcher)..."
"$PY" -m listener_os.main send --task-id "$TASK_ID" --approved true --reviewer run-sh --trigger file >/dev/null

CHANNEL="approval/$TASK_ID"

echo "⏳ Waiting up to ${TIMEOUT_SECONDS}s for OS-activated resume..."
SUCCESS=0
for ((i=0; i< TIMEOUT_SECONDS*2; i++)); do
    STATUS_JSON="$($PY -m listener_os.main status)"

    if STATUS_JSON="$STATUS_JSON" python3 - "$CHANNEL" <<'PY'
import json, os, sys
channel = sys.argv[1]
obj = json.loads(os.environ["STATUS_JSON"])
pending = obj.get("pending_signals", {})
waiting = obj.get("waiting_machines", {})
# success when no pending signal on channel and no machine waiting on channel
ok = pending.get(channel, 0) == 0 and channel not in waiting
raise SystemExit(0 if ok else 1)
PY
    then
        SUCCESS=1
        break
    fi

    sleep 0.5
done

if [ "$SUCCESS" != "1" ]; then
    echo "❌ OS integration check failed. Machine still waiting or signal still pending." >&2
    echo "--- status ---" >&2
    "$PY" -m listener_os.main status >&2 || true
    echo "--- recent logs ---" >&2
    ls -1 ../data/*.log >/dev/null 2>&1 && tail -n 80 ../data/*.log >&2 || echo "(no activation logs found)" >&2
    exit 1
fi

echo "✅ Success: machine resumed via OS activation (no manual dispatch-once)."
"$PY" -m listener_os.main status

if [ "$KEEP_ACTIVATION" = true ]; then
    echo "ℹ️ Keeping OS activation installed (--keep-activation)."
fi

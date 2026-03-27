#!/bin/bash
set -e

LOCAL_INSTALL=false
TASK="Say hello and list files in current directory"
WORKING_DIR=""
MULTI_STATE=false
MACHINE_CONFIG=""
SHOW_HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --local|-l)
            LOCAL_INSTALL=true
            shift
            ;;
        --multi-state)
            MULTI_STATE=true
            shift
            ;;
        --with-refs)
            MACHINE_CONFIG="machine_with_refs.yml"
            shift
            ;;
        -p|--print)
            TASK="$2"
            shift 2
            ;;
        -w|--working-dir)
            WORKING_DIR="$2"
            shift 2
            ;;
        -h|--help)
            SHOW_HELP=true
            shift
            ;;
        *)
            echo "❌ Unknown flag: $1"
            exit 1
            ;;
    esac
done

echo "--- Claude Code Adapter Demo Runner (JS) ---"

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
JS_SDK_PATH="$PROJECT_ROOT/sdk/js"

cd "$SCRIPT_DIR"

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed."
    exit 1
fi
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed."
    exit 1
fi
if ! command -v claude &> /dev/null; then
    echo "❌ 'claude' CLI not found on PATH"
    exit 1
fi

if [ "$LOCAL_INSTALL" = true ]; then
    cd "$JS_SDK_PATH"
    npm run build
    cd "$SCRIPT_DIR"
    npm pkg set dependencies.@memgrafter/flatmachines="file:../../../js/packages/flatmachines"
else
    npm pkg set dependencies.@memgrafter/flatmachines="^2.5.0"
fi

npm install
npm run build

ARGS=()
if [ "$SHOW_HELP" = true ]; then
    ARGS+=("--help")
else
    ARGS+=("-p" "$TASK")
    if [ "$MULTI_STATE" = true ]; then
        ARGS+=("--multi-state")
    fi
    if [ -n "$MACHINE_CONFIG" ]; then
        ARGS+=("--config" "$MACHINE_CONFIG")
    fi
    if [ -n "$WORKING_DIR" ]; then
        ARGS+=("-w" "$WORKING_DIR")
    fi
fi

node dist/claude_code_example/main.js "${ARGS[@]}"

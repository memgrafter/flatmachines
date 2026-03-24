#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
JS_SDK_PATH="$PROJECT_ROOT/sdk/js"

cd "$SCRIPT_DIR"

echo "=== coding_machine_cli/js test suite ==="

if ! command -v node >/dev/null 2>&1; then
  echo "node is required but not found on PATH"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but not found on PATH"
  exit 1
fi

echo "Building local JS SDK packages..."
cd "$JS_SDK_PATH"
npm run build >/dev/null

cd "$SCRIPT_DIR"

echo "Installing example dependencies (local flatmachines)..."
npm pkg set dependencies.@memgrafter/flatmachines="file:../../../js/packages/flatmachines" >/dev/null
npm install >/dev/null

echo "Building example..."
npm run build >/dev/null

echo "Test 1: tool definition merge (agent YAML + provider override semantics)"
node --input-type=module <<'EOF'
import { FlatMachine } from '@memgrafter/flatmachines';
import { join } from 'path';

const configDir = join(process.cwd(), '..', 'config');
const machine = new FlatMachine({ config: join(configDir, 'machine.yml'), configDir });

const defsFromYaml = machine._resolve_tool_definitions('coder', { get_tool_definitions: () => [] });
const names = defsFromYaml.map(d => d?.function?.name).filter(Boolean);
const expected = ['read', 'bash', 'write', 'edit'];
for (const n of expected) {
  if (!names.includes(n)) {
    throw new Error(`missing tool definition from YAML: ${n}`);
  }
}

const overridden = machine._resolve_tool_definitions('coder', {
  get_tool_definitions: () => [
    {
      type: 'function',
      function: {
        name: 'read',
        description: 'provider override read',
        parameters: { type: 'object', properties: {}, required: [] },
      },
    },
  ],
});

const readDefs = overridden.filter(d => d?.function?.name === 'read');
if (readDefs.length !== 1) {
  throw new Error(`expected exactly one merged 'read' definition, got ${readDefs.length}`);
}
if (readDefs[0].function.description !== 'provider override read') {
  throw new Error('provider override for read did not win over YAML definition');
}

console.log('ok');
EOF

echo "Test 2: tool path handling expands ~ for read"
node --input-type=module <<'EOF'
import { toolRead } from './dist/tool_use_cli/tools.js';

const result = await toolRead(process.cwd(), 't1', { path: '~/.pi/agent/auth.json', limit: 1 });
if (result.is_error) {
  throw new Error(`toolRead(~/.pi/agent/auth.json) failed: ${result.content}`);
}
console.log('ok');
EOF

echo "Test 3: codex backend + tool loop smoke test (read-only)"
if [ ! -f "$HOME/.pi/agent/auth.json" ]; then
  echo "Missing Codex auth file: $HOME/.pi/agent/auth.json"
  exit 1
fi

SMOKE_OUTPUT="$(node dist/tool_use_cli/main.js --standalone "Read-only. You must call read on README.md and return only the first markdown heading exactly. Do not modify files." 2>&1)"

echo "$SMOKE_OUTPUT"

echo "$SMOKE_OUTPUT" | grep -q "✓ .*read: README.md"
echo "$SMOKE_OUTPUT" | grep -q "# Coding Machine CLI (JavaScript)"

echo "=== coding_machine_cli/js tests passed ==="

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

type ManifestFile = {
  file: string
  tests: string[]
}

type Manifest = {
  generated_at: string
  source_root: string
  total_tests: number
  files: ManifestFile[]
}

export const PARITY_TOPICAL_SUITES = Object.freeze({
  holdback: 'sdk/js/tests/holdback/python-sdk-parity.test.ts',
  parityAgents: 'sdk/js/tests/parity/agents.parity.test.ts',
  parityChat: 'sdk/js/tests/parity/chat.parity.test.ts',
  parityCodex: 'sdk/js/tests/parity/codex.parity.test.ts',
  parityClaudeCodeLive: 'sdk/js/tests/parity/claude-code-live.parity.test.ts',
  parityConfiguration: 'sdk/js/tests/parity/configuration.parity.test.ts',
  parityContext: 'sdk/js/tests/parity/context.parity.test.ts',
  parityCore: 'sdk/js/tests/parity/core.parity.test.ts',
  parityEvents: 'sdk/js/tests/parity/events.parity.test.ts',
  parityFlatagentBackends: 'sdk/js/tests/parity/flatagent-backends.parity.test.ts',
  parityHooks: 'sdk/js/tests/parity/hooks.parity.test.ts',
  parityMemory: 'sdk/js/tests/parity/memory.parity.test.ts',
  parityModels: 'sdk/js/tests/parity/models.parity.test.ts',
  parityOrchestration: 'sdk/js/tests/parity/orchestration.parity.test.ts',
  parityPrompts: 'sdk/js/tests/parity/prompts.parity.test.ts',
  parityRetries: 'sdk/js/tests/parity/retries.parity.test.ts',
  parityRunner: 'sdk/js/tests/parity/runner.parity.test.ts',
  parityStorage: 'sdk/js/tests/parity/storage.parity.test.ts',
  parityStreaming: 'sdk/js/tests/parity/streaming.parity.test.ts',
  parityTools: 'sdk/js/tests/parity/tools.parity.test.ts',
  parityTracing: 'sdk/js/tests/parity/tracing.parity.test.ts',
  parityUtils: 'sdk/js/tests/parity/utils.parity.test.ts',
})

export type ParityTopicalSuite = keyof typeof PARITY_TOPICAL_SUITES

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const manifestPath = resolve(__dirname, '../../holdback/python-sdk-tests-manifest.json')
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as Manifest

export const PARITY_MANIFEST_METADATA = Object.freeze({
  generatedAt: manifest.generated_at,
  sourceRoot: manifest.source_root,
  totalTests: manifest.total_tests,
})

export const PARITY_MANIFEST_CASE_KEYS = Object.freeze(
  manifest.files.flatMap((file) => file.tests.map((test) => `${file.file}::${test}`)),
)

// Topical suite assignments (cases promoted out of holdback)
const TOPICAL_ASSIGNMENTS = {
  parityAgents: Object.freeze([]) as readonly string[],
  parityChat: Object.freeze([]) as readonly string[],
  parityCodex: Object.freeze([]) as readonly string[],
  parityClaudeCodeLive: Object.freeze([
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_simple_task',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_tool_use_read_file',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_session_resume',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_concurrent_sessions',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_resume_nonexistent_session',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_permission_bypass_headless',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_tools_exact_restriction',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_continuation_loop',
    'sdk/python/tests/integration/claude_code/test_claude_code_live.py::test_stream_event_types',
  ] as const),
  parityConfiguration: Object.freeze([]) as readonly string[],
  parityContext: Object.freeze([]) as readonly string[],
  parityCore: Object.freeze([]) as readonly string[],
  parityEvents: Object.freeze([]) as readonly string[],
  parityFlatagentBackends: Object.freeze([
    'sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_flatagent_codex_backend_end_to_end',
    'sdk/python/tests/integration/distributed/test_distributed.py::test_distributed_backends_basic',
  ] as const),
  parityHooks: Object.freeze([]) as readonly string[],
  parityMemory: Object.freeze([]) as readonly string[],
  parityModels: Object.freeze([]) as readonly string[],
  parityOrchestration: Object.freeze([]) as readonly string[],
  parityPrompts: Object.freeze([]) as readonly string[],
  parityRetries: Object.freeze([]) as readonly string[],
  parityRunner: Object.freeze([]) as readonly string[],
  parityStorage: Object.freeze([]) as readonly string[],
  parityStreaming: Object.freeze([]) as readonly string[],
  parityTools: Object.freeze([]) as readonly string[],
  parityTracing: Object.freeze([]) as readonly string[],
  parityUtils: Object.freeze([]) as readonly string[],
} as const

// Holdback = all manifest cases minus those claimed by topical suites
const promotedCases = new Set(Object.values(TOPICAL_ASSIGNMENTS).flat())
const holdbackCases = Object.freeze(
  PARITY_MANIFEST_CASE_KEYS.filter((key) => !promotedCases.has(key)),
)

export const PARITY_CASE_ASSIGNMENTS: Readonly<Record<ParityTopicalSuite, readonly string[]>> = Object.freeze({
  holdback: holdbackCases,
  ...TOPICAL_ASSIGNMENTS,
})

import { describe, expect, it } from 'vitest'

import {
  PARITY_CASE_ASSIGNMENTS,
  PARITY_MANIFEST_CASE_KEYS,
} from '../helpers/parity/test-matrix'

const OWNED_SUITE_KEY = 'parityFlatagentBackends' as const

const BACKEND_CASE_KEYS = Object.freeze([
  'sdk/python/tests/integration/codex/test_codex_backend_integration.py::test_flatagent_codex_backend_end_to_end',
  'sdk/python/tests/integration/distributed/test_distributed.py::test_distributed_backends_basic',
])

describe('python parity: flatagent backends', () => {
  it('owns only backend parity cases in the shared matrix', () => {
    const assignments = PARITY_CASE_ASSIGNMENTS as Readonly<Record<string, readonly string[]>>

    expect(assignments[OWNED_SUITE_KEY]).toBeDefined()
    expect(assignments[OWNED_SUITE_KEY]).toEqual(BACKEND_CASE_KEYS)

    const allOtherAssigned = Object.entries(assignments)
      .filter(([suite]) => suite !== OWNED_SUITE_KEY)
      .flatMap(([, keys]) => keys)

    expect(new Set(allOtherAssigned)).toEqual(new Set())
  })

  it('tracks only manifest-backed backend parity case keys', () => {
    const manifestKeys = new Set(PARITY_MANIFEST_CASE_KEYS)

    for (const key of BACKEND_CASE_KEYS) {
      expect(manifestKeys.has(key), `${key} should exist in python manifest`).toBe(true)
    }
  })

  it('keeps backend case keys deterministic and unique', () => {
    expect(BACKEND_CASE_KEYS.length).toBeGreaterThan(0)
    expect(new Set(BACKEND_CASE_KEYS).size).toBe(BACKEND_CASE_KEYS.length)
    expect([...BACKEND_CASE_KEYS]).toEqual([...BACKEND_CASE_KEYS].sort())
  })
})

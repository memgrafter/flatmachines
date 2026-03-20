import { describe, it, expect } from 'vitest'
import {
  PARITY_CASE_ASSIGNMENTS,
  PARITY_MANIFEST_CASE_KEYS,
  PARITY_MANIFEST_METADATA,
  PARITY_TOPICAL_SUITES,
} from '../helpers/parity/test-matrix'

describe('python sdk parity holdback manifest', () => {
  it('captures full python sdk suite snapshot at 2026-03-20T08:38:22', () => {
    expect(PARITY_MANIFEST_METADATA.generatedAt).toBe('2026-03-20T08:38:22')
    expect(PARITY_MANIFEST_METADATA.sourceRoot).toBe('sdk/python/tests')
    expect(PARITY_MANIFEST_METADATA.totalTests).toBe(824)

    expect(PARITY_MANIFEST_CASE_KEYS.length).toBe(PARITY_MANIFEST_METADATA.totalTests)
    expect(new Set(PARITY_MANIFEST_CASE_KEYS).size).toBe(PARITY_MANIFEST_METADATA.totalTests)
  })

  it('assigns every manifest case key exactly once across topical suites', () => {
    const assignmentEntries = Object.entries(PARITY_CASE_ASSIGNMENTS) as Array<
      [keyof typeof PARITY_CASE_ASSIGNMENTS, readonly string[]]
    >

    expect(assignmentEntries.length).toBe(Object.keys(PARITY_TOPICAL_SUITES).length)

    const ownersByKey = new Map<string, string[]>()
    for (const [suiteName, caseKeys] of assignmentEntries) {
      for (const caseKey of caseKeys) {
        const owners = ownersByKey.get(caseKey)
        if (owners) {
          owners.push(String(suiteName))
        } else {
          ownersByKey.set(caseKey, [String(suiteName)])
        }
      }
    }

    const missing = PARITY_MANIFEST_CASE_KEYS.filter((caseKey) => !ownersByKey.has(caseKey))
    const unknown = [...ownersByKey.keys()].filter((caseKey) => !PARITY_MANIFEST_CASE_KEYS.includes(caseKey))
    const duplicateOwners = [...ownersByKey.entries()]
      .filter(([, owners]) => owners.length > 1)
      .map(([caseKey, owners]) => ({ caseKey, owners }))

    expect(
      {
        missing,
        unknown,
        duplicateOwners,
      },
      [
        `Missing manifest case assignments: ${missing.length}`,
        `Unknown assigned case keys: ${unknown.length}`,
        `Duplicate-assigned case keys: ${duplicateOwners.length}`,
      ].join(' | '),
    ).toEqual({
      missing: [],
      unknown: [],
      duplicateOwners: [],
    })
  })

  for (const caseKey of PARITY_MANIFEST_CASE_KEYS) {
    const [filePath, testName] = caseKey.split('::')
    describe(filePath, () => {
      it.todo(testName)
    })
  }
})

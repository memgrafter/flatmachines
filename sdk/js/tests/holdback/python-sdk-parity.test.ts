import { describe, it, expect } from 'vitest'
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

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const manifestPath = resolve(__dirname, 'python-sdk-tests-manifest.json')
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as Manifest

describe('python sdk parity holdback manifest', () => {
  it('captures full python sdk suite snapshot at 2026-03-20T08:38:22', () => {
    expect(manifest.generated_at).toBe('2026-03-20T08:38:22')
    expect(manifest.source_root).toBe('sdk/python/tests')
    expect(manifest.total_tests).toBe(824)
    expect(manifest.files.length).toBeGreaterThan(0)

    const flattened = manifest.files.flatMap((file) => file.tests.map((test) => `${file.file}::${test}`))
    expect(flattened.length).toBe(manifest.total_tests)
    expect(new Set(flattened).size).toBe(manifest.total_tests)
  })

  for (const fileEntry of manifest.files) {
    describe(fileEntry.file, () => {
      for (const testName of fileEntry.tests) {
        it.todo(testName)
      }
    })
  }
})

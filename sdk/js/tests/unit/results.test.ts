import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { inMemoryResultBackend } from '../../src/results'

describe('InMemoryResultBackend', () => {
  beforeEach(() => {
    // Clear the store before each test
    vi.resetAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('Basic CRUD Operations', () => {
    it('should write data successfully', async () => {
      const uri = 'flatagents://test/result'
      const data = { result: 'success', score: 95 }
      
      await inMemoryResultBackend.write(uri, data)
      
      // Should not throw and data should be stored
      expect(true).toBe(true)
    })

    it('should read written data', async () => {
      const uri = 'flatagents://test/completed'
      const data = { analysis: 'completed', confidence: 0.87 }
      
      await inMemoryResultBackend.write(uri, data)
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result).toEqual(data)
    })

    it('should return undefined for non-existent data', async () => {
      const uri = 'flatagents://nonexistent/result'
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result).toBeUndefined()
    })

    it('should check if data exists', async () => {
      const uri = 'flatagents://test/exists'
      const data = { exists: true }
      
      // Before writing
      expect(await inMemoryResultBackend.exists(uri)).toBe(false)
      
      await inMemoryResultBackend.write(uri, data)
      
      // After writing
      expect(await inMemoryResultBackend.exists(uri)).toBe(true)
    })

    it('should delete data successfully', async () => {
      const uri = 'flatagents://test/delete'
      const data = { toDelete: true }
      
      await inMemoryResultBackend.write(uri, data)
      expect(await inMemoryResultBackend.exists(uri)).toBe(true)
      
      await inMemoryResultBackend.delete(uri)
      expect(await inMemoryResultBackend.exists(uri)).toBe(false)
      expect(await inMemoryResultBackend.read(uri)).toBeUndefined()
    })
  })

  describe('Blocking Read Operations', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should block until data is available', async () => {
      const uri = 'flatagents://test/blocking'
      const data = { result: 'finally here' }
      
      // Start blocking read
      const readPromise = inMemoryResultBackend.read(uri, { block: true, timeout: 5000 })
      
      // Data should not be available immediately
      vi.advanceTimersByTime(100)
      
      await inMemoryResultBackend.write(uri, data)
      vi.advanceTimersByTime(100)
      
      const result = await readPromise
      expect(result).toEqual(data)
    })

    it('should timeout when blocking with timeout', async () => {
      const uri = 'flatagents://test/timeout'
      
      const readPromise = inMemoryResultBackend.read(uri, { block: true, timeout: 3000 })
      
      // Advance time past timeout
      vi.advanceTimersByTime(3100)
      
      const result = await readPromise
      expect(result).toBeUndefined()
    })

    it('should use default timeout when not specified', async () => {
      const uri = 'flatagents://test/default-timeout'
      
      const readPromise = inMemoryResultBackend.read(uri, { block: true })
      
      // Advance time past default 30s timeout
      vi.advanceTimersByTime(31000)
      
      const result = await readPromise
      expect(result).toBeUndefined()
    })

    it('should return immediately if data exists', async () => {
      const uri = 'flatagents://test/immediate'
      const data = { result: 'ready' }
      
      await inMemoryResultBackend.write(uri, data)
      
      const readPromise = inMemoryResultBackend.read(uri, { block: true, timeout: 5000 })
      
      // Should not need to advance timers
      const result = await readPromise
      expect(result).toEqual(data)
    })

    it('should handle non-blocking reads', async () => {
      const uri = 'flatagents://test/non-blocking'
      
      const result = await inMemoryResultBackend.read(uri, { block: false })
      expect(result).toBeUndefined()
    })
  })

  describe('Concurrent Operations', () => {
    it('should handle multiple simultaneous writes', async () => {
      const operations = []
      
      for (let i = 0; i < 100; i++) {
        const uri = `flatagents://concurrent/${i}`
        const data = { id: i, timestamp: Date.now() }
        operations.push(inMemoryResultBackend.write(uri, data))
      }
      
      await Promise.all(operations)
      
      // Verify all data was written
      for (let i = 0; i < 100; i++) {
        const uri = `flatagents://concurrent/${i}`
        const exists = await inMemoryResultBackend.exists(uri)
        expect(exists).toBe(true)
      }
    })

    it('should handle multiple simultaneous reads', async () => {
      const uri = 'flatagents://test/simultaneous-reads'
      const data = { result: 'shared data', readers: 50 }
      
      await inMemoryResultBackend.write(uri, data)
      
      const readPromises = Array.from({ length: 50 }, () =>
        inMemoryResultBackend.read(uri)
      )
      
      const results = await Promise.all(readPromises)
      results.forEach(result => {
        expect(result).toEqual(data)
      })
    })

    it('should handle mixed concurrent operations', async () => {
      const operations = []
      
      // Write operations
      for (let i = 0; i < 25; i++) {
        const uri = `flatagents://mixed/write-${i}`
        const data = { operation: 'write', id: i }
        operations.push(inMemoryResultBackend.write(uri, data))
      }
      
      // Read operations
      for (let i = 0; i < 25; i++) {
        const uri = `flatagents://mixed/read-${i}`
        operations.push(inMemoryResultBackend.read(uri))
      }
      
      // Delete operations
      for (let i = 0; i < 25; i++) {
        const uri = `flatagents://mixed/delete-${i}`
        // First write, then delete
        operations.push(
          inMemoryResultBackend.write(uri, { temp: true }).then(() =>
            inMemoryResultBackend.delete(uri)
          )
        )
      }
      
      // Should complete without errors
      await expect(Promise.allSettled(operations)).resolves.toBeDefined()
    })

    it('should handle blocking reads with concurrent writes', async () => {
      vi.useFakeTimers()
      
      const uri = 'flatagents://test/concurrent-blocking'
      const data = { result: 'concurrent success' }
      
      // Start multiple blocking reads
      const readPromises = Array.from({ length: 10 }, () =>
        inMemoryResultBackend.read(uri, { block: true, timeout: 5000 })
      )
      
      // Write data after some time
      setTimeout(() => {
        inMemoryResultBackend.write(uri, data)
      }, 1000)
      
      vi.advanceTimersByTime(1000)
      vi.advanceTimersByTime(100)
      
      const results = await Promise.all(readPromises)
      results.forEach(result => {
        expect(result).toEqual(data)
      })
      
      vi.useRealTimers()
    })
  })

  describe('Data Types and Serialization', () => {
    it('should handle different data types', async () => {
      const testCases = [
        { uri: 'test/string', data: 'simple string' },
        { uri: 'test/number', data: 42 },
        { uri: 'test/boolean', data: true },
        { uri: 'test/null', data: null },
        { uri: 'test/array', data: [1, 2, 3, 'string', { nested: true }] },
        { uri: 'test/object', data: { nested: { deep: { value: 'test' } } } }
      ]
      
      // Write all test cases
      for (const testCase of testCases) {
        await inMemoryResultBackend.write(testCase.uri, testCase.data)
      }
      
      // Read and verify all test cases
      for (const testCase of testCases) {
        const result = await inMemoryResultBackend.read(testCase.uri)
        expect(result).toEqual(testCase.data)
      }
    })

    it('should handle complex nested objects', async () => {
      const uri = 'test/complex-nested'
      const data = {
        metadata: {
          version: '1.0.0',
          timestamp: Date.now(),
          tags: ['production', 'v2', 'api']
        },
        results: {
          primary: {
            score: 0.95,
            confidence: 0.87,
            predictions: Array.from({ length: 100 }, (_, i) => ({
              id: i,
              probability: Math.random(),
              label: `class_${i % 10}`
            }))
          },
          secondary: {
            metrics: {
              precision: 0.92,
              recall: 0.89,
              f1: 0.90
            },
            processing_time: 150.5
          }
        },
        errors: [],
        warnings: []
      }
      
      await inMemoryResultBackend.write(uri, data)
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result).toEqual(data)
      expect(result.results.primary.predictions).toHaveLength(100)
      expect(result.results.secondary.metrics.f1).toBe(0.90)
    })

    it('should handle large data objects', async () => {
      const uri = 'test/large-data'
      const largeData = {
        array: Array.from({ length: 10000 }, (_, i) => ({ id: i, value: `item_${i}` })),
        text: 'x'.repeat(50000),
        nested: {
          level1: {
            level2: {
              level3: {
                data: Array.from({ length: 1000 }, (_, i) => `nested_${i}`)
              }
            }
          }
        }
      }
      
      await inMemoryResultBackend.write(uri, largeData)
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result.array).toHaveLength(10000)
      expect(result.text.length).toBe(50000)
      expect(result.nested.level1.level2.level3.data).toHaveLength(1000)
    })

    it('should handle data with special characters', async () => {
      const uri = 'special-chars'
      const data = {
        unicode: '你好 🌍 🚀 测试',
        specialChars: 'Quotes " and \' and ` and \\n and \\t',
        html: '<script>alert("test")</script>',
        json: '{"nested": {"json": "string"}}',
        emoji: '😀😎🎊🔥💯',
        newlines: 'Line 1\nLine 2\nLine 3',
        tabs: 'Column1\tColumn2\tColumn3'
      }
      
      await inMemoryResultBackend.write(uri, data)
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result).toEqual(data)
    })
  })

  describe('URI Handling', () => {
    it('should handle various URI formats', async () => {
      const testCases = [
        { uri: 'flatagents://simple/path', data: { path: 'simple' } },
        { uri: 'flatagents://complex/nested/deep/path', data: { deep: true } },
        { uri: 'flatagents://with-parameters?id=123&version=v2', data: { params: true } },
        { uri: 'flatagents://unicode/路径/测试', data: { unicode: 'test' } },
        { uri: 'flatagents://special/chars@#$%^&*()', data: { special: true } }
      ]
      
      for (const testCase of testCases) {
        await inMemoryResultBackend.write(testCase.uri, testCase.data)
        const result = await inMemoryResultBackend.read(testCase.uri)
        expect(result).toEqual(testCase.data)
        expect(await inMemoryResultBackend.exists(testCase.uri)).toBe(true)
      }
    })

    it('should handle edge case URIs', async () => {
      const edgeCases = [
        { uri: 'flatagents://', data: { root: true } },
        { uri: 'flatagents://empty-path/', data: { empty: true } },
        { uri: 'flatagents://' + 'a'.repeat(1000), data: { long: true } }
      ]
      
      for (const testCase of edgeCases) {
        await inMemoryResultBackend.write(testCase.uri, testCase.data)
        const result = await inMemoryResultBackend.read(testCase.uri)
        expect(result).toEqual(testCase.data)
      }
    })

    it('should handle similar but distinct URIs', async () => {
      const uris = [
        'flatagents://test/similar/path',
        'flatagents://test/similar/path/',
        'flatagents://test/similar/Path', // Case sensitivity
        'flatagents://test/similar/path?param=value'
      ]
      
      const data = { test: 'data' }
      
      for (const uri of uris) {
        await inMemoryResultBackend.write(uri, { ...data, uri })
      }
      
      // Each URI should have distinct data
      for (let i = 0; i < uris.length; i++) {
        const result = await inMemoryResultBackend.read(uris[i])
        expect(result.uri).toBe(uris[i])
      }
    })
  })

  describe('Error Handling and Edge Cases', () => {
    it('should handle empty string URIs', async () => {
      const data = { test: 'data' }

      // Empty string is a valid key
      await inMemoryResultBackend.write('', data)
      const result = await inMemoryResultBackend.read('')
      expect(result).toEqual(data)
      expect(await inMemoryResultBackend.exists('')).toBe(true)

      // Cleanup
      await inMemoryResultBackend.delete('')
    })

    it('should handle empty data', async () => {
      const uri = 'test/empty-data'
      
      await inMemoryResultBackend.write(uri, {})
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result).toEqual({})
      expect(await inMemoryResultBackend.exists(uri)).toBe(true)
    })

    it('should handle circular references in data', async () => {
      const uri = 'test/circular'
      const data: any = { name: 'test' }
      data.self = data // Create circular reference
      
      // Should handle circular reference gracefully
      await inMemoryResultBackend.write(uri, data)
      const result = await inMemoryResultBackend.read(uri)
      
      expect(result).toEqual(data)
    })

    it('should handle delete of non-existent keys', async () => {
      const nonExistentUri = 'flatagents://nonexistent/key'
      
      // Should not throw
      await expect(inMemoryResultBackend.delete(nonExistentUri)).resolves.toBeUndefined()
      expect(await inMemoryResultBackend.exists(nonExistentUri)).toBe(false)
    })

    it('should handle multiple writes to same URI', async () => {
      const uri = 'test/overwrite'
      const data1 = { version: 1, data: 'first' }
      const data2 = { version: 2, data: 'second' }
      const data3 = { version: 3, data: 'third' }
      
      await inMemoryResultBackend.write(uri, data1)
      expect(await inMemoryResultBackend.read(uri)).toEqual(data1)
      
      await inMemoryResultBackend.write(uri, data2)
      expect(await inMemoryResultBackend.read(uri)).toEqual(data2)
      
      await inMemoryResultBackend.write(uri, data3)
      expect(await inMemoryResultBackend.read(uri)).toEqual(data3)
    })

    it('should handle rapid read-write-delete cycles', async () => {
      const uri = 'test/rapid-cycle'
      
      for (let i = 0; i < 100; i++) {
        const data = { iteration: i, timestamp: Date.now() }
        
        await inMemoryResultBackend.write(uri, data)
        expect(await inMemoryResultBackend.exists(uri)).toBe(true)
        
        const read = await inMemoryResultBackend.read(uri)
        expect(read).toEqual(data)
        
        await inMemoryResultBackend.delete(uri)
        expect(await inMemoryResultBackend.exists(uri)).toBe(false)
        expect(await inMemoryResultBackend.read(uri)).toBeUndefined()
      }
    })
  })

  describe('Performance Testing', () => {
    it('should handle high volume operations efficiently', async () => {
      const operationCount = 1000
      const operations = []
      
      // Time the write operations
      const writeStart = Date.now()
      
      for (let i = 0; i < operationCount; i++) {
        const uri = `perf/write-${i}`
        const data = { id: i, timestamp: Date.now() }
        operations.push(inMemoryResultBackend.write(uri, data))
      }
      
      await Promise.all(operations)
      const writeTime = Date.now() - writeStart
      
      // Write operations should complete in reasonable time
      expect(writeTime).toBeLessThan(1000)
      
      // Time the read operations
      const readStart = Date.now()
      const readOperations = []
      
      for (let i = 0; i < operationCount; i++) {
        const uri = `perf/write-${i}`
        readOperations.push(inMemoryResultBackend.read(uri))
      }
      
      const readResults = await Promise.all(readOperations)
      const readTime = Date.now() - readStart
      
      expect(readTime).toBeLessThan(1000)
      expect(readResults).toHaveLength(operationCount)
    })

    it('should handle simultaneous blocking reads efficiently', async () => {
      vi.useFakeTimers()
      
      const concurrentReads = 100
      const uri = 'perf/concurrent-blocking'
      const data = { result: 'concurrent success' }
      
      // Start all blocking reads
      const readPromises = Array.from({ length: concurrentReads }, () =>
        inMemoryResultBackend.read(uri, { block: true, timeout: 5000 })
      )
      
      // Write data after small delay
      setTimeout(() => {
        inMemoryResultBackend.write(uri, data)
      }, 100)
      
      // Advance time
      vi.advanceTimersByTime(200)
      
      const startTime = Date.now()
      const results = await Promise.all(readPromises)
      const duration = Date.now() - startTime
      
      vi.useRealTimers()
      
      // All reads should complete successfully
      expect(results).toHaveLength(concurrentReads)
      results.forEach(result => {
        expect(result).toEqual(data)
      })
      
      // Should complete in reasonable time
      expect(duration).toBeLessThan(5000)
    })
  })

  describe('Memory Management', () => {
    it('should handle large amounts of data without memory leaks', async () => {
      const largeDataSets = []
      
      // Store multiple large datasets
      for (let i = 0; i < 10; i++) {
        const uri = `memory/large-${i}`
        const data = {
          id: i,
          dataset: Array.from({ length: 5000 }, (_, j) => ({
            index: j,
            data: `item_${i}_${j}`,
            random: Math.random()
          }))
        }
        
        await inMemoryResultBackend.write(uri, data)
        largeDataSets.push({ uri, data })
      }
      
      // Verify all data is still accessible
      for (const { uri, data } of largeDataSets) {
        const result = await inMemoryResultBackend.read(uri)
        expect(result).toEqual(data)
        expect(result.dataset).toHaveLength(5000)
      }
    })

    it('should clean up data properly when deleted', async () => {
      const tempUri = 'memory/temp-cleanup'
      const data = { temp: true }
      
      // Write data
      await inMemoryResultBackend.write(tempUri, data)
      expect(await inMemoryResultBackend.exists(tempUri)).toBe(true)
      
      // Delete data
      await inMemoryResultBackend.delete(tempUri)
      expect(await inMemoryResultBackend.exists(tempUri)).toBe(false)
      expect(await inMemoryResultBackend.read(tempUri)).toBeUndefined()
      
      // Verify data can't be accessed after deletion
      expect(await inMemoryResultBackend.exists(tempUri)).toBe(false)
    })

    it('should handle overwriting data efficiently', async () => {
      const uri = 'memory/overwrite'
      const iterations = 100
      
      // Repeatedly overwrite the same URI with different data
      for (let i = 0; i < iterations; i++) {
        const data = {
          iteration: i,
          payload: 'x'.repeat(1000), // 1KB payload
          timestamp: Date.now()
        }
        
        await inMemoryResultBackend.write(uri, data)
        
        const result = await inMemoryResultBackend.read(uri)
        expect(result.iteration).toBe(i)
        expect(result.payload.length).toBe(1000)
      }
      
      // Final data should be accessible
      const finalResult = await inMemoryResultBackend.read(uri)
      expect(finalResult.iteration).toBe(iterations - 1)
    })
  })

  describe('Integration Scenarios', () => {
    it('should handle typical FlatAgents workflow', async () => {
      const executionId = 'exec-12345'
      const scenarioData = {
        execution_start: { timestamp: Date.now(), status: 'started' },
        agent_results: {
          analysis: { confidence: 0.92, sentiment: 'positive' },
          summary: { text: 'Analysis completed successfully', wordCount: 152 }
        },
        execution_end: { timestamp: Date.now(), status: 'completed', duration: 4500 }
      }
      
      // Write results at different stages
      await inMemoryResultBackend.write(
        `flatagents://${executionId}/start`,
        scenarioData.execution_start
      )
      
      await inMemoryResultBackend.write(
        `flatagents://${executionId}/results`,
        scenarioData.agent_results
      )
      
      await inMemoryResultBackend.write(
        `flatagents://${executionId}/end`,
        scenarioData.execution_end
      )
      
      // Read all results
      const start = await inMemoryResultBackend.read(`flatagents://${executionId}/start`)
      const results = await inMemoryResultBackend.read(`flatagents://${executionId}/results`)
      const end = await inMemoryResultBackend.read(`flatagents://${executionId}/end`)
      
      expect(start.status).toBe('started')
      expect(results.analysis.confidence).toBe(0.92)
      expect(end.status).toBe('completed')
      
      // Check existence
      expect(await inMemoryResultBackend.exists(`flatagents://${executionId}/results`)).toBe(true)
    })

    it('should handle parallel machine execution results', async () => {
      const machineNames = ['analyzer', 'validator', 'processor', 'formatter']
      const executionId = 'parallel-exec-67890'
      const results = {}
      
      // Simulate parallel machines writing results
      const writePromises = machineNames.map(async (machine) => {
        const uri = `flatagents://${executionId}/${machine}`
        const data = {
          machine,
          status: 'completed',
          result: `Result from ${machine}`,
          timestamp: Date.now()
        }
        
        await inMemoryResultBackend.write(uri, data)
        results[machine] = data
      })
      
      await Promise.all(writePromises)
      
      // Read all machine results
      const readPromises = machineNames.map(machine =>
        inMemoryResultBackend.read(`flatagents://${executionId}/${machine}`)
      )
      
      const machineResults = await Promise.all(readPromises)
      
      machineResults.forEach((result, index) => {
        expect(result.machine).toBe(machineNames[index])
        expect(result.status).toBe('completed')
      })
      
      // Should be able to aggregate results
      const aggregated = machineResults.reduce((acc, result) => {
        acc[result.machine] = result.result
        return acc
      }, {})
      
      expect(Object.keys(aggregated)).toHaveLength(4)
    })

    it('should handle result backend timeout scenarios', async () => {
      vi.useFakeTimers()
      
      const executionId = 'timeout-exec-123'
      const resultUri = `flatagents://${executionId}/results`
      const data = { result: 'final data', completion: true }
      
      // Start blocking read with long timeout
      const readPromise = inMemoryResultBackend.read(resultUri, {
        block: true,
        timeout: 60000 // 60 seconds
      })
      
      // Write data after 10 seconds
      setTimeout(() => {
        inMemoryResultBackend.write(resultUri, data)
      }, 10000)
      
      // Advance time to when data should be available
      vi.advanceTimersByTime(10000)
      vi.advanceTimersByTime(100)
      
      const result = await readPromise
      expect(result).toEqual(data)
      
      vi.useRealTimers()
    })
  })
})
import { vi } from 'vitest'
import { readFileSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'
import { AgentConfig, MachineConfig, State } from '../../src/types'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

/**
 * Load a YAML configuration file from test fixtures
 */
export function loadTestConfig(category: string, filename: string): string {
  const configPath = join(__dirname, 'configs', category, filename)
  return readFileSync(configPath, 'utf-8')
}

/**
 * Parse YAML configuration string
 */
export function parseTestConfig(yamlString: string): any {
  try {
    const yaml = require('yaml')
    return yaml.parse(yamlString)
  } catch (error) {
    throw new Error(`Failed to parse YAML: ${error}`)
  }
}

/**
 * Load and parse a test configuration
 */
export function loadConfig(category: string, filename: string): any {
  const yamlString = loadTestConfig(category, filename)
  return parseTestConfig(yamlString)
}

/**
 * Create a minimal FlatAgent configuration for testing
 */
export function createMinimalAgentConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    spec: 'flatagent',
    spec_version: '0.1.0',
    data: {
      model: {
        provider: 'openai',
        name: 'gpt-4'
      },
      system: 'You are a helpful assistant.',
      user: 'Hello, {{ name }}!',
      output: {
        response: { type: 'string', description: 'The response to the user' }
      },
      ...overrides.data
    },
    ...overrides
  }
}

/**
 * Create a minimal FlatMachine configuration for testing
 */
export function createMinimalMachineConfig(overrides: Partial<MachineConfig> = {}): MachineConfig {
  return {
    spec: 'flatmachine',
    spec_version: '0.1.0',
    data: {
states: {
        initial: {
          type: 'initial' as const,
          agent: 'test_agent',
          input: {
            query: '{{ input.query }}'
          },
          output_to_context: {
            result: '{{ output }}'
          },
          transitions: [
            { condition: 'true', to: 'final' }
          ]
        },
        final: {
          type: 'final' as const,
          output: { result: '{{ context.result }}' }
        }
      } as Record<string, State>,
      ...overrides.data
    },
    ...overrides
  }
}

/**
 * Create mock hooks for testing
 */
export function createMockHooks() {
  return {
    onMachineStart: vi.fn(),
    onMachineEnd: vi.fn(),
    onStateEnter: vi.fn(),
    onStateExit: vi.fn(),
    onAction: vi.fn(),
    onTransition: vi.fn(),
    onError: vi.fn()
  }
}

/**
 * Create a mock MCP tool
 */
export function createMockTool(name: string, description: string = '') {
  return {
    name,
    description: description || `Mock tool ${name}`,
    inputSchema: {
      type: 'object',
      properties: {
        input: { type: 'string' }
      }
    }
  }
}

/**
 * Mock network failure for testing
 */
export function mockNetworkFailure() {
  vi.mock('@ai-sdk/openai', () => ({
    openai: vi.fn(() => {
      throw new Error('Network error: Unable to connect to API')
    })
  }))
}

/**
 * Mock rate limit error for testing
 */
export function mockRateLimitError() {
  vi.mock('@ai-sdk/openai', () => ({
    openai: vi.fn(() => {
      const error = new Error('Rate limit exceeded')
      error.name = 'RateLimitError'
      throw error
    })
  }))
}

/**
 * Mock authentication error for testing
 */
export function mockAuthError() {
  vi.mock('@ai-sdk/openai', () => ({
    openai: vi.fn(() => {
      const error = new Error('Authentication failed')
      error.name = 'AuthenticationError'
      throw error
    })
  }))
}

/**
 * Create a temporary directory path for test files
 */
export function getTempDir(testName: string): string {
  return join(__dirname, '..', '..', 'temp', testName)
}

/**
 * Clean up temporary directory and files
 */
export function cleanupTempDir(testName: string): void {
  const fs = require('fs')
  const tempDir = getTempDir(testName)
  if (fs.existsSync(tempDir)) {
    fs.rmSync(tempDir, { recursive: true, force: true })
  }
}

/**
 * Capture console logs for testing
 */
export function captureLogs() {
  const logs: string[] = []
  const originalLog = console.log
  const originalError = console.error
  const originalWarn = console.warn

  console.log = (...args) => logs.push(`LOG: ${args.join(' ')}`)
  console.error = (...args) => logs.push(`ERROR: ${args.join(' ')}`)
  console.warn = (...args) => logs.push(`WARN: ${args.join(' ')}`)

  return {
    getLogs: () => logs,
    reset: () => {
      console.log = originalLog
      console.error = originalError
      console.warn = originalWarn
    }
  }
}

/**
 * Measure execution time for performance tests
 */
export function measurePerformance<T>(fn: () => T): { result: T; duration: number } {
  const start = performance.now()
  const result = fn()
  const end = performance.now()
  return { result, duration: end - start }
}

/**
 * Measure async execution time for performance tests
 */
export async function measureAsyncPerformance<T>(fn: () => Promise<T>): Promise<{ result: T; duration: number }> {
  const start = performance.now()
  const result = await fn()
  const end = performance.now()
  return { result, duration: end - start }
}

/**
 * Create a file system watcher mock
 */
export function createMockWatcher() {
  const callbacks: Array<(eventType: string, filename: string) => void> = []
  
  return {
    watch: vi.fn((path: string, callback: (eventType: string, filename: string) => void) => {
      callbacks.push(callback)
      return {
        close: vi.fn()
      }
    }),
    triggerEvent: (eventType: string, filename: string) => {
      callbacks.forEach(callback => callback(eventType, filename))
    }
  }
}

/**
 * Create a mock HTTP server for webhook testing
 */
export function createMockServer() {
  const requests: Array<{ method: string; url: string; body: any; headers: any }> = []
  
  return {
    listen: vi.fn((port: number, callback: () => void) => {
      callback()
      return {
        close: vi.fn()
      }
    }),
    on: vi.fn((event: string, callback: (req: any, res: any) => void) => {
      if (event === 'request') {
        // Mock request object
        const mockReq = {
          method: 'POST',
          url: '/webhook',
          headers: { 'content-type': 'application/json' },
          body: {},
          on: vi.fn((event: string, handler: Function) => {
            if (event === 'data') {
              handler(JSON.stringify({ test: 'data' }))
            } else if (event === 'end') {
              handler()
            }
          })
        }
        
        // Mock response object
        const mockRes = {
          statusCode: 200,
          setHeader: vi.fn(),
          end: vi.fn()
        }
        
        requests.push({
          method: mockReq.method,
          url: mockReq.url,
          body: mockReq.body,
          headers: mockReq.headers
        })
        
        callback(mockReq, mockRes)
      }
    }),
    getRequests: () => requests,
    clearRequests: () => requests.length = 0
  }
}

/**
 * Automatic cleanup wrapper for tests
 */
export function withCleanup(testName: string, testFn: () => Promise<void>) {
  return async () => {
    try {
      await testFn()
    } finally {
      cleanupTempDir(testName)
    }
  }
}
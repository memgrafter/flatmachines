import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { WebhookHooks, CompositeHooks } from '../../src/hooks'
import { createMockHooks, createMockServer } from '../fixtures/helpers'

describe('WebhookHooks', () => {
  describe('Constructor and Initialization', () => {
    it('should initialize with webhook URL', () => {
      const webhookUrl = 'https://example.com/webhook'
      const hooks = new WebhookHooks(webhookUrl)
      expect(hooks).toBeDefined()
    })

    it('should handle different URL formats', () => {
      const urls = [
        'https://api.example.com/webhooks',
        'http://localhost:3000/hook',
        'https://webhook.site/abc123',
        'https://example.com:8080/hooks/machine-events'
      ]
      
      urls.forEach(url => {
        expect(() => new WebhookHooks(url)).not.toThrow()
      })
    })

    it('should handle invalid URLs gracefully', () => {
      const invalidUrls = [
        '',
        'not-a-url',
        'ftp://example.com/hook',
        'javascript://evil.com'
      ]
      
      // WebhookHooks should not throw during construction
      invalidUrls.forEach(url => {
        expect(() => new WebhookHooks(url)).not.toThrow()
      })
    })
  })

  describe('Webhook Payload Sending', () => {
    beforeEach(() => {
      vi.resetAllMocks()
      // Mock fetch globally
      global.fetch = vi.fn()
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should send machine_start event', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true })
      global.fetch = mockFetch
      
      const webhookUrl = 'https://example.com/webhook'
      const hooks = new WebhookHooks(webhookUrl)
      const context = { test: 'data', user: 'john' }
      
      await hooks.onMachineStart(context)
      
      expect(mockFetch).toHaveBeenCalledWith(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('"event":"machine_start"')
      })
      
      const callArgs = mockFetch.mock.calls[0]
      const body = JSON.parse(callArgs[1].body)
      expect(body.event).toBe('machine_start')
      expect(body.context).toEqual(context)
      expect(body.timestamp).toBeDefined()
    })

    it('should send machine_end event', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true })
      global.fetch = mockFetch
      
      const webhookUrl = 'https://example.com/webhook'
      const hooks = new WebhookHooks(webhookUrl)
      const context = { test: 'data' }
      const output = { result: 'success', score: 0.95 }
      
      await hooks.onMachineEnd(context, output)
      
      expect(mockFetch).toHaveBeenCalledWith(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('"event":"machine_end"')
      })
      
      const callArgs = mockFetch.mock.calls[0]
      const body = JSON.parse(callArgs[1].body)
      expect(body.event).toBe('machine_end')
      expect(body.context).toEqual(context)
      expect(body.output).toEqual(output)
      expect(body.timestamp).toBeDefined()
    })

    it('should send state_enter event', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true })
      global.fetch = mockFetch
      
      const webhookUrl = 'https://example.com/webhook'
      const hooks = new WebhookHooks(webhookUrl)
      const state = 'processing'
      const context = { step: 1, data: 'test' }
      
      await hooks.onStateEnter(state, context)
      
      expect(mockFetch).toHaveBeenCalledWith(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('"event":"state_enter"')
      })
      
      const callArgs = mockFetch.mock.calls[0]
      const body = JSON.parse(callArgs[1].body)
      expect(body.event).toBe('state_enter')
      expect(body.state).toBe(state)
      expect(body.context).toEqual(context)
      expect(body.timestamp).toBeDefined()
    })

    it('should send state_exit event', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ ok: true })
      global.fetch = mockFetch
      
      const webhookUrl = 'https://example.com/webhook'
      const hooks = new WebhookHooks(webhookUrl)
      const state = 'processing'
      const context = { step: 1 }
      const output = { result: 'processed' }
      
      await hooks.onStateExit(state, context, output)
      
      expect(mockFetch).toHaveBeenCalledWith(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: expect.stringContaining('"event":"state_exit"')
      })
      
      const callArgs = mockFetch.mock.calls[0]
      const body = JSON.parse(callArgs[1].body)
      expect(body.event).toBe('state_exit')
      expect(body.state).toBe(state)
      expect(body.context).toEqual(context)
      expect(body.output).toEqual(output)
      expect(body.timestamp).toBeDefined()
    })
  })

  describe('Context and Output Return Values', () => {
    beforeEach(() => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should return original context from onMachineStart', async () => {
      const hooks = new WebhookHooks('https://example.com/webhook')
      const context = { user: 'test', session: 'abc123' }
      
      const result = await hooks.onMachineStart(context)
      expect(result).toEqual(context)
    })

    it('should return original output from onMachineEnd', async () => {
      const hooks = new WebhookHooks('https://example.com/webhook')
      const context = { test: 'data' }
      const output = { result: 'success' }
      
      const result = await hooks.onMachineEnd(context, output)
      expect(result).toEqual(output)
    })

    it('should return original context from onStateEnter', async () => {
      const hooks = new WebhookHooks('https://example.com/webhook')
      const state = 'test_state'
      const context = { step: 1, data: 'test' }
      
      const result = await hooks.onStateEnter(state, context)
      expect(result).toEqual(context)
    })

    it('should return original output from onStateExit', async () => {
      const hooks = new WebhookHooks('https://example.com/webhook')
      const state = 'test_state'
      const context = { step: 1 }
      const output = { result: 'processed' }
      
      const result = await hooks.onStateExit(state, context, output)
      expect(result).toEqual(output)
    })
  })

  describe('Error Handling', () => {
    beforeEach(() => {
      vi.resetAllMocks()
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should handle network errors gracefully', async () => {
      const mockFetch = vi.fn().mockRejectedValue(new Error('Network error'))
      global.fetch = mockFetch
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      const context = { test: 'data' }
      
      // Should not throw errors
      expect(await hooks.onMachineStart(context)).toEqual(context)
    })

    it('should handle timeout errors gracefully', async () => {
      const mockFetch = vi.fn().mockRejectedValue(new Error('Request timeout'))
      global.fetch = mockFetch
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      const context = { test: 'data' }
      
      expect(await hooks.onMachineStart(context)).toEqual(context)
    })

    it('should handle non-2xx responses gracefully', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ 
        status: 500, 
        statusText: 'Internal Server Error',
        ok: false 
      })
      global.fetch = mockFetch
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      const context = { test: 'data' }
      
      expect(await hooks.onMachineStart(context)).toEqual(context)
    })

    it('should handle malformed JSON in response', async () => {
      const mockFetch = vi.fn().mockResolvedValue({ 
        ok: true,
        text: () => Promise.resolve('invalid json')
      })
      global.fetch = mockFetch
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      const context = { test: 'data' }
      
      expect(await hooks.onMachineStart(context)).toEqual(context)
    })
  })

  describe('Complex Payload Handling', () => {
    beforeEach(() => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true })
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('should handle large context objects', async () => {
      const largeContext = {
        data: 'x'.repeat(10000),
        nested: {
          array: new Array(1000).fill(0).map((_, i) => ({ id: i, value: `item_${i}` })),
          deep: {
            level1: { level2: { level3: { level4: { value: 'deep_value' } } } }
          }
        }
      }
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      
      expect(await hooks.onMachineStart(largeContext)).toEqual(largeContext)
    })

    it('should handle special characters in data', async () => {
      const specialContext = {
        unicode: '你好 🌍 🚀 测试',
        specialChars: 'Quotes " and \' and ` and \\n and \\t',
        emoji: '😀😎🎊🔥💯',
        html: '<script>alert("test")</script>',
        json: '{"nested": {"json": "string"}}'
      }
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      
      expect(await hooks.onMachineStart(specialContext)).toEqual(specialContext)
    })

    it('should handle circular references in context', async () => {
      const context: any = { name: 'test' }
      context.self = context // Create circular reference
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      
      // JSON.stringify should handle this by throwing, but hooks should not crash
      expect(await hooks.onMachineStart(context)).toEqual(context)
    })

    it('should handle null and undefined values', async () => {
      const context = {
        nullValue: null,
        undefinedValue: undefined,
        nestedNull: { value: null },
        nestedUndefined: { value: undefined }
      }
      
      const hooks = new WebhookHooks('https://example.com/webhook')
      
      expect(await hooks.onMachineStart(context)).toEqual(context)
    })
  })
})

describe('CompositeHooks', () => {
  describe('Constructor and Initialization', () => {
    it('should initialize with array of hooks', () => {
      const mockHook1 = createMockHooks()
      const mockHook2 = createMockHooks()
      const composite = new CompositeHooks([mockHook1, mockHook2])
      
      expect(composite).toBeDefined()
    })

    it('should handle empty hooks array', () => {
      const composite = new CompositeHooks([])
      expect(composite).toBeDefined()
    })

    it('should handle single hook in array', () => {
      const mockHook = createMockHooks()
      const composite = new CompositeHooks([mockHook])
      expect(composite).toBeDefined()
    })

    it('should handle mixed hook implementations', () => {
      const fullHook = createMockHooks()
      const partialHook = {
        onMachineStart: vi.fn(),
        onStateEnter: vi.fn()
      }
      const emptyHook = {}
      
      expect(() => new CompositeHooks([fullHook, partialHook, emptyHook as any])).not.toThrow()
    })
  })

  describe('Hook Execution Order', () => {
    it('should execute hooks in order for onMachineStart', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      const hook3 = createMockHooks()
      
      let callOrder = 0
      hook1.onMachineStart.mockImplementation(async (ctx) => {
        callOrder++
        return { ...ctx, order: callOrder }
      })
      hook2.onMachineStart.mockImplementation(async (ctx) => {
        callOrder++
        return { ...ctx, order: callOrder }
      })
      hook3.onMachineStart.mockImplementation(async (ctx) => {
        callOrder++
        return { ...ctx, order: callOrder }
      })
      
      const composite = new CompositeHooks([hook1, hook2, hook3])
      const result = await composite.onMachineStart({ test: 'data' })
      
      expect(hook1.onMachineStart).toHaveBeenCalled()
      expect(hook2.onMachineStart).toHaveBeenCalled()
      expect(hook3.onMachineStart).toHaveBeenCalled()
      expect(result.order).toBe(3) // Last hook's result
    })

    it('should execute hooks in order for onStateEnter', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onStateEnter.mockImplementation(async (state, ctx) => ({ ...ctx, hook1: true }))
      hook2.onStateEnter.mockImplementation(async (state, ctx) => ({ ...ctx, hook2: true }))
      
      const composite = new CompositeHooks([hook1, hook2])
      const result = await composite.onStateEnter('test_state', { test: 'data' })
      
      expect(result.hook1).toBe(true)
      expect(result.hook2).toBe(true)
    })

    it('should execute hooks in order for onMachineEnd', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onMachineEnd.mockImplementation(async (ctx, output) => ({ ...output, processed: 1 }))
      hook2.onMachineEnd.mockImplementation(async (ctx, output) => ({ ...output, processed: 2 }))
      
      const composite = new CompositeHooks([hook1, hook2])
      const result = await composite.onMachineEnd({ test: 'ctx' }, { data: 'output' })
      
      expect(result.processed).toBe(2)
    })
  })

  describe('Data Flow Between Hooks', () => {
    it('should pass modified context between hooks', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onMachineStart.mockImplementation(async (ctx) => ({ 
        ...ctx, 
        modified_by: 'hook1',
        timestamp: Date.now()
      }))
      
      hook2.onMachineStart.mockImplementation(async (ctx) => ({ 
        ...ctx, 
        modified_by: 'hook2',
        received_timestamp: ctx.timestamp
      }))
      
      const composite = new CompositeHooks([hook1, hook2])
      const result = await composite.onMachineStart({ initial: 'data' })
      
      expect(result.modified_by).toBe('hook2')
      expect(result.timestamp).toBeDefined()
      expect(result.received_timestamp).toBe(result.timestamp)
    })

    it('should pass output between hooks', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()

      hook1.onMachineEnd.mockImplementation(async (ctx, output) => ({
        ...output,
        hook1_processed: true,
        score: (output.score || 0) + 10
      }))

      hook2.onMachineEnd.mockImplementation(async (ctx, output) => ({
        ...output,
        hook2_processed: true,
        final_score: output.score + 5
      }))

      const composite = new CompositeHooks([hook1, hook2])
      const result = await composite.onMachineEnd({}, { score: 50 })

      expect(result.hook1_processed).toBe(true)
      expect(result.hook2_processed).toBe(true)
      expect(result.final_score).toBe(65) // 50 + 10 + 5
    })
  })

  describe('Optional Hook Methods', () => {
    it('should handle missing onMachineStart gracefully', async () => {
      const partialHook = { onStateEnter: vi.fn() }
      const fullHook = createMockHooks()
      
      fullHook.onMachineStart.mockImplementation(async (ctx) => ({ ...ctx, processed: true }))
      
      const composite = new CompositeHooks([partialHook, fullHook])
      const result = await composite.onMachineStart({ test: 'data' })
      
      expect(result.processed).toBe(true)
    })

    it('should handle missing onMachineEnd gracefully', async () => {
      const partialHook = { onStateEnter: vi.fn() }
      const fullHook = createMockHooks()
      
      fullHook.onMachineEnd.mockImplementation(async (ctx, output) => ({ ...output, end: true }))
      
      const composite = new CompositeHooks([partialHook, fullHook])
      const result = await composite.onMachineEnd({}, { test: 'data' })
      
      expect(result.end).toBe(true)
    })

    it('should handle missing onStateEnter gracefully', async () => {
      const partialHook = { onMachineStart: vi.fn() }
      const fullHook = createMockHooks()
      
      fullHook.onStateEnter.mockImplementation(async (state, ctx) => ({ ...ctx, entered: state }))
      
      const composite = new CompositeHooks([partialHook, fullHook])
      const result = await composite.onStateEnter('test_state', { test: 'data' })
      
      expect(result.entered).toBe('test_state')
    })

    it('should handle missing onStateExit gracefully', async () => {
      const partialHook = { onMachineStart: vi.fn() }
      const fullHook = createMockHooks()
      
      fullHook.onStateExit.mockImplementation(async (state, ctx, output) => ({ ...output, exited: state }))
      
      const composite = new CompositeHooks([partialHook, fullHook])
      const result = await composite.onStateExit('test_state', {}, { test: 'data' })
      
      expect(result.exited).toBe('test_state')
    })

    it('should handle missing onTransition gracefully', async () => {
      const partialHook = { onMachineStart: vi.fn() }
      const fullHook = createMockHooks()
      
      fullHook.onTransition.mockImplementation(async (from, to, ctx) => to)
      
      const composite = new CompositeHooks([partialHook, fullHook])
      const result = await composite.onTransition('state1', 'state2', {})
      
      expect(result).toBe('state2')
    })

    it('should handle missing onError gracefully', async () => {
      const partialHook = { onMachineStart: vi.fn() }
      const fullHook = createMockHooks()
      
      fullHook.onError.mockImplementation(async (state, error, ctx) => 'recovery_state')
      
      const composite = new CompositeHooks([partialHook, fullHook])
      const result = await composite.onError('error_state', new Error('test'), {})
      
      expect(result).toBe('recovery_state')
    })
  })

  describe('Error Handling in Composite', () => {
    it('should continue execution when one hook fails', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onMachineStart.mockRejectedValue(new Error('Hook 1 failed'))
      hook2.onMachineStart.mockImplementation(async (ctx) => ({ ...ctx, hook2_success: true }))
      
      const composite = new CompositeHooks([hook1, hook2])
      
      // Should handle the error gracefully and continue with next hook
      expect(await composite.onMachineStart({ test: 'data' })).toEqual(expect.objectContaining({
        hook2_success: true
      }))
    })

    it('should handle all hooks failing', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onMachineStart.mockRejectedValue(new Error('Hook 1 failed'))
      hook2.onMachineStart.mockRejectedValue(new Error('Hook 2 failed'))
      
      const composite = new CompositeHooks([hook1, hook2])
      
      // Should return the input context if all hooks fail
      expect(await composite.onMachineStart({ test: 'data' })).toEqual({ test: 'data' })
    })

    it('should handle mixed success and failure in error recovery', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onError.mockRejectedValue(new Error('Error handler failed'))
      hook2.onError.mockImplementation(async (state, error, ctx) => 'recovery_state')
      
      const composite = new CompositeHooks([hook1, hook2])
      const result = await composite.onError('error_state', new Error('test'), {})
      
      expect(result).toBe('recovery_state')
    })

    it('should handle onError returning null', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      
      hook1.onError.mockResolvedValue(null)
      hook2.onError.mockResolvedValue('recovery_state')
      
      const composite = new CompositeHooks([hook1, hook2])
      const result = await composite.onError('error_state', new Error('test'), {})
      
      expect(result).toBe('recovery_state')
    }, 5000)
  })

  describe('Performance and Load Testing', () => {
    it('should handle many hooks efficiently', async () => {
      const hooks = Array.from({ length: 100 }, () => createMockHooks())
      
      hooks.forEach((hook, index) => {
        hook.onMachineStart.mockImplementation(async (ctx) => ({ 
          ...ctx, 
          processed_by: index 
        }))
      })
      
      const composite = new CompositeHooks(hooks)
      const start = Date.now()
      const result = await composite.onMachineStart({ test: 'data' })
      const duration = Date.now() - start
      
      expect(result.processed_by).toBe(99) // Last hook
      expect(duration).toBeLessThan(1000) // Should complete within 1 second
    })

    it('should handle concurrent hook executions', async () => {
      const hook1 = createMockHooks()
      const hook2 = createMockHooks()
      const hook3 = createMockHooks()
      
      let hook1Complete = false
      let hook2Complete = false
      let hook3Complete = false
      
      hook1.onMachineStart.mockImplementation(async (ctx) => {
        await new Promise(resolve => setTimeout(resolve, 100))
        hook1Complete = true
        return { ...ctx, hook1: true }
      })
      
      hook2.onMachineStart.mockImplementation(async (ctx) => {
        await new Promise(resolve => setTimeout(resolve, 50))
        hook2Complete = true
        return { ...ctx, hook2: true }
      })
      
      hook3.onMachineStart.mockImplementation(async (ctx) => {
        hook3Complete = true
        return { ...ctx, hook3: true }
      })
      
      const composite = new CompositeHooks([hook1, hook2, hook3])
      const result = await composite.onMachineStart({ test: 'data' })
      
      expect(result.hook1).toBe(true)
      expect(result.hook2).toBe(true)
      expect(result.hook3).toBe(true)
      expect(hook3Complete).toBe(true)
    })
  })

  describe('Integration Scenarios', () => {
    it('should combine WebhookHooks with custom hooks', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true })
      
      const webhookHook = new WebhookHooks('https://example.com/webhook')
      const customHook = {
        onMachineStart: vi.fn().mockImplementation(async (ctx) => ({ 
          ...ctx, 
          custom_processed: true 
        })),
        onStateEnter: vi.fn().mockImplementation(async (state, ctx) => ({ 
          ...ctx, 
          state_logged: state 
        }))
      }
      
      const composite = new CompositeHooks([webhookHook, customHook])
      
      const context = { user: 'test', session: 'abc123' }
      const result = await composite.onMachineStart(context)
      
      expect(customHook.onMachineStart).toHaveBeenCalledWith(context)
      expect(result.custom_processed).toBe(true)
      expect(fetch).toHaveBeenCalled() // Webhook should be called
    })

    it('should handle real-world logging and metrics scenario', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true })
      
      const loggingHook = {
        onStateEnter: vi.fn().mockImplementation(async (state, ctx) => {
          console.log(`Entering state: ${state}`)
          return { ...ctx, log_time: Date.now() }
        }),
        onStateExit: vi.fn().mockImplementation(async (state, ctx, output) => {
          console.log(`Exiting state: ${state}`)
          return { ...output, exit_time: Date.now() }
        })
      }
      
      const metricsHook = {
        onStateEnter: vi.fn().mockImplementation(async (state, ctx) => {
          // Record metrics
          return { ...ctx, metrics: { state, timestamp: Date.now() } }
        }),
        onMachineEnd: vi.fn().mockImplementation(async (ctx, output) => {
          // Calculate total execution time
          return { ...output, metrics_collected: true }
        })
      }
      
      const webhookHook = new WebhookHooks('https://metrics.example.com')
      
      const composite = new CompositeHooks([loggingHook, metricsHook, webhookHook])
      
      const context = { workflow: 'test' }
      const result = await composite.onStateEnter('processing', context)
      
      expect(result.log_time).toBeDefined()
      expect(result.metrics).toBeDefined()
      expect(fetch).toHaveBeenCalledTimes(1) // Webhook called
    })
  })
})
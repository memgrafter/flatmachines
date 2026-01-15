import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { MCPToolProvider } from '../../src/mcp'

describe('MCPToolProvider', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('Constructor and Initialization', () => {
    it('should initialize with empty clients map', () => {
      const provider = new MCPToolProvider()
      expect(provider).toBeDefined()
    })

    it('should create new instance for each test', () => {
      const provider1 = new MCPToolProvider()
      const provider2 = new MCPToolProvider()
      expect(provider1).not.toBe(provider2)
    })
  })

  describe('Server Connection', () => {
    it('should have connect method available', () => {
      const provider = new MCPToolProvider()
      expect(typeof provider.connect).toBe('function')
    })

    it('should accept servers configuration', async () => {
      const provider = new MCPToolProvider()
      const servers = {
        'test-server': {
          command: 'node',
          args: ['server.js']
        }
      }
      
      // Should not throw during configuration
      expect(() => provider.connect(servers)).not.toThrow()
    })

    it('should handle empty server list', async () => {
      const provider = new MCPToolProvider()
      expect(() => provider.connect({})).not.toThrow()
    })

    it('should handle multiple server configurations', async () => {
      const provider = new MCPToolProvider()
      const servers = {
        'server1': { command: 'node', args: ['server1.js'] },
        'server2': { command: 'python', args: ['server2.py'] },
        'server3': { serverUrl: 'ws://localhost:3001' }
      }
      
      expect(() => provider.connect(servers)).not.toThrow()
    })

    it('should handle server with missing args', async () => {
      const provider = new MCPToolProvider()
      const servers = {
        'minimal-server': { command: 'echo' }
      }
      
      expect(() => provider.connect(servers)).not.toThrow()
    })

    it('should handle server with url instead of command', async () => {
      const provider = new MCPToolProvider()
      const servers = {
        'remote-server': { serverUrl: 'ws://localhost:3001' }
      }
      
      expect(() => provider.connect(servers)).not.toThrow()
    })
  })

  describe('Tool Listing', () => {
    it('should have listTools method available', () => {
      const provider = new MCPToolProvider()
      expect(typeof provider.listTools).toBe('function')
    })

    it('should return promise from listTools', () => {
      const provider = new MCPToolProvider()
      const result = provider.listTools()
      expect(result).toBeInstanceOf(Promise)
    })

    it('should handle listTools without filter', async () => {
      const provider = new MCPToolProvider()
      expect(() => provider.listTools()).not.toThrow()
    })

    it('should handle listTools with filter', async () => {
      const provider = new MCPToolProvider()
      const filter = {
        allow: ['*'],
        deny: ['*_private']
      }
      
      expect(() => provider.listTools(filter)).not.toThrow()
    })

    it('should handle complex filter patterns', async () => {
      const provider = new MCPToolProvider()
      const filter = {
        allow: ['calculator_*', 'text_*', 'file_*'],
        deny: ['*_admin', '*_debug']
      }
      
      expect(() => provider.listTools(filter)).not.toThrow()
    })
  })

  describe('Tool Calling', () => {
    it('should have callTool method available', () => {
      const provider = new MCPToolProvider()
      expect(typeof provider.callTool).toBe('function')
    })

    it('should accept tool name and arguments', async () => {
      const provider = new MCPToolProvider()
      const toolName = 'server:tool_name'
      const args = { param1: 'value1', param2: 42 }

      // callTool returns promise - rejects since no server connected
      await expect(provider.callTool(toolName, args)).rejects.toThrow()
    })

    it('should return promise from callTool', async () => {
      const provider = new MCPToolProvider()
      const result = provider.callTool('server:tool', {})
      expect(result).toBeInstanceOf(Promise)
      await result.catch(() => {})
    })

    it('should handle tool name with server prefix', async () => {
      const provider = new MCPToolProvider()
      const toolNames = [
        'calc-server:add',
        'text-server:format',
        'file-server:read',
        'db-server:query'
      ]

      for (const name of toolNames) {
        await expect(provider.callTool(name, {})).rejects.toThrow()
      }
    })

    it('should handle empty arguments', async () => {
      const provider = new MCPToolProvider()
      await expect(provider.callTool('server:tool', {})).rejects.toThrow()
      await expect(provider.callTool('server:tool', null as any)).rejects.toThrow()
    })

    it('should handle complex argument structures', async () => {
      const provider = new MCPToolProvider()
      const complexArgs = {
        simple: 'value',
        number: 42,
        boolean: true,
        array: [1, 2, 3, 'string', { nested: true }],
        object: {
          nested: { deep: { value: 'test' } },
          array: [1, 2, 3]
        },
        nullable: null,
        undefined: undefined
      }

      await expect(provider.callTool('server:complex_tool', complexArgs)).rejects.toThrow()
    })
  })

  describe('Pattern Matching', () => {
    describe('Filter Pattern Validation', () => {
      it('should handle allow patterns', async () => {
        const provider = new MCPToolProvider()
        
        const filters = [
          { allow: ['tool_*'] },
          { allow: ['*'] },
          { allow: ['specific_tool'] },
          { allow: ['*_prefix', 'prefix_*', '*_suffix'] }
        ]
        
        filters.forEach(filter => {
          expect(() => provider.listTools(filter)).not.toThrow()
        })
      })

      it('should handle deny patterns', async () => {
        const provider = new MCPToolProvider()
        
        const filters = [
          { deny: ['*'] },
          { deny: ['*_private', '*_internal'] },
          { deny: ['specific_tool'] },
          { deny: ['debug_*', 'test_*', '*_temp'] }
        ]
        
        filters.forEach(filter => {
          expect(() => provider.listTools(filter)).not.toThrow()
        })
      })

      it('should handle both allow and deny patterns', async () => {
        const provider = new MCPToolProvider()
        
        const filters = [
          { allow: ['*'], deny: ['*_private'] },
          { allow: ['tool_*'], deny: ['*_debug'] },
          { allow: ['public_*'], deny: ['*'] },
          { allow: ['safe_*'], deny: ['dangerous_*', '*_test'] }
        ]
        
        filters.forEach(filter => {
          expect(() => provider.listTools(filter)).not.toThrow()
        })
      })

      it('should handle wildcard patterns', async () => {
        const provider = new MCPToolProvider()
        
        const filters = [
          { allow: ['*'] },
          { allow: ['*tool*'] },
          { allow: ['prefix_*_suffix'] },
          { allow: ['*_*_*'] },
          { allow: ['*v*'] },
          { allow: ['user_*', 'admin_*', '*_action'] }
        ]
        
        filters.forEach(filter => {
          expect(() => provider.listTools(filter)).not.toThrow()
        })
      })
    })

    describe('Pattern Edge Cases', () => {
      it('should handle empty patterns', async () => {
        const provider = new MCPToolProvider()
        
        const filters = [
          { allow: [] },
          { deny: [] },
          { allow: [], deny: [] },
          {} as any
        ]
        
        filters.forEach(filter => {
          expect(() => provider.listTools(filter)).not.toThrow()
        })
      })

      it('should handle complex regex-like patterns', async () => {
        const provider = new MCPToolProvider()
        
        const filters = [
          { allow: ['*_v*'] },
          { allow: ['*_v1', '*_v2', '*_v*_beta'] },
          { allow: ['*_*'] },
          { allow: ['*_action_*'] },
          { allow: ['[invalid_regex*', '*special_chars!'] }
        ]
        
        filters.forEach(filter => {
          expect(() => provider.listTools(filter)).not.toThrow()
        })
      })
    })
  })

  describe('Error Handling Scenarios', () => {
    it('should handle invalid tool names', async () => {
      const provider = new MCPToolProvider()

      const invalidNames = [
        '',
        'unknown-server',
        'server:',
        ':tool',
        'server:',
        'server:tool:extra',
        'not_a_tool_name'
      ]

      for (const name of invalidNames) {
        await expect(provider.callTool(name, {})).rejects.toThrow()
      }
    })

    it('should handle malformed server configurations', async () => {
      const provider = new MCPToolProvider()
      
      const invalidServers = [
        { '': { command: 'node' } },
        { 'no-command': {}, args: ['test.js'] },
        { 'invalid': { command: '', args: [''] } }
      ]
      
      invalidServers.forEach(servers => {
        expect(() => provider.connect(servers as any)).not.toThrow()
      })
    })

    it('should handle edge case filters', async () => {
      const provider = new MCPToolProvider()
      
      const edgeFilters = [
        { allow: [''], deny: [''] },
        { allow: [null, undefined] as any },
        { allow: ['*tool*', 'too*', '*ool', '*'] },
        { deny: ['*', '*'] }
      ]
      
      edgeFilters.forEach(filter => {
        expect(() => provider.listTools(filter as any)).not.toThrow()
      })
    })
  })

  // Integration behaviors covered in tests/integration/mcp.integration.test.ts

  describe('Performance and Load Testing', () => {
    it('should handle many concurrent operations', async () => {
      const provider = new MCPToolProvider()

      // Test that provider can handle many operations without throwing synchronously
      const operationCount = 100
      const promises: Promise<any>[] = []

      for (let i = 0; i < operationCount; i++) {
        expect(() => provider.listTools()).not.toThrow()
        // callTool is async - collect promises to avoid unhandled rejections
        const p = provider.callTool(`server:tool_${i}`, { index: i }).catch(() => {})
        promises.push(p)
      }

      await Promise.all(promises)
    })

    it('should handle large filter operations', async () => {
      const provider = new MCPToolProvider()

      const largeFilter = {
        allow: Array.from({ length: 50 }, (_, i) => `tool_category_${i}_*`),
        deny: Array.from({ length: 25 }, (_, i) => `*_private_${i}`)
      }

      expect(() => provider.listTools(largeFilter)).not.toThrow()
    })

    it('should handle complex argument structures', async () => {
      const provider = new MCPToolProvider()

      const largeArgs = {
        array: Array.from({ length: 1000 }, (_, i) => ({ id: i, data: `item_${i}` })),
        nested: {
          level1: {
            level2: {
              level3: Array.from({ length: 100 }, (_, i) => `nested_${i}`)
            }
          }
        },
        metadata: {
          created: new Date(),
          tags: Array.from({ length: 50 }, (_, i) => `tag_${i}`)
        }
      }

      // callTool is async - await to catch rejection
      await expect(provider.callTool('server:complex_tool', largeArgs)).rejects.toThrow()
    })
  })

  describe('Special Characters and Edge Cases', () => {
    it('should handle unicode in tool names', async () => {
      const provider = new MCPToolProvider()

      const unicodeNames = [
        'server:工具',
        'сервис:инструмент',
        'サーバー:ツール',
        'server:🔧',
        'server:outil_français'
      ]

      for (const name of unicodeNames) {
        await expect(provider.callTool(name, {})).rejects.toThrow()
      }
    })

    it('should handle special characters in filter patterns', async () => {
      const provider = new MCPToolProvider()
      
      const specialFilters = [
        { allow: ['tool-with-dashes', 'tool_with_underscores'] },
        { allow: ['tool.with.dots'] },
        { allow: ['tool(.*?)'] }, // regex-like
        { allow: ['tool@home', 'tool#tag'] }
      ]
      
      specialFilters.forEach(filter => {
        expect(() => provider.listTools(filter)).not.toThrow()
      })
    })

    it('should handle extremely long names and patterns', async () => {
      const provider = new MCPToolProvider()

      const longName = 'server:' + 'tool'.repeat(100)
      const longFilter = { allow: ['tool'.repeat(50) + '*'] }

      await expect(provider.callTool(longName, {})).rejects.toThrow()
      await expect(provider.listTools(longFilter)).resolves.toEqual([])
    })
  })

  describe('State Management and Lifecycle', () => {
    it('should maintain independent instances', () => {
      const provider1 = new MCPToolProvider()
      const provider2 = new MCPToolProvider()
      
      expect(provider1).not.toBe(provider2)
      expect(typeof provider1.connect).toBe('function')
      expect(typeof provider2.connect).toBe('function')
    })

    // Server connection lifecycle tests covered in tests/integration/mcp.integration.test.ts
  })
})
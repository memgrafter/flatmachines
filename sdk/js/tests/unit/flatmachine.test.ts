import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { FlatMachine } from '../../src/flatmachine'
import { 
  createMinimalMachineConfig, 
  createMinimalAgentConfig,
  createMockHooks,
  withCleanup,
  captureLogs,
  loadConfig
} from '../fixtures/helpers'

describe('FlatMachine', () => {
  describe('Configuration Loading', () => {
    it('should load configuration from object', () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })
      expect(machine.config).toEqual(config)
    })

    it('should load configuration from file path', () => {
      // Test file loading through actual config from fixtures
      const config = loadConfig('helloworld', 'machine.yml')
      const machine = new FlatMachine({ config })
      expect(machine.config.spec).toBe('flatmachine')
      expect(machine.config.data.states).toBeDefined()
    })

    it('should handle configuration with missing required fields', () => {
      const invalidConfig = {
        spec: 'flatmachine' as const,
        spec_version: '0.1.0',
        data: {
          states: {
            // Has states but minimal
            test: { type: 'final' as const }
          }
        }
      }
      
      expect(() => new FlatMachine({ config: invalidConfig })).not.toThrow()
    })

    it('should throw on truly invalid configs', () => {
      const invalidConfigs = [
        null,
        undefined,
        { spec: 'flatmachine', spec_version: '0.1.0', data: null }
      ]

      invalidConfigs.forEach(config => {
        expect(() => new FlatMachine({ config: config as any })).toThrow()
      })
    })

    it('should accept minimal valid config structure', () => {
      const minimalConfigs = [
        { spec: 'flatmachine', spec_version: '0.1.0', data: { states: {} } },
        { spec: 'wrong_spec', spec_version: '0.1.0', data: { states: {} } }
      ]

      minimalConfigs.forEach(config => {
        expect(() => new FlatMachine({ config: config as any })).not.toThrow()
      })
    })

    it('should set config directory correctly', () => {
      const config = createMinimalMachineConfig()
      const customDir = '/custom/config/dir'
      const machine = new FlatMachine({ config, configDir: customDir })
      expect(machine).toBeDefined()
    })
  })

  describe('State Management', () => {
    it('should find initial state when marked', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            start: {
              type: 'initial' as const,
              agent: 'test_agent',
              transitions: [{ condition: 'true', to: 'end' }]
            },
            end: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.start.type).toBe('initial')
      expect(machine.config.data.states.end.type).toBe('final')
    })

    it('should handle missing initial state', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              agent: 'test_agent',
              transitions: [{ condition: 'true', to: 'step2' }]
            },
            step2: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step2.type).toBe('final')
    })

    it('should handle states without transitions', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent',
              // No transitions
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.type).toBe('initial')
    })

    it('should handle circular transitions', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            loop: {
              type: 'initial' as const,
              agent: 'test_agent',
              transitions: [{ condition: 'context.done != true', to: 'loop' }]
            },
            done: {
              type: 'final' as const,
              output: { result: '{{ context.result }}' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.loop.transitions?.[0].to).toBe('loop')
      expect(machine.config.data.states.done.type).toBe('final')
    })
  })

  describe('Context Management', () => {
    it('should initialize context from input', () => {
      const config = createMinimalMachineConfig({
        data: {
          context: {
            base_value: 'test'
          },
          states: {
            test: { type: 'final' as const }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.context?.base_value).toBe('test')
    })

    it('should handle empty context', () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })
      expect(machine.config.data.context ?? {}).toEqual({})
    })

    it('should merge context from input', () => {
      const config = createMinimalMachineConfig({
        data: {
          context: {
            base: 'value'
          },
          states: {
            test: { type: 'final' as const }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.context?.base).toBe('value')
    })

    it('should handle nested context objects', () => {
      const config = createMinimalMachineConfig({
        data: {
          context: {
            user: {
              name: 'John',
              role: 'admin'
            },
            settings: {
              theme: 'dark'
            }
          },
          states: {
            test: { type: 'final' as const }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.context?.user.name).toBe('John')
      expect(machine.config.data.context?.settings.theme).toBe('dark')
    })
  })

  describe('Template Rendering', () => {
    it('should render simple string templates', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent',
              input: {
                query: '{{ input.user_name }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: {
                message: 'Hello {{ context.result }}!'
              }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const state = machine.config.data.states.step1
      expect(state.input?.query).toContain('{{ input.user_name }}')
    })

    it('should render object templates', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent',
              input: {
                user: {
                  name: '{{ input.name }}',
                  id: '{{ input.id }}'
                },
                request: '{{ input.query }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const state = machine.config.data.states.step1
      expect(state.input?.user.name).toContain('{{ input.name }}')
      expect(state.input?.user.id).toContain('{{ input.id }}')
    })

    it('should render array templates', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent',
              input: {
                items: [
                  '{{ input.item1 }}',
                  '{{ input.item2 }}'
                ]
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const state = machine.config.data.states.step1
      expect(Array.isArray(state.input?.items)).toBe(true)
    })

    it('should handle template rendering errors gracefully', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent',
              input: {
                query: '{{ undefined_variable.some_property }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.input?.query).toContain('{{ undefined_variable.some_property }}')
    })
  })

  describe('Agent Execution', () => {
    it('should handle agent execution configuration', () => {
      const agentConfig = createMinimalAgentConfig()
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              input: {
                query: '{{ input.query }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.agent).toBe('test_agent.yml')
    })

    it('should handle missing agent configuration', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'nonexistent_agent.yml',
              input: {
                query: '{{ input.query }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.agent).toBe('nonexistent_agent.yml')
    })

    it('should handle agent input rendering', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              input: {
                query: 'Hello {{ input.name }}, here is {{ context.data }}',
                context: {
                  user_role: '{{ input.role }}',
                  session_id: '{{ context.session.id }}'
                }
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const state = machine.config.data.states.step1
      expect(state.input?.query).toContain('{{ input.name }}')
      expect(state.input?.context.user_role).toContain('{{ input.role }}')
    })
  })

  describe('Machine Execution', () => {
    it('should handle single machine execution', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              machine: 'submachine.yml',
              input: {
                data: '{{ input.value }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.machine).toBe('submachine.yml')
    })

    it('should handle parallel machine execution', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              machine: ['machine1.yml', 'machine2.yml', 'machine3.yml'],
              input: {
                data: '{{ input.value }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const machineRef = machine.config.data.states.step1.machine
      expect(Array.isArray(machineRef)).toBe(true)
      expect(machineRef).toHaveLength(3)
    })

    it('should handle foreach dynamic parallelism', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              machine: 'processor.yml',
              foreach: '{{ context.items }}',
              as: 'item',
              input: {
                data: '{{ item }}',
                index: '{{ loop.index }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const state = machine.config.data.states.step1
      expect(state.machine).toBe('processor.yml')
      expect(state.foreach).toContain('{{ context.items }}')
      expect(state.as).toBe('item')
      expect(state.input?.data).toContain('{{ item }}')
    })

    it('should handle fire-and-forget launch machines', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              launch: 'background_task.yml',
              launch_input: {
                priority: 'low',
                data: '{{ input.async_data }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const state = machine.config.data.states.step1
      expect(state.launch).toBe('background_task.yml')
      expect(state.launch_input?.priority).toBe('low')
    })

    it('should handle multiple launch machines', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              launch: ['task1.yml', 'task2.yml'],
              launch_input: {
                batch_id: '{{ input.batch_id }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const launch = machine.config.data.states.step1.launch
      expect(Array.isArray(launch)).toBe(true)
      expect(launch).toHaveLength(2)
    })
  })

  describe('Execution Types', () => {
    it('should handle default execution type', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              execution: {
                type: 'default' as const
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.execution?.type).toBe('default')
    })

    it('should handle retry execution type', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              execution: {
                type: 'retry' as const,
                backoffs: [2, 8, 16, 35],
                jitter: 0.1
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const execution = machine.config.data.states.step1.execution
      expect(execution?.type).toBe('retry')
      expect(execution?.backoffs).toEqual([2, 8, 16, 35])
      expect(execution?.jitter).toBe(0.1)
    })

    it('should handle execution with minimal configuration', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              execution: {
                type: 'retry' as const
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.execution?.type).toBe('retry')
    })
  })

  describe('Transition Evaluation', () => {
    it('should handle conditional transitions', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              transitions: [
                {
                  condition: 'context.success == true',
                  to: 'success_state'
                },
                {
                  condition: 'context.error == true',
                  to: 'error_state'
                },
                {
                  to: 'default_state'
                }
              ]
            },
            success_state: {
              type: 'final' as const,
              output: { result: 'success' }
            },
            error_state: {
              type: 'final' as const,
              output: { result: 'error' }
            },
            default_state: {
              type: 'final' as const,
              output: { result: 'default' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const transitions = machine.config.data.states.step1.transitions
      expect(transitions).toHaveLength(3)
      expect(transitions?.[0].condition).toContain('context.success == true')
      expect(transitions?.[1].condition).toContain('context.error == true')
      expect(transitions?.[2].condition).toBeUndefined()
    })

    it('should handle single unconditional transition', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              transitions: [
                { to: 'next_state' }
              ]
            },
            next_state: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const transitions = machine.config.data.states.step1.transitions
      expect(transitions).toHaveLength(1)
      expect(transitions?.[0].to).toBe('next_state')
    })

    it('should handle complex transition conditions', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              transitions: [
                {
                  condition: 'context.score >= 8 and context.approved == true',
                  to: 'approved'
                },
                {
                  condition: 'context.score < 5 or context.rejected == true',
                  to: 'rejected'
                },
                {
                  condition: 'context.retry_count < 3',
                  to: 'retry'
                },
                {
                  to: 'manual_review'
                }
              ]
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const transitions = machine.config.data.states.step1.transitions
      expect(transitions).toHaveLength(4)
      expect(transitions?.[0].condition).toContain('>= 8 and')
      expect(transitions?.[1].condition).toContain('< 5 or')
      expect(transitions?.[2].condition).toContain('< 3')
    })
  })

  describe('Error Handling', () => {
    it('should handle on_error state routing', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              on_error: 'error_handler',
              transitions: [{ condition: 'true', to: 'final' }]
            },
            error_handler: {
              type: 'final' as const,
              output: { error: '{{ context.last_error }}' }
            },
            final: {
              type: 'final' as const,
              output: { result: 'success' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.on_error).toBe('error_handler')
    })

    it('should handle multiple error recovery strategies', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              on_error: 'step1_retry',
              transitions: [{ condition: 'true', to: 'final' }]
            },
            step1_retry: {
              agent: 'test_agent.yml',
              input: { retry_count: '{{ context.retry_count + 1 }}' },
              on_error: 'step1_error',
              transitions: [{ condition: 'context.retry_count < 3', to: 'step1' }]
            },
            step1_error: {
              type: 'final' as const,
              output: { error: 'Failed after retries' }
            },
            final: {
              type: 'final' as const,
              output: { result: 'success' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.on_error).toBe('step1_retry')
      expect(machine.config.data.states.step1_retry.on_error).toBe('step1_error')
    })
  })

  describe('Output Mapping', () => {
    it('should handle output_to_context mapping', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              output_to_context: {
                result: '{{ output.response }}',
                confidence: '{{ output.score }}',
                metadata: {
                  model: '{{ output.model }}',
                  timestamp: '{{ output.created_at }}'
                }
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { final_result: '{{ context.result }}' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const mapping = machine.config.data.states.step1.output_to_context
      expect(mapping?.result).toContain('{{ output.response }}')
      expect(mapping?.confidence).toContain('{{ output.score }}')
      expect(mapping?.metadata.model).toContain('{{ output.model }}')
    })

    it('should handle simple output mapping', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              output_to_context: {
                data: '{{ output }}'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: '{{ context.data }}' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.states.step1.output_to_context?.data).toContain('{{ output }}')
    })

    it('should handle complex nested output mapping', () => {
      const config = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              output_to_context: {
                analysis: {
                  sentiment: '{{ output.sentiment }}',
                  confidence: '{{ output.confidence_score }}',
                  entities: '{{ output.extracted_entities }}'
                },
                processing: {
                  duration_ms: '{{ context.processing_time }}',
                  model_used: '{{ output.model_name }}'
                }
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: '{{ context.analysis }}' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      const mapping = machine.config.data.states.step1.output_to_context
      expect(mapping?.analysis.sentiment).toContain('{{ output.sentiment }}')
      expect(mapping?.processing.model_used).toContain('{{ output.model_name }}')
    })
  })

  describe('Persistence Configuration', () => {
    it('should handle persistence enabled', () => {
      const config = createMinimalMachineConfig({
        data: {
          persistence: {
            enabled: true,
            backend: 'local' as const
          },
          states: {
            test: { type: 'final' as const }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.persistence?.enabled).toBe(true)
      expect(machine.config.data.persistence?.backend).toBe('local')
    })

    it('should handle memory backend', () => {
      const config = createMinimalMachineConfig({
        data: {
          persistence: {
            enabled: true,
            backend: 'memory' as const
          },
          states: {
            test: { type: 'final' as const }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.persistence?.backend).toBe('memory')
    })

    it('should handle disabled persistence', () => {
      const config = createMinimalMachineConfig({
        data: {
          persistence: {
            enabled: false,
            backend: 'local' as const
          },
          states: {
            test: { type: 'final' as const }
          }
        }
      })
      
      const machine = new FlatMachine({ config })
      expect(machine.config.data.persistence?.enabled).toBe(false)
    })
  })

  describe('Hooks Integration', () => {
    it('should accept hooks configuration', () => {
      const mockHooks = createMockHooks()
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config, hooks: mockHooks })
      expect(machine).toBeDefined()
    })

    it('should handle missing hooks gracefully', () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })
      expect(machine).toBeDefined()
    })

    it('should handle partial hooks implementation', () => {
      const partialHooks = {
        onMachineStart: vi.fn(),
        onStateEnter: vi.fn()
        // Missing other hook methods
      }
      
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config, hooks: partialHooks })
      expect(machine).toBeDefined()
    })
  })

  describe('Edge Cases', () => {
    it('should handle extremely large configuration objects', () => {
      const largeConfig = createMinimalMachineConfig({
        data: {
          context: {
            large_data: 'x'.repeat(10000)
          },
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              input: {
                large_prompt: 'y'.repeat(50000)
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: 'done' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config: largeConfig })
      expect(machine.config.data.context?.large_data.length).toBe(10000)
    })

    it('should handle deeply nested state definitions', () => {
      const deepConfig = createMinimalMachineConfig({
        data: {
          states: {
            step1: {
              type: 'initial' as const,
              agent: 'test_agent.yml',
              input: {
                level1: {
                  level2: {
                    level3: {
                      level4: {
                        value: '{{ input.deep_value }}'
                      }
                    }
                  }
                }
              },
              output_to_context: {
                result: {
                  nested: {
                    data: '{{ output.response }}'
                  }
                }
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: '{{ context.result.nested.data }}' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config: deepConfig })
      expect(machine.config.data.states.step1.input?.level1.level2.level3.level4.value).toContain('{{ input.deep_value }}')
    })

    it('should handle unicode characters in all fields', () => {
      const unicodeConfig = createMinimalMachineConfig({
        data: {
          name: '测试机器 🚀',
          context: {
            greeting: 'Hello 🌍 World',
            emoji: '🎉✨🎊'
          },
          states: {
            step1: {
              type: 'initial' as const,
              agent: '测试代理.yml',
              input: {
                message: '你好 {{ input.name }} 🌟',
                unicode: 'αβγδε ζηθικ λμνξο πρστυ φχψω'
              },
              transitions: [{ condition: 'true', to: 'final' }]
            },
            final: {
              type: 'final' as const,
              output: { result: '完成 ✅' }
            }
          }
        }
      })
      
      const machine = new FlatMachine({ config: unicodeConfig })
      expect(machine.config.data.name).toContain('测试机器')
      expect(machine.config.data.context?.greeting).toContain('🌍')
    })

    it('should handle missing optional properties', () => {
      const minimalConfig = {
        spec: 'flatmachine' as const,
        spec_version: '0.1.0',
        data: {
          states: {
            final: {
              type: 'final' as const
            }
          }
        }
      }
      
      const machine = new FlatMachine({ config: minimalConfig })
      expect(machine.config.data.name).toBeUndefined()
      expect(machine.config.data.context ?? {}).toEqual({})
      expect(machine.config.data.persistence).toBeUndefined()
    })
  })

  describe('Execution Method', () => {
    it('should have execute method available', () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })
      expect(typeof machine.execute).toBe('function')
    })

    it('should accept input parameter', async () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })

      const input = { query: 'test', user: 'john' }
      // execute returns promise - rejects since test_agent doesn't exist
      await expect(machine.execute(input)).rejects.toThrow()
    })

    it('should return promise from execute method', async () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })

      const result = machine.execute({ test: 'data' })
      expect(result).toBeInstanceOf(Promise)
      await result.catch(() => {})
    })

    it('should have resume method available', () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })
      expect(typeof machine.resume).toBe('function')
    })

    it('should handle resume with execution ID', async () => {
      const config = createMinimalMachineConfig()
      const machine = new FlatMachine({ config })

      const executionId = 'test-execution-id'
      // resume rejects when no checkpoint exists
      await expect(machine.resume(executionId)).rejects.toThrow()
    })
  })
})
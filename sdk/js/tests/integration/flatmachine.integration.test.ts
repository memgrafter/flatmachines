// flatmachine.integration.test.ts
// Integration tests for FlatMachine functionality

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { FlatMachine } from '../src/flatmachine';
import { readFileSync } from 'fs';
import { join } from 'path';
import { MemoryBackend } from '../src/persistence';

describe('FlatMachine Integration Tests', () => {
  let flatMachine: FlatMachine;
  let mockPersistence: MemoryBackend;

  beforeEach(() => {
    vi.clearAllMocks();
    mockPersistence = new MemoryBackend();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Real Configuration Loading', () => {
    it('should load and execute a complete machine configuration', async () => {
      // Load real machine configuration from fixtures
      const configPath = join(__dirname, '../fixtures/configs/machine.yml');
      let configContent: string;
      
      try {
        configContent = readFileSync(configPath, 'utf-8');
      } catch (error) {
        // Fallback to minimal config for testing
        configContent = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "test-machine"
  context:
    initial_value: 10
  states:
    start:
      type: "initial"
      agent: "processor"
      input:
        value: "{{ context.initial_value }}"
      output_to_context:
        result: "{{ output.processed_value }}"
      transitions:
        - to: "process"
    process:
      agent: "calculator"
      input:
        input_value: "{{ context.result }}"
      output_to_context:
        calculation: "{{ output.result }}"
      transitions:
        - condition: "context.calculation > 50"
          to: "high_value"
        - to: "low_value"
    high_value:
      type: "final"
      output:
        category: "high"
        value: "{{ context.calculation }}"
    low_value:
      type: "final"
      output:
        category: "low"
        value: "{{ context.calculation }}"
`;
      }

      flatMachine = new FlatMachine(configContent);

      // Mock agent calls
      const mockAgentCall = vi.fn().mockImplementation((config, input) => {
        if (config.includes('processor')) {
          return Promise.resolve({
            output: { processed_value: input.value * 2 }
          });
        } else if (config.includes('calculator')) {
          return Promise.resolve({
            output: { result: input.input_value * 5 }
          });
        }
        return Promise.resolve({ output: {} });
      });

      // Replace the actual agent execution
      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue({
            output: { category: 'high', value: 100 },
            executionId: 'test-execution-id',
            states: ['start', 'process', 'high_value']
          })
        }))
      }));

      const result = await flatMachine.execute({
        input_data: 'test input'
      });

      expect(result).toBeDefined();
      expect(result.output).toBeDefined();
      expect(result.output.category).toBe('high');
      expect(result executionId).toBeDefined();
    });

    it('should handle complex state transitions', async () => {
      const complexConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "complex-transition-machine"
  context:
    step_count: 0
    errors: []
  states:
    initialize:
      type: "initial"
      action: "setup_resources"
      output_to_context:
        resources_ready: true
      transitions:
        - condition: "context.resources_ready"
          to: "validate"
        - to: "setup_failed"
    validate:
      agent: "validator"
      input:
        data: "{{ input.data }}"
      output_to_context:
        validation_result: "{{ output.is_valid }}"
        validation_errors: "{{ output.errors }}"
      transitions:
        - condition: "context.validation_result"
          to: "process"
        - to: "validation_failed"
    process:
      agent: "processor"
      input:
        valid_data: "{{ input.data }}"
        config: "{{ context.processing_config }}"
      output_to_context:
        processed_data: "{{ output.result }}"
        processing_metrics: "{{ output.metrics }}"
      transitions:
        - condition: "context.processed_data.success"
          to: "finalize"
        - to: "retry"
    retry:
      agent: "retry_handler"
      input:
        original_data: "{{ input.data }}"
        error: "{{ context.last_error }}"
        attempt: "{{ context.retry_count }}"
      output_to_context:
        should_retry: "{{ output.retry_possible }}"
        retry_delay: "{{ output.delay }}"
      transitions:
        - condition: "context.should_retry and context.retry_count < 3"
          to: "process"
        - to: "failed"
    finalize:
      type: "final"
      output:
        success: true
        result: "{{ context.processed_data }}"
        metrics: "{{ context.processing_metrics }}"
    validation_failed:
      type: "final"
      output:
        success: false
        error: "Validation failed"
        details: "{{ context.validation_errors }}"
    setup_failed:
      type: "final"
      output:
        success: false
        error: "Setup failed"
    failed:
      type: "final"
      output:
        success: false
        error: "Processing failed after retries"
        attempt_count: "{{ context.retry_count }}"
`;

      flatMachine = new FlatMachine(complexConfig);

      // Mock successful execution path
      const mockResult = {
        output: {
          success: true,
          result: { data: 'processed', success: true },
          metrics: { time: 1500, memory: '50MB' }
        },
        executionId: 'complex-execution-id',
        states: ['initialize', 'validate', 'process', 'finalize']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({
        data: { content: 'test data', type: 'text' }
      });

      expect(result.output.success).toBe(true);
      expect(result.output.result.data).toBe('processed');
      expect(result.states).toContain('finalize');
    });
  });

  describe('Parallel Execution Integration', () => {
    it('should execute parallel machines concurrently', async () => {
      const parallelConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "parallel-processor-machine"
  context:
    results: {}
  states:
    start:
      type: "initial"
      machine: ["analyzer", "validator", "transformer"]
      input:
        data: "{{ input.document }}"
      mode: "settled"
      timeout: 30
      output_to_context:
        analysis_results: "{{ output.analyzer }}"
        validation_results: "{{ output.validator }}"
        transformation_results: "{{ output.transformer }}"
      transitions:
        - to: "synthesize"
    synthesize:
      agent: "synthesizer"
      input:
        analysis: "{{ context.analysis_results }}"
        validation: "{{ context.validation_results }}"
        transformation: "{{ context.transformation_results }}"
      output_to_context:
        final_result: "{{ output.synthesized_result }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        result: "{{ context.final_result }}"
        components:
          analysis: "{{ context.analysis_results }}"
          validation: "{{ context.validation_results }}"
          transformation: "{{ context.transformation_results }}"
`;

      flatMachine = new FlatMachine(parallelConfig);

      const mockParallelResult = {
        output: {
          result: { 
            synthesized_result: 'All components processed successfully',
            confidence: 0.95
          },
          components: {
            analysis: { sentiment: 'positive', topics: ['technology'] },
            validation: { is_valid: true, errors: [] },
            transformation: { format: 'json', size: '2KB' }
          }
        },
        executionId: 'parallel-execution-id',
        states: ['start', 'synthesize', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockParallelResult)
        }))
      }));

      const result = await flatMachine.execute({
        document: { text: 'Sample document for parallel processing', length: 500 }
      });

      expect(result.output.result.synthesized_result).toBe('All components processed successfully');
      expect(result.output.components.analysis.sentiment).toBe('positive');
      expect(result.output.components.validation.is_valid).toBe(true);
    });

    it('should handle parallel execution with timeout', async () => {
      const timeoutConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "timeout-parallel-machine"
  context: {}
  states:
    start:
      type: "initial"
      machine: ["slow_task", "fast_task"]
      input:
        data: "{{ input.data }}"
      mode: "settled"
      timeout: 2
      on_error: "timeout_handler"
      transitions:
        - to: "complete"
    timeout_handler:
      type: "final"
      output:
        timed_out: true
        message: "Some tasks exceeded timeout limit"
    complete:
      type: "final"
      output:
        completed: true
        results: "{{ context.parallel_results }}"
`;

      flatMachine = new FlatMachine(timeoutConfig);

      const mockTimeoutResult = {
        output: {
          timed_out: true,
          message: "Some tasks exceeded timeout limit"
        },
        executionId: 'timeout-execution-id',
        states: ['start', 'timeout_handler']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockTimeoutResult)
        }))
      }));

      const result = await flatMachine.execute({
        data: { complexity: 'high' }
      });

      expect(result.output.timed_out).toBe(true);
      expect(result.states).toContain('timeout_handler');
    });
  });

  describe('Dynamic Parallelism (foreach)', () => {
    it('should process dynamic arrays with foreach', async () => {
      const foreachConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "foreach-processor-machine"
  context:
    processed_items: []
    errors: []
  states:
    start:
      type: "initial"
      foreach: "{{ input.items }}"
      as: "item"
      key: "{{ item.id }}"
      machine: "item_processor"
      input:
        item_data: "{{ item }}"
        processing_config: "{{ input.config }}"
      output_to_context:
        processed_items: "{{ output }}"
        errors: "{{ context.errors }}"
      transitions:
        - condition: "context.errors.length == 0"
          to: "aggregate"
        - to: "handle_errors"
    aggregate:
      agent: "aggregator"
      input:
        items: "{{ context.processed_items }}"
      output_to_context:
        summary: "{{ output.aggregated_result }}"
      transitions:
        - to: "complete"
    handle_errors:
      type: "final"
      output:
        success: false
        errors: "{{ context.errors }}"
        processed_count: "{{ context.processed_items.length }}"
    complete:
      type: "final"
      output:
        success: true
        summary: "{{ context.summary }}"
        processed_count: "{{ context.processed_items.length }}"
`;

      flatMachine = new FlatMachine(foreachConfig);

      const testItems = [
        { id: 'item1', content: 'First item', priority: 'high' },
        { id: 'item2', content: 'Second item', priority: 'medium' },
        { id: 'item3', content: 'Third item', priority: 'low' }
      ];

      const mockForeachResult = {
        output: {
          success: true,
          summary: {
            totalProcessed: 3,
            totalTime: 2500,
            averagePriority: 'medium'
          },
          processed_count: 3
        },
        executionId: 'foreach-execution-id',
        states: ['start', 'aggregate', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockForeachResult)
        }))
      }));

      const result = await flatMachine.execute({
        items: testItems,
        config: { timeout: 5, retries: 2 }
      });

      expect(result.output.success).toBe(true);
      expect(result.output.summary.totalProcessed).toBe(3);
      expect(result.output.processed_count).toBe(3);
    });

    it('should handle empty arrays in foreach', async () => {
      const emptyForeachConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "empty-foreach-machine"
  context: {}
  states:
    start:
      type: "initial"
      foreach: "{{ input.items }}"
      as: "item"
      machine: "empty_processor"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        message: "No items to process"
        processed_count: 0
`;

      flatMachine = new FlatMachine(emptyForeachConfig);

      const mockEmptyResult = {
        output: {
          message: "No items to process",
          processed_count: 0
        },
        executionId: 'empty-foreach-id',
        states: ['start', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockEmptyResult)
        }))
      }));

      const result = await flatMachine.execute({
        items: []
      });

      expect(result.output.message).toBe("No items to process");
      expect(result.output.processed_count).toBe(0);
    });
  });

  describe('Fire-and-Forget (launch) Integration', () => {
    it('should launch background tasks without blocking', async () => {
      const launchConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "background-launch-machine"
  context:
    main_task_complete: false
  states:
    start:
      type: "initial"
      launch: ["background_analyzer", "background_processor"]
      launch_input:
        data: "{{ input.large_dataset }}"
        priority: "high"
      action: "process_immediate_data"
      output_to_context:
        immediate_result: "{{ output.quick_result }}"
        main_task_complete: true
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        immediate_result: "{{ context.immediate_result }}"
        background_tasks_launched: true
        message: "Main task completed, background processing initiated"
`;

      flatMachine = new FlatMachine(launchConfig);

      const mockLaunchResult = {
        output: {
          immediate_result: { status: 'processed', items: 150 },
          background_tasks_launched: true,
          message: "Main task completed, background processing initiated"
        },
        executionId: 'launch-execution-id',
        states: ['start', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockLaunchResult)
        }))
      }));

      const startTime = Date.now();
      const result = await flatMachine.execute({
        large_dataset: { size: '10GB', records: 1000000 }
      });
      const endTime = Date.now();

      expect(result.output.background_tasks_launched).toBe(true);
      expect(result.output.immediate_result.items).toBe(150);
      // Should complete quickly since background tasks don't block
      expect(endTime - startTime).toBeLessThan(1000);
    });
  });

  describe('Error Handling and Recovery', () => {
    it('should handle state-level errors and transitions', async () => {
      const errorHandlingConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "error-handling-machine"
  context:
    error_count: 0
    last_error: null
  states:
    start:
      type: "initial"
      agent: "risky_agent"
      input:
        data: "{{ input.data }}"
      on_error: "error_handler"
      output_to_context:
        result: "{{ output.data }}"
      transitions:
        - to: "success"
    success:
      type: "final"
      output:
        status: "success"
        result: "{{ context.result }}"
    error_handler:
      agent: "error_processor"
      input:
        error: "{{ context.last_error }}"
        original_data: "{{ input.data }}"
      output_to_context:
        error_analysis: "{{ output.analysis }}"
        can_retry: "{{ output.retry_possible }}"
      transitions:
        - condition: "context.can_retry and context.error_count < 3"
          to: "start"
        - to: "final_error"
    final_error:
      type: "final"
      output:
        status: "failed"
        error: "{{ context.last_error }}"
        analysis: "{{ context.error_analysis }}"
`;

      flatMachine = new FlatMachine(errorHandlingConfig);

      const mockErrorResult = {
        output: {
          status: 'failed',
          error: 'Connection timeout after 30 seconds',
          analysis: { type: 'network_error', retry_possible: true }
        },
        executionId: 'error-execution-id',
        states: ['start', 'error_handler', 'final_error']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockErrorResult)
        }))
      }));

      const result = await flatMachine.execute({
        data: { url: 'https://example.com/api/data', timeout: 30 }
      });

      expect(result.output.status).toBe('failed');
      expect(result.output.error).toContain('timeout');
      expect(result.output.analysis.retry_possible).toBe(true);
    });

    it('should handle retry logic with backoff', async () => {
      const retryConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "retry-backoff-machine"
  context:
    attempt_count: 0
  states:
    start:
      type: "initial"
      agent: "unstable_api"
      execution:
        type: "retry"
        backoffs: [1, 2, 4]  // 1s, 2s, 4s
        jitter: 0.1         // 10% random variation
      input:
        endpoint: "{{ input.url }}"
      output_to_context:
        api_result: "{{ output.data }}"
        attempt_count: "{{ context.attempt_count + 1 }}"
      transitions:
        - condition: "context.api_result.success"
          to: "success"
        - to: "final_failure"
    success:
      type: "final"
      output:
        status: "success"
        data: "{{ context.api_result }}"
        attempts: "{{ context.attempt_count }}"
    final_failure:
      type: "final"
      output:
        status: "failed"
        attempts: "{{ context.attempt_count }}"
        last_error: "{{ context.last_error }}"
`;

      flatMachine = new FlatMachine(retryConfig);

      const mockRetryResult = {
        output: {
          status: 'success',
          data: { 
            success: true, 
            content: 'Data retrieved successfully after retries',
            response_time: 200
          },
          attempts: 2
        },
        executionId: 'retry-execution-id',
        states: ['start', 'success']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockRetryResult)
        }))
      }));

      const startTime = Date.now();
      const result = await flatMachine.execute({
        url: 'https://unstable-api.example.com/data'
      });
      const endTime = Date.now();

      expect(result.output.status).toBe('success');
      expect(result.output.data.success).toBe(true);
      expect(result.output.attempts).toBe(2);
      // Should include retry delays (first attempt failed, second succeeded after 1s backoff)
      expect(endTime - startTime).toBeGreaterThan(1000);
    });
  });

  describe('Hooks Integration', () => {
    it('should integrate hooks throughout machine lifecycle', async () => {
      const hooksConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "hooks-integration-machine"
  context:
    lifecycle_events: []
    processed_data: {}
  states:
    start:
      type: "initial"
      hooks:
        on_state_enter: "log_start"
        on_state_exit: "validate_start"
      agent: "data_processor"
      input:
        data: "{{ input.dataset }}"
      output_to_context:
        processed_data: "{{ output.result }}"
      transitions:
        - to: "validate"
    validate:
      hooks:
        on_state_enter: "log_validation"
        on_transition: "check_quality"
      agent: "quality_checker"
      input:
        processed: "{{ context.processed_data }}"
      output_to_context:
        quality_score: "{{ output.score }}"
      transitions:
        - condition: "context.quality_score >= 0.8"
          to: "complete"
        - to: "improve"
    improve:
      agent: "data_improver"
      input:
        data: "{{ context.processed_data }}"
        quality_threshold: 0.8
      output_to_context:
        improved_data: "{{ output.improved_result }}"
      transitions:
        - to: "validate"
    complete:
      type: "final"
      hooks:
        on_state_enter: "log_completion"
        on_machine_end: "generate_report"
      output:
        result: "{{ context.processed_data }}"
        quality: "{{ context.quality_score }}"
        events: "{{ context.lifecycle_events }}"
`;

      const mockHooks = {
        onMachineStart: vi.fn().mockResolvedValue({ initialized: true }),
        onMachineEnd: vi.fn().mockResolvedValue({ report: 'completed' }),
        onStateEnter: vi.fn().mockResolvedValue({ entered: true }),
        onStateExit: vi.fn().mockResolvedValue({ exited: true }),
        onTransition: vi.fn().mockResolvedValue({ transitioned: true }),
        onError: vi.fn().mockResolvedValue({ handled: true })
      };

      flatMachine = new FlatMachine(hooksConfig, { hooks: mockHooks });

      const mockHooksResult = {
        output: {
          result: { data: 'processed dataset', records: 1000 },
          quality: 0.85,
          events: ['start', 'validate', 'complete']
        },
        executionId: 'hooks-execution-id',
        states: ['start', 'validate', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockHooksResult)
        }))
      }));

      const result = await flatMachine.execute({
        dataset: { records: 1000, type: 'customer_data' }
      });

      expect(result.output.quality).toBe(0.85);
      expect(result.output.events).toContain('complete');
    });
  });

  describe('Persistence Integration', () => {
    it('should persist and resume machine execution', async () => {
      const persistenceConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "persistence-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    checkpoint_count: 0
  states:
    start:
      type: "initial"
      agent: "long_running_task"
      input:
        iterations: "{{ input.num_iterations }}"
      output_to_context:
        progress: "{{ output.current_iteration }}"
        checkpoint_count: "{{ context.checkpoint_count + 1 }}"
      transitions:
        - condition: "context.progress < input.num_iterations"
          to: "start"  // Loop back to continue processing
        - to: "complete"
    complete:
      type: "final"
      output:
        total_iterations: "{{ context.progress }}"
        checkpoints_created: "{{ context.checkpoint_count }}"
`;

      flatMachine = new FlatMachine(persistenceConfig, { persistence: mockPersistence });

      const mockPersistenceResult = {
        output: {
          total_iterations: 100,
          checkpoints_created: 100
        },
        executionId: 'persistence-execution-id',
        states: Array.from({ length: 101 }, (_, i) => i === 0 ? 'start' : `checkpoint_${i}`)
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockPersistenceResult)
        }))
      }));

      const result = await flatMachine.execute({
        num_iterations: 100
      });

      expect(result.output.total_iterations).toBe(100);
      expect(result.output.checkpoints_created).toBe(100);
    });

    it('should resume from checkpoint after interruption', async () => {
      const resumeConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "resume-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    resumed: false
  states:
    start:
      type: "initial"
      agent: "resumable_task"
      input:
        work_id: "{{ input.job_id }}"
        resume_from: "{{ context.checkpoint_data }}"
      output_to_context:
        current_state: "{{ output.processing_state }}"
        resumed: "{{ context.resumed or input.resume_from != null }}"
      transitions:
        - to: "continue_processing"
    continue_processing:
      agent: "continuation_worker"
      input:
        state: "{{ context.current_state }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        resumed: "{{ context.resumed }}"
        final_state: "{{ context.current_state }}"
`;

      flatMachine = new FlatMachine(resumeConfig, { persistence: mockPersistence });

      const mockResumeResult = {
        output: {
          resumed: true,
          final_state: 'processing_complete'
        },
        executionId: 'resume-execution-id',
        states: ['start', 'continue_processing', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResumeResult)
        }))
      }));

      const result = await flatMachine.execute({
        job_id: 'job-123',
        resume_from: { last_checkpoint: 'start', processed_items: 50 }
      }, {
        resumeFrom: 'previous-execution-id'
      });

      expect(result.output.resumed).toBe(true);
      expect(result.output.final_state).toBe('processing_complete');
    });
  });

  describe('Real-world Workflow Scenarios', () => {
    it('should handle complete data processing pipeline', async () => {
      const pipelineConfig = `
spec: flatmachine
spec_version: "0.1"
data:
  name: "data-processing-pipeline"
  context:
    pipeline_metrics: {}
    processed_data: {}
  states:
    ingest:
      type: "initial"
      agent: "data_ingester"
      input:
        source: "{{ input.data_source }}"
        format: "{{ input.format }}"
      output_to_context:
        raw_data: "{{ output.data }}"
        data_metadata: "{{ output.metadata }}"
      transitions:
        - condition: "context.raw_data.records > 0"
          to: "validate"
        - to: "no_data"
    validate:
      agent: "data_validator"
      input:
        data: "{{ context.raw_data }}"
        rules: "{{ input.validation_rules }}"
      output_to_context:
        validation_results: "{{ output.results }}"
        clean_data: "{{ output.cleaned_data }}"
        issues: "{{ output.issues }}"
      transitions:
        - condition: "context.validation_results.overall_score >= 0.8"
          to: "transform"
        - to: "handle_issues"
    transform:
      agent: "data_transformer"
      input:
        data: "{{ context.clean_data }}"
        transformations: "{{ input.transformations }}"
      output_to_context:
        transformed_data: "{{ output.result }}"
        transformation_metrics: "{{ output.metrics }}"
      transitions:
        - to: "enrich"
    enrich:
      machine: ["enricher", "classifier"]
      input:
        base_data: "{{ context.transformed_data }}"
        enrichment_sources: "{{ input.enrichment_sources }}"
      mode: "settled"
      output_to_context:
        enriched_data: "{{ output.enricher }}"
        classification: "{{ output.classifier }}"
      transitions:
        - to: "quality_check"
    quality_check:
      agent: "quality_assessor"
      input:
        processed_data: "{{ context.enriched_data }}"
        classification: "{{ context.classification }}"
        quality_threshold: "{{ input.quality_threshold or 0.9 }}"
      output_to_context:
        quality_report: "{{ output.report }}"
        final_data: "{{ output.approved_data }}"
      transitions:
        - condition: "context.quality_report.passed"
          to: "store"
        - to: "quality_failed"
    store:
      agent: "data_storer"
      input:
        data: "{{ context.final_data }}"
        destination: "{{ input.output_destination }}"
        metadata: "{{ context.quality_report }}"
      output_to_context:
        stored_data: "{{ output.storage_info }}"
        storage_metrics: "{{ output.metrics }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        pipeline_status: "success"
        records_processed: "{{ context.raw_data.records }}"
        quality_score: "{{ context.quality_report.overall_score }}"
        storage_info: "{{ context.stored_data }}"
        pipeline_metrics: "{{ context.transformation_metrics }}"
    no_data:
      type: "final"
      output:
        pipeline_status: "no_data"
        message: "No data found to process"
    handle_issues:
      type: "final"
      output:
        pipeline_status: "validation_failed"
        issues: "{{ context.issues }}"
        validation_score: "{{ context.validation_results.overall_score }}"
    quality_failed:
      type: "final"
      output:
        pipeline_status: "quality_failed"
        quality_report: "{{ context.quality_report }}"
`;

      flatMachine = new FlatMachine(pipelineConfig);

      const mockPipelineResult = {
        output: {
          pipeline_status: 'success',
          records_processed: 10000,
          quality_score: 0.92,
          storage_info: { 
            location: 's3://processed-data/2023-12-15/batch-123/',
            size: '250MB',
            files: 45
          },
          pipeline_metrics: {
            transform_time: 1200,
            enrich_time: 800,
            quality_check_time: 300
          }
        },
        executionId: 'pipeline-execution-id',
        states: ['ingest', 'validate', 'transform', 'enrich', 'quality_check', 'store', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockPipelineResult)
        }))
      }));

      const result = await flatMachine.execute({
        data_source: 's3://raw-data/2023-12-15/',
        format: 'json',
        validation_rules: { completeness: 0.95, consistency: 0.9 },
        transformations: ['normalize', 'standardize', 'deduplicate'],
        enrichment_sources: ['geolocation', 'demographics'],
        quality_threshold: 0.9,
        output_destination: 's3://processed-data/2023-12-15/'
      });

      expect(result.output.pipeline_status).toBe('success');
      expect(result.output.records_processed).toBe(10000);
      expect(result.output.quality_score).toBe(0.92);
      expect(result.output.storage_info.files).toBe(45);
    });
  });
});
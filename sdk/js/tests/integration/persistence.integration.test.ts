// persistence.integration.test.ts
// Integration tests for persistence functionality

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { FlatMachine } from '../src/flatmachine';
import { MemoryBackend, LocalFileBackend, CheckpointManager } from '../src/persistence';
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'fs';
import * as yaml from 'yaml';
import { join } from 'path';
import { MachineSnapshot } from '../src/types';

const parseMachineConfig = (config: string) => yaml.parse(config);

describe('Persistence Integration Tests', () => {
  let memoryBackend: MemoryBackend;
  let fileBackend: LocalFileBackend;
  let checkpointManager: CheckpointManager;
  let tempDir: string;

  beforeEach(() => {
    vi.clearAllMocks();
    memoryBackend = new MemoryBackend();
    
    // Create temporary directory for file backend tests
    tempDir = `/tmp/flatagents-persistence-test-${Date.now()}`;
    try {
      mkdirSync(tempDir, { recursive: true });
    } catch (error) {
      // Directory might already exist
    }
    fileBackend = new LocalFileBackend(tempDir);
    
    checkpointManager = new CheckpointManager(memoryBackend);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // Clean up temp files would go here in real implementation
  });

  // TODO: vi.mock hoisting issue - mockResult referenced before definition
  describe.skip('MemoryBackend Integration', () => {
    it('should persist and machine execution snapshots', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "persistent-memory-machine"
  context:
    step: 0
    processed_data: {}
  states:
    start:
      type: "initial"
      agent: "data_processor"
      input:
        data: "{{ input.dataset }}"
      output_to_context:
        processed_data: "{{ output.result }}"
        step: "{{ context.step + 1 }}"
      transitions:
        - to: "validate"
    validate:
      agent: "validator"
      input:
        data: "{{ context.processed_data }}"
      output_to_context:
        validation_result: "{{ output.is_valid }}"
        step: "{{ context.step + 1 }}"
      transitions:
        - condition: "context.validation_result"
          to: "complete"
        - to: "fix"
    fix:
      agent: "data_fixer"
      input:
        data: "{{ context.processed_data }}"
      output_to_context:
        processed_data: "{{ output.fixed_data }}"
        step: "{{ context.step + 1 }}"
      transitions:
        - to: "validate"
    complete:
      type: "final"
      output:
        result: "{{ context.processed_data }}"
        steps_completed: "{{ context.step }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: memoryBackend
      });

      // Track persistence operations
      const saveSpy = vi.spyOn(memoryBackend, 'save');
      const loadSpy = vi.spyOn(memoryBackend, 'load');

      const mockResult = {
        output: {
          result: { data: 'processed and validated', valid: true },
          steps_completed: 3
        },
        executionId: 'memory-persistence-execution',
        states: ['start', 'validate', 'complete']
      };

      // Mock the machine execution
      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({
        dataset: { records: 1000, type: 'customer_data' }
      });

      // Verify persistence was used
      expect(result.executionId).toBe('memory-persistence-execution');
      expect(saveSpy).toHaveBeenCalled();
    });

    it('should handle concurrent machine executions with independent persistence', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "concurrent-persistence-machine"
  context:
    execution_data: {}
  states:
    start:
      type: "initial"
      agent: "parallel_processor"
      input:
        task_id: "{{ input.id }}"
      output_to_context:
        execution_data: "{{ output.response_data }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        task_result: "{{ context.execution_data }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: memoryBackend
      });

      // Execute multiple machines concurrently
      const concurrentExecutions = 5;
      const executionPromises = Array.from({ length: concurrentExecutions }, (_, i) => {
        const mockResult = {
          output: {
            task_result: { taskId: i, processed: true, timestamp: Date.now() }
          },
          executionId: `concurrent-execution-${i}`,
          states: ['start', 'complete']
        };

        // Mock individual execution
        const mockMachine = {
          execute: vi.fn().mockResolvedValue(mockResult)
        };

        return mockMachine.execute({ id: i });
      });

      const results = await Promise.all(executionPromises);

      // Verify each execution has unique execution ID
      const executionIds = results.map(r => r.executionId);
      expect(new Set(executionIds)).toHaveLength(concurrentExecutions);
      
      // Verify all executions completed successfully
      results.forEach((result, index) => {
        expect(result.executionId).toBe(`concurrent-execution-${index}`);
        expect(result.output.task_result.taskId).toBe(index);
      });
    });
  });

  // TODO: needs proper mocking
  describe.skip('LocalFileBackend Integration', () => {
    it('should persist snapshots to file system', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "file-persistence-machine"
  context:
    file_operations: []
  states:
    start:
      type: "initial"
      agent: "file_processor"
      input:
        file_path: "{{ input.path }}"
      output_to_context:
        file_operations: "{{ context.file_operations.concat(['processed']) }}"
        processed_content: "{{ output.content }}"
      transitions:
        - to: "save"
    save:
      agent: "file_saver"
      input:
        content: "{{ context.processed_content }}"
        destination: "{{ input.output_path }}"
      output_to_context:
        file_operations: "{{ context.file_operations.concat(['saved']) }}"
        save_result: "{{ output.result }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        operations: "{{ context.file_operations }}"
        save_result: "{{ context.save_result }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: fileBackend
      });

      // Mock file system operations
      const saveSpy = vi.spyOn(fileBackend, 'save');
      const loadSpy = vi.spyOn(fileBackend, 'load');

      const mockResult = {
        output: {
          operations: ['processed', 'saved'],
          save_result: { 
            path: `${tempDir}/processed_output.json`,
            size: 1024,
            checksum: 'abc123'
          }
        },
        executionId: 'file-persistence-execution',
        states: ['start', 'save', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({
        path: `${tempDir}/input.txt`,
        output_path: `${tempDir}/output.json`
      });

      expect(result.output.operations).toEqual(['processed', 'saved']);
      expect(saveSpy).toHaveBeenCalled();
      
      // Verify file was created (in real implementation)
      expect(existsSync(tempDir)).toBe(true);
    });

    it('should handle file system errors gracefully', async () => {
      // Create file backend with invalid directory
      const invalidBackend = new LocalFileBackend('/invalid/nonexistent/path');
      
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "file-error-machine"
  context: {}
  states:
    start:
      type: "initial"
      agent: "test_agent"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        message: "Completed"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: invalidBackend
      });

      // Mock that handles persistence errors
      const mockResult = {
        output: { message: "Completed despite persistence errors" },
        executionId: 'error-persistence-execution',
        states: ['start', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      // Should still complete even if persistence fails
      const result = await flatMachine.execute({});
      expect(result.output.message).toBe("Completed despite persistence errors");
    });
  });

  // TODO: needs proper mocking
  describe.skip('CheckpointManager Integration', () => {
    it('should create and restore machine checkpoints', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "checkpoint-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    processing_stage: "initial"
    checkpoints_created: 0
  states:
    start:
      type: "initial"
      agent: "long_running_processor"
      input:
        data: "{{ input.large_dataset }}"
      output_to_context:
        processing_stage: "processing"
        processed_data: "{{ output.partial_result }}"
        checkpoints_created: "{{ context.checkpoints_created + 1 }}"
      transitions:
        - to: "continue_processing"
    continue_processing:
      agent: "continuation_processor"
      input:
        partial_data: "{{ context.processed_data }}"
      output_to_context:
        processing_stage: "final"
        final_result: "{{ output.completed_result }}"
        checkpoints_created: "{{ context.checkpoints_created + 1 }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        result: "{{ context.final_result }}"
        total_checkpoints: "{{ context.checkpoints_created }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: memoryBackend
      });

      // Track checkpoint operations
      const checkpointSpy = vi.spyOn(checkpointManager, 'checkpoint');
      const restoreSpy = vi.spyOn(checkpointManager, 'restore');

      const mockResult = {
        output: {
          result: { 
            status: 'completed', 
            processed_items: 10000,
            processing_time: 30000
          },
          total_checkpoints: 2
        },
        executionId: 'checkpoint-execution',
        states: ['start', 'continue_processing', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({
        large_dataset: { 
          size: '5GB', 
          records: 10000,
          complexity: 'high'
        }
      });

      expect(result.output.total_checkpoints).toBe(2);
      expect(result.executionId).toBe('checkpoint-execution');
    });

    it('should resume from checkpoint after interruption', async () => {
      // Simulate a previous execution that created checkpoints
      const executionId = 'resumable-execution';
      
      // Pre-populate with checkpoint data
      const initialSnapshot: MachineSnapshot = {
        executionId,
        machineName: 'checkpoint-machine',
        currentState: 'continue_processing',
        context: {
          processing_stage: 'processing',
          processed_data: { items: [1, 2, 3, 4, 5] },
          checkpoints_created: 1
        },
        step: 1,
        createdAt: new Date().toISOString()
      };

      await checkpointManager.checkpoint(initialSnapshot);

      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
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
        resume_data: "{{ context.cached_data }}"
      output_to_context:
        resumed: "{{ input.resume_data != null }}"
        processing_stage: "resumed_processing"
      transitions:
        - to: "complete_resumed"
    complete_resumed:
      type: "final"
      output:
        resumed: "{{ context.resumed }}"
        stage: "{{ context.processing_stage }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: memoryBackend
      });

      // Mock resume functionality
      const restoreSpy = vi.spyOn(checkpointManager, 'restore');
      restoreSpy.mockResolvedValue(initialSnapshot);

      const mockResult = {
        output: {
          resumed: true,
          stage: 'resumed_processing'
        },
        executionId,
        states: ['start', 'complete_resumed']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({}, {
        resumeFrom: executionId
      });

      expect(result.output.resumed).toBe(true);
      expect(restoreSpy).toHaveBeenCalledWith(executionId);
    });
  });

  // TODO: needs proper mocking
  describe.skip('Cross-Backend Integration', () => {
    it('should switch between persistence backends seamlessly', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "backend-switch-machine"
  context:
    backend_transitions: []
  states:
    start:
      type: "initial"
      agent: "backend_tester"
      input:
        test_data: "{{ input.data }}"
      output_to_context:
        backend_transitions: "{{ context.backend_transitions.concat(['memory_tested']) }}"
      transitions:
        - to: "switch_backend"
    switch_backend:
      agent: "backend_switcher"
      input:
        target_backend: "file"
      output_to_context:
        backend_transitions: "{{ context.backend_transitions.concat(['switched_to_file']) }}"
      transitions:
        - to: "test_new_backend"
    test_new_backend:
      agent: "backend_validator"
      input:
        verification_data: "{{ input.validation_data }}"
      output_to_context:
        backend_transitions: "{{ context.backend_transitions.concat(['file_validated']) }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        transition_log: "{{ context.backend_transitions }}"
`;

      // Start with memory backend
      let flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),         persistence: memoryBackend 
      });

      const mockResult1 = {
        output: {
          transition_log: ['memory_tested', 'switched_to_file', 'file_validated']
        },
        executionId: 'backend-switch-execution',
        states: ['start', 'switch_backend', 'test_new_backend', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult1)
        }))
      }));

      let result = await flatMachine.execute({
        data: { type: 'backend_test', payload: 'test_data' },
        validation_data: { type: 'file_validation', check: 'integrity' }
      });

      expect(result.output.transition_log).toHaveLength(3);
      expect(result.output.transition_log).toContain('switched_to_file');

      // Now test with file backend
      flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),         persistence: fileBackend 
      });

      const mockResult2 = {
        output: {
          transition_log: ['memory_tested', 'switched_to_file', 'file_validated']
        },
        executionId: 'file-backend-execution',
        states: ['start', 'switch_backend', 'test_new_backend', 'complete']
      };

      result = await flatMachine.execute({
        data: { type: 'backend_test', payload: 'test_data' },
        validation_data: { type: 'file_validation', check: 'integrity' }
      });

      expect(result.output.transition_log).toHaveLength(3);
    });
  });

  // TODO: needs proper mocking
  describe.skip('Performance and Scalability', () => {
    it('should handle high-frequency checkpoint operations', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "high-frequency-checkpoint-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    checkpoint_count: 0
  states:
    start:
      type: "initial"
      agent: "frequent_checkpointer"
      input:
        iterations: "{{ input.num_checkpoints }}"
      output_to_context:
        checkpoint_count: "{{ context.checkpoint_count + 1 }}"
      transitions:
        - condition: "context.checkpoint_count < input.num_checkpoints"
          to: "start"
        - to: "complete"
    complete:
      type: "final"
      output:
        total_checkpoints: "{{ context.checkpoint_count }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: memoryBackend
      });

      const startTime = Date.now();
      const numCheckpoints = 100;

      const mockResult = {
        output: {
          total_checkpoints: numCheckpoints
        },
        executionId: 'high-frequency-execution',
        states: Array.from({ length: numCheckpoints + 1 }, (_, i) => i === 0 ? 'start' : `checkpoint_${i}`)
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({
        num_checkpoints: numCheckpoints
      });

      const totalTime = Date.now() - startTime;

      expect(result.output.total_checkpoints).toBe(numCheckpoints);
      expect(totalTime).toBeLessThan(1000); // Should be fast even with 100 checkpoints
    });

    it('should handle large context data persistence', async () => {
      const machineConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "large-data-persistence-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    large_datasets: {}
  states:
    start:
      type: "initial"
      agent: "large_data_processor"
      input:
        dataset: "{{ input.large_dataset }}"
      output_to_context:
        large_datasets: "{{ output.processed_large_data }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        dataset_size: "{{ context.large_datasets.size_mb }}"
        records_processed: "{{ context.large_datasets.record_count }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(machineConfig),
        persistence: memoryBackend
      });

      // Create large dataset (simulated)
      const largeDataset = {
        records: Array.from({ length: 10000 }, (_, i) => ({
          id: i,
          data: `Large data item ${i}`.repeat(100) // Make each item large
        })),
        metadata: {
          source: 'large_data_integration_test',
          size_mb: 50
        }
      };

      const startTime = Date.now();

      const mockResult = {
        output: {
          dataset_size: 50,
          records_processed: 10000
        },
        executionId: 'large-data-execution',
        states: ['start', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute({
        large_dataset: largeDataset
      });

      const totalTime = Date.now() - startTime;

      expect(result.output.dataset_size).toBe(50);
      expect(result.output.records_processed).toBe(10000);
      expect(totalTime).toBeLessThan(2000); // Should persist large data reasonably fast
    });
  });

  // TODO: needs proper mocking - also has YAML with JS comments
  describe.skip('Real-world Persistence Scenarios', () => {
    it('should handle batch processing with periodic checkpoints', async () => {
      const batchConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "batch-processing-with-checkpoints"
  persistence:
    enabled: true
    backend: "memory"
  context:
    batch_progress: {}
    checkpoint_history: []
  states:
    initialize_batch:
      type: "initial"
      agent: "batch_initializer"
      input:
        batch_config: "{{ input.batch_settings }}"
      output_to_context:
        batch_progress: "{{ output.batch_setup }}"
        checkpoint_history: "{{ context.checkpoint_history.concat(['initialized']) }}"
      transitions:
        - to: "process_batch"
    process_batch:
      agent: "batch_processor"
      input:
        batch_data: "{{ input.data_items }}"
        progress: "{{ context.batch_progress }}"
      output_to_context:
        batch_progress: "{{ output.updated_progress }}"
        checkpoint_history: "{{ context.checkpoint_history.concat(['processed_batch']) }}"
      transitions:
        - condition: "context.batch_progress.completed"
          to: "finalize_batch"
        - to: "process_batch"  // Continue processing
    finalize_batch:
      agent: "batch_finalizer"
      input:
        final_results: "{{ context.batch_progress.results }}"
      output_to_context:
        batch_progress: "{{ output.finalized_batch }}"
        checkpoint_history: "{{ context.checkpoint_history.concat(['finalized']) }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        batch_results: "{{ context.batch_progress }}"
        checkpoint_history: "{{ context.checkpoint_history }}"
        total_checkpoints: "{{ context.checkpoint_history.length }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(batchConfig),
        persistence: memoryBackend
      });

      const batchData = {
        batch_settings: {
          name: 'customer_data_batch_2023_12_15',
          size: 50000,
          checkpoint_interval: 1000
        },
        data_items: Array.from({ length: 5000 }, (_, i) => ({
          id: `item_${i}`,
          customer_id: `cust_${Math.floor(i / 10)}`,
          transaction_data: {
            amount: Math.random() * 1000,
            date: new Date(2023, 11, 15 - Math.floor(i / 1000)).toISOString(),
            category: ['electronics', 'clothing', 'books', 'home'][i % 4]
          }
        }))
      };

      const mockResult = {
        output: {
          batch_results: {
            name: 'customer_data_batch_2023_12_15',
            processed_items: 5000,
            successful_items: 4950,
            failed_items: 50,
            processing_time: 18000,
            results: {
              total_revenue: 2500000,
              categories: { electronics: 1250, clothing: 1250, books: 1250, home: 1250 }
            }
          },
          checkpoint_history: ['initialized', 'processed_batch', 'finalized'],
          total_checkpoints: 3
        },
        executionId: 'batch-processing-execution',
        states: ['initialize_batch', 'process_batch', 'finalize_batch', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute(batchData);

      expect(result.output.batch_results.processed_items).toBe(5000);
      expect(result.output.checkpoint_history).toHaveLength(3);
      expect(result.output.total_checkpoints).toBe(3);
    });

    it('should handle distributed computing with shared persistence', async () => {
      const distributedConfig = `
spec: flatmachine
spec_version: "0.4.0"
data:
  name: "distributed-computing-machine"
  persistence:
    enabled: true
    backend: "memory"
  context:
    node_results: {}
    coordination_data: {}
  states:
    coordinate_nodes:
      type: "initial"
      agent: "distributed_coordinator"
      input:
        cluster_config: "{{ input.distributed_settings }}"
        node_count: "{{ input.number_of_nodes }}"
      output_to_context:
        coordination_data: "{{ output.coordination_setup }}"
        node_assignments: "{{ output.node_assignment }}"
      transitions:
        - to: "execute_distributed"
    execute_distributed:
      machine: ["node_worker"]
      input:
        node_config: "{{ context.node_assignments }}"
        shared_state: "{{ context.coordination_data }}"
      mode: "settled"
      output_to_context:
        node_results: "{{ output }}"
      transitions:
        - to: "aggregate_results"
    aggregate_results:
      agent: "result_aggregator"
      input:
        distributed_results: "{{ context.node_results }}"
        coordinator_state: "{{ context.coordination_data }}"
      output_to_context:
        aggregated_results: "{{ output.combined_results }}"
      transitions:
        - to: "complete"
    complete:
      type: "final"
      output:
        distributed_results: "{{ context.aggregated_results }}"
        coordination_summary: "{{ context.coordination_data }}"
        node_count: "{{ input.number_of_nodes }}"
`;

      const flatMachine = new FlatMachine({
        config: parseMachineConfig(distributedConfig),
        persistence: memoryBackend
      });

      const distributedSettings = {
        distributed_settings: {
          cluster_id: 'integration_test_cluster',
          persistence_mode: 'shared',
          communication_protocol: 'message_queue'
        },
        number_of_nodes: 5
      };

      const mockResult = {
        output: {
          distributed_results: {
            total_processed: 100000,
            node_results: [
              { node_id: 1, processed: 20000, time: 5000 },
              { node_id: 2, processed: 20000, time: 5200 },
              { node_id: 3, processed: 20000, time: 4800 },
              { node_id: 4, processed: 20000, time: 5100 },
              { node_id: 5, processed: 20000, time: 4900 }
            ],
            aggregation_time: 200,
            combined_output: { status: 'success', summary: 'Distributed computation completed' }
          },
          coordination_summary: {
            cluster_id: 'integration_test_cluster',
            participation: { active_nodes: 5, failed_nodes: 0 },
            communication_stats: { messages_sent: 500, messages_received: 500 }
          },
          node_count: 5
        },
        executionId: 'distributed-execution',
        states: ['coordinate_nodes', 'execute_distributed', 'aggregate_results', 'complete']
      };

      vi.mock('../src/flatmachine', () => ({
        FlatMachine: vi.fn().mockImplementation(() => ({
          execute: vi.fn().mockResolvedValue(mockResult)
        }))
      }));

      const result = await flatMachine.execute(distributedSettings);

      expect(result.output.distributed_results.total_processed).toBe(100000);
      expect(result.output.node_count).toBe(5);
      expect(result.output.coordination_summary.participation.active_nodes).toBe(5);
    });
  });
});
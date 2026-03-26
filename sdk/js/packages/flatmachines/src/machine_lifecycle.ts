/**
 * Machine lifecycle helpers — checkpoint, launch, and result management.
 *
 * Extracted from FlatMachine to reduce god-class complexity.
 * Pure utility functions that operate on provided state rather than class internals.
 */

import { randomUUID } from 'node:crypto';
import { MachineSnapshot, LaunchIntent, ResultBackend, MachineHooks } from './types';
import { CheckpointManager } from './persistence';

/**
 * Build a result URI for a given execution ID.
 */
export function makeResultUri(executionId: string): string {
  return `flatagents://${executionId}/result`;
}

/**
 * Create a checkpoint snapshot object.
 */
export function buildCheckpointSnapshot(opts: {
  executionId: string;
  machineName: string;
  specVersion: string;
  state: string;
  context: Record<string, any>;
  step: number;
  event?: string;
  output?: any;
  totalApiCalls?: number;
  totalCost?: number;
  parentExecutionId?: string;
  pendingLaunches?: LaunchIntent[];
  configHash?: string;
  waitingChannel?: string;
  toolLoopState?: Record<string, any>;
}): MachineSnapshot {
  const snapshot: MachineSnapshot = {
    execution_id: opts.executionId,
    machine_name: opts.machineName,
    spec_version: opts.specVersion,
    current_state: opts.state,
    context: opts.context,
    step: opts.step,
    created_at: new Date().toISOString(),
    event: opts.event,
    output: opts.output,
    total_api_calls: opts.totalApiCalls,
    total_cost: opts.totalCost,
    parent_execution_id: opts.parentExecutionId,
    config_hash: opts.configHash,
  };

  if (opts.pendingLaunches?.length) {
    snapshot.pending_launches = opts.pendingLaunches;
  }
  if (opts.waitingChannel) {
    snapshot.waiting_channel = opts.waitingChannel;
  }
  if (opts.toolLoopState) {
    snapshot.tool_loop_state = opts.toolLoopState;
  }

  return snapshot;
}

/**
 * Inject machine metadata into the context as a frozen object.
 */
export function injectMachineMetadata(
  context: Record<string, any>,
  opts: {
    executionId: string;
    machineName: string;
    specVersion: string;
    step: number;
    state: string;
    parentExecutionId?: string;
    totalApiCalls: number;
    totalCost: number;
  },
): void {
  context.machine = Object.freeze({
    execution_id: opts.executionId,
    machine_name: opts.machineName,
    spec_version: opts.specVersion,
    step: opts.step,
    current_state: opts.state,
    parent_execution_id: opts.parentExecutionId ?? null,
    total_api_calls: opts.totalApiCalls,
    total_cost: opts.totalCost,
  });
}

/**
 * Build an assistant message from an agent result (for tool loop chains).
 */
export function buildAssistantMessage(result: any): Record<string, any> {
  const msg: Record<string, any> = { role: 'assistant', content: result.content ?? '' };
  const toolCalls = result.tool_calls;
  if (toolCalls?.length) {
    msg.tool_calls = toolCalls.map((tc: any) => ({
      id: tc.id,
      type: 'function',
      function: {
        name: tc.name ?? tc.tool,
        arguments: typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments ?? {}),
      },
    }));
  }
  return msg;
}

/**
 * Extract cost from an agent result, handling both number and object forms.
 */
export function extractCost(result: any): number {
  const cost = result?.cost;
  if (cost == null) return 0;
  if (typeof cost === 'number') return cost;
  if (typeof cost === 'object' && 'total' in cost) return Number(cost.total);
  return 0;
}

/**
 * Normalize a machine result, throwing for error results.
 */
export function normalizeMachineResult(result: any): any {
  if (result && typeof result === 'object' && '_error' in result) {
    const error = new Error(String(result._error ?? 'Machine execution failed'));
    error.name = String((result as Record<string, any>)._error_type ?? 'Error');
    throw error;
  }
  return result;
}

/**
 * Race promises with a "first completed" strategy.
 */
export async function firstCompleted<T>(tasks: Promise<T>[]): Promise<T> {
  return new Promise((resolve, reject) => {
    let pending = tasks.length;
    let settled = false;
    const errors: any[] = [];
    for (const task of tasks) {
      task.then((value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      }).catch((err) => {
        errors.push(err);
        pending -= 1;
        if (pending === 0 && !settled) {
          reject(errors[0]);
        }
      });
    }
  });
}

/**
 * Add a timeout to a promise.
 */
export function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Operation timed out')), timeoutMs);
    promise.then((value) => {
      clearTimeout(timer);
      resolve(value);
    }).catch((err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

/**
 * Await tasks with mode selection (settled = all, any = first).
 */
export async function awaitWithMode<T>(
  tasks: Promise<T>[],
  mode: string,
  timeoutMs?: number,
): Promise<T | T[]> {
  if (tasks.length === 0) {
    return mode === 'any' ? (undefined as T) : ([] as T[]);
  }
  const runner: Promise<T | T[]> = mode === 'any' ? firstCompleted(tasks) : Promise.all(tasks);
  if (!timeoutMs) return runner;
  return withTimeout(runner, timeoutMs);
}

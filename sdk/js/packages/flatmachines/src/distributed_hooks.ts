/**
 * Distributed worker hooks.
 *
 * Ports Python SDK's distributed_hooks.py. Ready-to-use action handlers
 * for pool management, worker lifecycle, reaper, and auto-scaling.
 */

import { MachineHooks } from './types';
import {
  RegistrationBackend,
  WorkerRegistration,
  WorkerFilter,
} from './distributed';
import { WorkBackend } from './work';
import { hostname } from 'os';

export class DistributedWorkerHooks implements MachineHooks {
  private _registration: RegistrationBackend;
  private _work: WorkBackend;

  constructor(registration: RegistrationBackend, work: WorkBackend) {
    this._registration = registration;
    this._work = work;
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    const handlers: Record<string, (ctx: Record<string, any>) => Promise<Record<string, any>>> = {
      get_pool_state: ctx => this._getPoolState(ctx),
      claim_job: ctx => this._claimJob(ctx),
      complete_job: ctx => this._completeJob(ctx),
      fail_job: ctx => this._failJob(ctx),
      register_worker: ctx => this._registerWorker(ctx),
      deregister_worker: ctx => this._deregisterWorker(ctx),
      heartbeat: ctx => this._heartbeat(ctx),
      list_stale_workers: ctx => this._listStaleWorkers(ctx),
      reap_worker: ctx => this._reapWorker(ctx),
      reap_stale_workers: ctx => this._reapStaleWorkers(ctx),
      calculate_spawn: ctx => this._calculateSpawn(ctx),
      spawn_workers: ctx => this._spawnWorkers(ctx),
    };
    const handler = handlers[action];
    if (handler) return handler(context);
    return context;
  }

  // Pool state
  private async _getPoolState(ctx: Record<string, any>): Promise<Record<string, any>> {
    const poolId = ctx.pool_id ?? 'default';
    const pool = this._work.pool(poolId);
    const workers = await this._registration.list({ status: 'active' });
    ctx.queue_depth = await pool.size();
    ctx.active_workers = workers.length;
    return ctx;
  }

  // Job operations
  private async _claimJob(ctx: Record<string, any>): Promise<Record<string, any>> {
    const poolId = ctx.pool_id ?? 'default';
    const workerId = ctx.worker_id;
    if (!workerId) throw new Error('worker_id is required for claim_job');
    const pool = this._work.pool(poolId);
    const item = await pool.claim(workerId);
    ctx.job = item?.data ?? null;
    ctx.job_id = item?.id ?? null;
    return ctx;
  }

  private async _completeJob(ctx: Record<string, any>): Promise<Record<string, any>> {
    const poolId = ctx.pool_id ?? 'default';
    const jobId = ctx.job_id;
    if (!jobId) throw new Error('job_id is required for complete_job');
    await this._work.pool(poolId).complete(jobId, ctx.result);
    return ctx;
  }

  private async _failJob(ctx: Record<string, any>): Promise<Record<string, any>> {
    const poolId = ctx.pool_id ?? 'default';
    const jobId = ctx.job_id;
    if (!jobId) throw new Error('job_id is required for fail_job');
    await this._work.pool(poolId).fail(jobId, ctx.error);
    return ctx;
  }

  // Worker lifecycle
  private async _registerWorker(ctx: Record<string, any>): Promise<Record<string, any>> {
    const workerId = ctx.worker_id;
    if (!workerId) throw new Error('worker_id is required for register_worker');
    const reg: WorkerRegistration = {
      worker_id: workerId,
      host: hostname(),
      pid: process.pid,
      capabilities: ctx.capabilities ?? [],
      pool_id: ctx.pool_id,
    };
    const record = await this._registration.register(reg);
    ctx.worker_id = record.worker_id;
    ctx.status = record.status;
    ctx.registered_at = record.started_at;
    return ctx;
  }

  private async _deregisterWorker(ctx: Record<string, any>): Promise<Record<string, any>> {
    const workerId = ctx.worker_id;
    if (!workerId) throw new Error('worker_id is required for deregister_worker');
    await this._registration.updateStatus(workerId, 'terminated');
    return ctx;
  }

  private async _heartbeat(ctx: Record<string, any>): Promise<Record<string, any>> {
    const workerId = ctx.worker_id;
    if (!workerId) throw new Error('worker_id is required for heartbeat');
    await this._registration.heartbeat(workerId);
    return ctx;
  }

  // Reaper
  private async _listStaleWorkers(ctx: Record<string, any>): Promise<Record<string, any>> {
    const threshold = ctx.stale_threshold_seconds ?? 60;
    const workers = await this._registration.list({ status: 'active', stale_threshold_seconds: threshold });
    ctx.workers = workers.map(w => ({ worker_id: w.worker_id, last_heartbeat: w.last_heartbeat, host: w.host }));
    ctx.stale_count = workers.length;
    return ctx;
  }

  private async _reapWorker(ctx: Record<string, any>): Promise<Record<string, any>> {
    const worker = ctx.worker;
    const poolId = ctx.pool_id ?? 'default';
    if (!worker) throw new Error('worker is required for reap_worker');
    const workerId = worker.worker_id;
    await this._registration.updateStatus(workerId, 'lost');
    const pool = this._work.pool(poolId);
    const released = await pool.releaseByWorker(workerId);
    ctx.reaped_worker_id = workerId;
    ctx.jobs_released = released;
    return ctx;
  }

  private async _reapStaleWorkers(ctx: Record<string, any>): Promise<Record<string, any>> {
    const staleWorkers = ctx.stale_workers ?? [];
    const poolId = ctx.pool_id ?? 'default';
    const reaped: string[] = [];
    let totalJobsReleased = 0;
    for (const worker of staleWorkers) {
      const workerId = worker.worker_id;
      await this._registration.updateStatus(workerId, 'lost');
      const pool = this._work.pool(poolId);
      const released = await pool.releaseByWorker(workerId);
      reaped.push(workerId);
      totalJobsReleased += released;
    }
    ctx.reaped_workers = reaped;
    ctx.reaped_count = reaped.length;
    ctx.total_jobs_released = totalJobsReleased;
    return ctx;
  }

  // Auto-scaling
  private async _calculateSpawn(ctx: Record<string, any>): Promise<Record<string, any>> {
    const queueDepth = Number(ctx.queue_depth ?? 0);
    const activeWorkers = Number(ctx.active_workers ?? 0);
    const maxWorkers = Number(ctx.max_workers ?? 3);
    const workersNeeded = Math.min(queueDepth, maxWorkers);
    const workersToSpawn = Math.max(0, workersNeeded - activeWorkers);
    ctx.workers_needed = workersNeeded;
    ctx.workers_to_spawn = workersToSpawn;
    ctx.spawn_list = Array.from({ length: workersToSpawn }, (_, i) => i);
    return ctx;
  }

  private async _spawnWorkers(ctx: Record<string, any>): Promise<Record<string, any>> {
    const workersToSpawn = Number(ctx.workers_to_spawn ?? 0);
    const { randomUUID } = require('node:crypto');
    const spawnedIds: string[] = [];
    for (let i = 0; i < workersToSpawn; i++) {
      const workerId = `worker-${randomUUID().slice(0, 8)}`;
      // In a real deployment, this would launch a subprocess or send to a queue.
      // The hook consumer is expected to override this for their infrastructure.
      spawnedIds.push(workerId);
    }
    ctx.spawned_ids = spawnedIds;
    ctx.spawned_count = spawnedIds.length;
    return ctx;
  }
}
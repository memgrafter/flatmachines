/**
 * Signal dispatcher — Phase 3.4
 *
 * Ports Python SDK's dispatcher.py. Bridges signals to waiting machine resume.
 */

import { SignalBackend } from './signals';
import { PersistenceBackend } from './types';

// ─────────────────────────────────────────────────────────────────────────────
// MachineResumer interface (Phase 3.5)
// ─────────────────────────────────────────────────────────────────────────────

export interface MachineResumer {
  resume(executionId: string, signalData: any): Promise<any>;
}

// ─────────────────────────────────────────────────────────────────────────────
// SignalDispatcher
// ─────────────────────────────────────────────────────────────────────────────

export class SignalDispatcher {
  private signalBackend: SignalBackend;
  private persistenceBackend: PersistenceBackend;
  private resumeFn: ((executionId: string, signalData: any) => Promise<any>) | null;

  constructor(
    signalBackend: SignalBackend,
    persistenceBackend: PersistenceBackend,
    opts?: {
      resumer?: MachineResumer;
      resumeFn?: (executionId: string, signalData: any) => Promise<any>;
    },
  ) {
    this.signalBackend = signalBackend;
    this.persistenceBackend = persistenceBackend;
    if (opts?.resumer) {
      this.resumeFn = opts.resumer.resume.bind(opts.resumer);
    } else {
      this.resumeFn = opts?.resumeFn ?? null;
    }
  }

  /**
   * Process one signal on a channel. Resumes all waiting machines.
   * Returns list of resumed execution IDs.
   */
  async dispatch(channel: string): Promise<string[]> {
    if (!this.persistenceBackend.listExecutionIds) return [];

    const executionIds = await this.persistenceBackend.listExecutionIds({ waiting_channel: channel });
    if (!executionIds.length) return [];

    const signal = await this.signalBackend.consume(channel);
    if (!signal) return [];

    // Fan out: one copy per waiter
    for (const _eid of executionIds) {
      await this.signalBackend.send(channel, signal.data);
    }

    const resumed: string[] = [];
    for (const eid of executionIds) {
      if (this.resumeFn) {
        try {
          await this.resumeFn(eid, signal.data);
          resumed.push(eid);
        } catch (e) {
          // Log but continue
        }
      } else {
        resumed.push(eid);
      }
    }
    return resumed;
  }

  /**
   * Drain a channel by dispatching until no progress.
   */
  async dispatchChannel(channel: string, maxSignals?: number): Promise<string[]> {
    const resumedAll: string[] = [];
    let processed = 0;
    while (true) {
      if (maxSignals != null && processed >= maxSignals) break;
      const resumed = await this.dispatch(channel);
      if (!resumed.length) break;
      resumedAll.push(...resumed);
      processed += 1;
    }
    return resumedAll;
  }

  /**
   * Process all pending signals across all channels.
   */
  async dispatchAll(): Promise<Record<string, string[]>> {
    const results: Record<string, string[]> = {};
    const channels = await this.signalBackend.channels();
    for (const channel of channels) {
      const pending = await this.signalBackend.peek(channel);
      const maxSignals = pending.length || 1;
      const resumed = await this.dispatchChannel(channel, maxSignals);
      if (resumed.length) results[channel] = resumed;
    }
    return results;
  }
}

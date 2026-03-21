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
    // Find machines waiting on this channel first
    const executionIds = this.persistenceBackend.listExecutionIds
      ? await this.persistenceBackend.listExecutionIds({ waiting_channel: channel })
      : [];

    if (!executionIds.length) {
      // No waiters — leave signals untouched
      return [];
    }

    // Consume the signal
    const signal = await this.signalBackend.consume(channel);
    if (!signal) return [];

    // Fan out: one copy per waiter so each machine can consume on resume
    for (const _eid of executionIds) {
      await this.signalBackend.send(channel, signal.data);
    }

    // Resume all waiters
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
   * Process pending signals on a channel (single pass).
   */
  async dispatchChannel(channel: string, _maxSignals?: number): Promise<string[]> {
    return this.dispatch(channel);
  }

  /**
   * Process all pending signals across all channels.
   */
  async dispatchAll(): Promise<Record<string, string[]>> {
    const results: Record<string, string[]> = {};
    const channels = await this.signalBackend.channels();
    for (const channel of channels) {
      const resumed = await this.dispatchChannel(channel);
      if (resumed.length) results[channel] = resumed;
    }
    return results;
  }
}

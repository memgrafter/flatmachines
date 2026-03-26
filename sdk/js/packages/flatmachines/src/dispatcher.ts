/**
 * Signal dispatcher.
 *
 * Ports Python SDK's dispatcher.py. Bridges signals to waiting machine resume.
 */

import { SignalBackend } from './signals';
import { PersistenceBackend } from './types';
import { createServer, type Server } from 'node:net';

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
      // No waiters — leave signals untouched so they're available later
      return [];
    }

    // Consume the signal
    const signal = await this.signalBackend.consume(channel);
    if (!signal) return [];

    // Resume all waiters. For each, re-send the signal so the resumed machine
    // can consume it in handleWaitFor, then resume. After resume, consume the
    // re-sent signal if the machine didn't (prevents infinite loops in dispatchAll).
    const resumed: string[] = [];
    for (const eid of executionIds) {
      const preCount = (await this.signalBackend.peek(channel)).length;
      await this.signalBackend.send(channel, signal.data);

      if (this.resumeFn) {
        try {
          await this.resumeFn(eid, signal.data);
          resumed.push(eid);
        } catch {
          // Log but continue
        }
      } else {
        resumed.push(eid);
      }

      // Check if the machine consumed the re-sent signal
      const postCount = (await this.signalBackend.peek(channel)).length;
      if (postCount > preCount) {
        // Signal wasn't consumed by the machine — clean it up
        await this.signalBackend.consume(channel);
      }
    }
    return resumed;
  }

  /**
   * Process one pending signal on a channel.
   */
  async dispatchChannel(channel: string, _maxSignals?: number): Promise<string[]> {
    return this.dispatch(channel);
  }

  /**
   * Listen on a UDS socket for trigger notifications.
   * Creates a server, drains pending signals, then polls until stopEvent is set.
   */
  async listen(
    socketPath: string,
    stopEvent: { is_set(): boolean; set(): void },
  ): Promise<void> {
    const { unlinkSync, existsSync } = require('fs');
    if (existsSync(socketPath)) unlinkSync(socketPath);

    const server: Server = createServer((conn) => {
      conn.on('data', async (data: Buffer) => {
        const channel = data.toString('utf-8').trim();
        if (channel) {
          await this.dispatchChannel(channel);
        }
      });
    });

    await new Promise<void>((resolve) => {
      server.listen(socketPath, () => resolve());
    });

    try {
      // Drain pending signals first
      await this.dispatchAll();

      // Poll until stopped
      while (!stopEvent.is_set()) {
        await new Promise((r) => setTimeout(r, 50));
        await this.dispatchAll();
      }
    } finally {
      server.close();
      if (existsSync(socketPath)) {
        try { unlinkSync(socketPath); } catch {}
      }
    }
  }

  /**
   * Process all pending signals across all channels.
   * Processes one signal per channel, then re-scans for remaining signals.
   */
  async dispatchAll(): Promise<Record<string, string[]>> {
    const results: Record<string, string[]> = {};
    // Repeat until no more signals are dispatched (handles multiple signals per channel)
    for (let pass = 0; pass < 1000; pass++) {
      const channels = await this.signalBackend.channels();
      if (!channels.length) break;
      let dispatched = false;
      for (const channel of channels) {
        const resumed = await this.dispatch(channel);
        if (resumed.length) {
          if (!results[channel]) results[channel] = [];
          results[channel].push(...resumed);
          dispatched = true;
        }
      }
      if (!dispatched) break;
    }
    return results;
  }
}
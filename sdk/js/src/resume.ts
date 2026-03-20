/**
 * Machine resume abstraction — Phase 3.5
 *
 * Ports Python SDK's resume.py. Provides ConfigStoreResumer for
 * reconstructing and resuming parked machines from checkpoint.
 */

import { MachineResumer } from './dispatcher';
import { ConfigStore } from './persistence_sqlite';
import { SignalBackend } from './signals';
import { PersistenceBackend, MachineSnapshot, MachineHooks } from './types';
import { HooksRegistry } from './hooks';
import { ToolProvider } from './tools';
import * as yaml from 'yaml';

// ─────────────────────────────────────────────────────────────────────────────
// Reference resolver
// ─────────────────────────────────────────────────────────────────────────────

export type ReferenceResolver = (opts: {
  machine_name: string;
  config_hash: string;
  ref_kind: string;
  ref_name: string;
  ref_value: string;
}) => Record<string, any> | null | Promise<Record<string, any> | null>;

// ─────────────────────────────────────────────────────────────────────────────
// CheckpointManager helper (loads latest from any PersistenceBackend)
// ─────────────────────────────────────────────────────────────────────────────

async function loadLatestSnapshot(
  backend: PersistenceBackend,
  executionId: string,
): Promise<MachineSnapshot | null> {
  // Try listExecutionIds-based approach first (for SQLite backends)
  if ((backend as any).loadLatest) {
    return (backend as any).loadLatest(executionId);
  }

  // Fallback: list all keys and pick the latest
  const keys = await backend.list(`${executionId}/`);
  if (!keys.length) return null;
  const sorted = keys.sort();
  return backend.load(sorted[sorted.length - 1]!);
}

// ─────────────────────────────────────────────────────────────────────────────
// ConfigStoreResumer
// ─────────────────────────────────────────────────────────────────────────────

export interface ConfigStoreResumerOptions {
  signalBackend: SignalBackend;
  persistenceBackend: PersistenceBackend;
  configStore: ConfigStore;
  refResolver?: ReferenceResolver;
  hooks?: MachineHooks;
  hooksRegistry?: HooksRegistry;
  toolProvider?: ToolProvider;
}

export class ConfigStoreResumer implements MachineResumer {
  private _signalBackend: SignalBackend;
  private _persistence: PersistenceBackend;
  private _configStore: ConfigStore;
  private _refResolver: ReferenceResolver | null;
  private _hooks: MachineHooks | undefined;
  private _hooksRegistry: HooksRegistry | undefined;
  private _toolProvider: ToolProvider | undefined;

  constructor(opts: ConfigStoreResumerOptions) {
    this._signalBackend = opts.signalBackend;
    this._persistence = opts.persistenceBackend;
    this._configStore = opts.configStore;
    this._refResolver = opts.refResolver ?? null;
    this._hooks = opts.hooks;
    this._hooksRegistry = opts.hooksRegistry;
    this._toolProvider = opts.toolProvider;
  }

  private async _loadSnapshot(executionId: string): Promise<MachineSnapshot> {
    const snapshot = await loadLatestSnapshot(this._persistence, executionId);
    if (!snapshot) throw new Error(`No checkpoint found for execution ${executionId}`);
    return snapshot;
  }

  private async _resolveRef(opts: {
    machine_name: string;
    config_hash: string;
    ref_kind: string;
    ref_name: string;
    ref_value: string;
  }): Promise<Record<string, any>> {
    if (!this._refResolver) {
      throw new Error(
        `Portable resume does not support string/path refs without a refResolver. ` +
        `Found ${opts.ref_kind}s.${opts.ref_name}=${opts.ref_value} in machine=${opts.machine_name} hash=${opts.config_hash}.`
      );
    }
    const resolved = await this._refResolver(opts);
    if (resolved == null) {
      throw new Error(
        `refResolver could not resolve ${opts.ref_kind}s.${opts.ref_name}=${opts.ref_value} ` +
        `for machine=${opts.machine_name} hash=${opts.config_hash}.`
      );
    }
    return resolved;
  }

  private async _materializeStringRefs(
    configDict: Record<string, any>,
    machineName: string,
    configHashVal: string,
  ): Promise<Record<string, any>> {
    const data = configDict.data;
    if (!data || typeof data !== 'object') return configDict;

    for (const [refKind, section] of [['agent', 'agents'], ['machine', 'machines']] as const) {
      const refs = data[section];
      if (!refs || typeof refs !== 'object') continue;
      for (const [refName, refValue] of Object.entries(refs)) {
        if (typeof refValue !== 'string') continue;
        refs[refName] = await this._resolveRef({
          machine_name: machineName,
          config_hash: configHashVal,
          ref_kind: refKind,
          ref_name: refName,
          ref_value: refValue,
        });
      }
    }
    return configDict;
  }

  private async _loadConfig(snapshot: MachineSnapshot): Promise<Record<string, any>> {
    const hash = (snapshot as any).config_hash;
    if (!hash) {
      throw new Error(
        `No config_hash in checkpoint for execution ${snapshot.execution_id}. ` +
        `Machine was created without a config_store.`
      );
    }
    const raw = await this._configStore.get(hash);
    if (raw == null) {
      throw new Error(`Config not found in store for hash ${hash}.`);
    }
    let configDict: Record<string, any>;
    try {
      configDict = yaml.parse(raw);
    } catch {
      configDict = JSON.parse(raw);
    }
    return this._materializeStringRefs(configDict, snapshot.machine_name, hash);
  }

  async buildMachine(
    executionId: string,
    snapshot: MachineSnapshot,
    configDict: Record<string, any>,
  ): Promise<any> {
    // Lazy import to avoid circular dependency
    const { FlatMachine } = require('./flatmachine');
    return new FlatMachine({
      config: configDict,
      persistence: this._persistence,
      hooks: this._hooks,
      hooksRegistry: this._hooksRegistry,
    });
  }

  async resume(executionId: string, signalData: any): Promise<any> {
    const snapshot = await this._loadSnapshot(executionId);
    const configDict = await this._loadConfig(snapshot);
    const machine = await this.buildMachine(executionId, snapshot, configDict);
    return machine.resume(executionId);
  }
}

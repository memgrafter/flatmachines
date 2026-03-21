/**
 * Actions and Machine Invokers — Phase 3.7
 *
 * Ports Python SDK's actions.py. Provides HookAction, InlineInvoker,
 * SubprocessInvoker, and QueueInvoker.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Action interface
// ─────────────────────────────────────────────────────────────────────────────

export interface Action {
  execute(
    actionName: string,
    context: Record<string, any>,
    config: Record<string, any>,
  ): Promise<Record<string, any>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// HookAction — delegates to machine hooks (on_action)
// ─────────────────────────────────────────────────────────────────────────────

export class HookAction implements Action {
  constructor(private hooks: any) {}

  async execute(
    actionName: string,
    context: Record<string, any>,
    config: Record<string, any>,
  ): Promise<Record<string, any>> {
    if (this.hooks?.onAction) {
      const result = await this.hooks.onAction(actionName, context);
      return result ?? context;
    }
    return context;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MachineInvoker
// ─────────────────────────────────────────────────────────────────────────────

export interface MachineInvoker {
  invoke(
    callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId?: string,
  ): Promise<Record<string, any>>;

  launch(
    callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId: string,
  ): Promise<void>;
}

// ─────────────────────────────────────────────────────────────────────────────
// InlineInvoker — runs target machine in same process
// ─────────────────────────────────────────────────────────────────────────────

export class InlineInvoker implements MachineInvoker {
  async invoke(
    callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId?: string,
  ): Promise<Record<string, any>> {
    // Lazy import to avoid circular dependency
    const { FlatMachine } = require('./flatmachine');
    const target = new FlatMachine({
      config: targetConfig,
      configDir: callerMachine.configDir ?? process.cwd(),
      resultBackend: callerMachine.resultBackend,
      hooksRegistry: callerMachine.hooksRegistry,
      executionId,
      parentExecutionId: callerMachine.executionId,
      profilesFile: callerMachine.profilesFile,
    });
    return target.execute(inputData);
  }

  async launch(
    callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId: string,
  ): Promise<void> {
    // Fire-and-forget: start execution but don't await
    this.invoke(callerMachine, targetConfig, inputData, executionId).catch(() => {});
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SubprocessInvoker — launches machines as independent subprocesses
// ─────────────────────────────────────────────────────────────────────────────

export class SubprocessInvoker implements MachineInvoker {
  private workingDir?: string;

  constructor(opts?: { workingDir?: string }) {
    this.workingDir = opts?.workingDir;
  }

  async invoke(
    callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId?: string,
  ): Promise<Record<string, any>> {
    const { randomUUID } = require('node:crypto');
    const eid = executionId ?? randomUUID();
    await this.launch(callerMachine, targetConfig, inputData, eid);
    // Block until result available
    if (callerMachine.resultBackend) {
      return callerMachine.resultBackend.read(`flatagents://${eid}/result`, { block: true });
    }
    throw new Error('No result backend available for SubprocessInvoker.invoke()');
  }

  async launch(
    _callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId: string,
  ): Promise<void> {
    const { spawn } = require('child_process');
    const { writeFileSync, mkdtempSync } = require('fs');
    const { join } = require('path');
    const { tmpdir } = require('os');

    // Write config and input to temp files (avoids shell injection)
    const tmpDir = mkdtempSync(join(tmpdir(), 'flatmachines-'));
    const configPath = join(tmpDir, 'config.json');
    const inputPath = join(tmpDir, 'input.json');
    const metaPath = join(tmpDir, 'meta.json');
    writeFileSync(configPath, JSON.stringify(targetConfig));
    writeFileSync(inputPath, JSON.stringify(inputData));
    writeFileSync(metaPath, JSON.stringify({ executionId }));

    // Write a launcher script that reads data from files (no interpolation)
    const launcherPath = join(tmpDir, 'launcher.cjs');
    const sdkPath = require.resolve('./flatmachine').replace(/\\/g, '/');
    writeFileSync(launcherPath, [
      `const { readFileSync } = require('fs');`,
      `const { join } = require('path');`,
      `const dir = ${JSON.stringify(tmpDir)};`,
      `const config = JSON.parse(readFileSync(join(dir, 'config.json'), 'utf-8'));`,
      `const input = JSON.parse(readFileSync(join(dir, 'input.json'), 'utf-8'));`,
      `const meta = JSON.parse(readFileSync(join(dir, 'meta.json'), 'utf-8'));`,
      `const { FlatMachine } = require(${JSON.stringify(sdkPath)});`,
      `const machine = new FlatMachine({ config, executionId: meta.executionId });`,
      `machine.execute(input).catch(e => { console.error(e); process.exit(1); });`,
    ].join('\n'));

    // Spawn detached process
    const child = spawn(
      process.execPath,
      [launcherPath],
      {
        detached: true,
        stdio: 'ignore',
        cwd: this.workingDir ?? process.cwd(),
      },
    ) as any;
    child.unref();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// QueueInvoker — abstract base for queue-based invocation
// ─────────────────────────────────────────────────────────────────────────────

export abstract class QueueInvoker implements MachineInvoker {
  async invoke(
    callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId?: string,
  ): Promise<Record<string, any>> {
    const { randomUUID } = require('node:crypto');
    const eid = executionId ?? randomUUID();
    await this.launch(callerMachine, targetConfig, inputData, eid);
    if (callerMachine.resultBackend) {
      return callerMachine.resultBackend.read(`flatagents://${eid}/result`, { block: true });
    }
    throw new Error('No result backend available for QueueInvoker.invoke()');
  }

  async launch(
    _callerMachine: any,
    targetConfig: Record<string, any>,
    inputData: Record<string, any>,
    executionId: string,
  ): Promise<void> {
    await this.enqueue(executionId, targetConfig, inputData);
  }

  protected abstract enqueue(
    executionId: string,
    config: Record<string, any>,
    inputData: Record<string, any>,
  ): Promise<void>;
}

import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  DistributedWorkerHooks,
  SQLiteRegistrationBackend,
  SQLiteWorkBackend,
} from '@memgrafter/flatmachines';

export class DemoHooks extends DistributedWorkerHooks {
  readonly dbPath: string;

  constructor(dbPath: string) {
    mkdirSync(dirname(dbPath), { recursive: true });
    const registration = new SQLiteRegistrationBackend(dbPath);
    const work = new SQLiteWorkBackend(dbPath);
    super(registration, work);
    this.dbPath = dbPath;
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action === 'echo_delay') {
      const delaySeconds = Number(context.delay_seconds ?? context?.job?.delay_seconds ?? 1);
      const delayMs = Math.max(0, delaySeconds) * 1000;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      context.processed = true;
      context.delay_applied = delaySeconds;
      return context;
    }

    return super.onAction(action, context);
  }
}

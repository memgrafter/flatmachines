import type { MachineHooks } from '@memgrafter/flatmachines';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';
import { CLIToolProvider } from './tools.js';

type Context = Record<string, any>;

function dim(text: string): string {
  return `\u001b[2m${text}\u001b[0m`;
}

function bold(text: string): string {
  return `\u001b[1m${text}\u001b[0m`;
}

async function prompt(question: string): Promise<string> {
  const rl = createInterface({ input, output });
  try {
    const answer = await rl.question(question);
    return answer.trim();
  } catch {
    return '';
  } finally {
    rl.close();
  }
}

export class CLIToolHooks implements MachineHooks {
  private readonly provider: CLIToolProvider;
  private readonly autoApprove: boolean;

  constructor(workingDir = '.', autoApprove = false) {
    this.provider = new CLIToolProvider(workingDir);
    this.autoApprove = autoApprove;
  }

  get_tool_provider(_stateName: string): CLIToolProvider {
    return this.provider;
  }

  async onAction(actionName: string, context: Context): Promise<Context> {
    if (actionName === 'human_review') {
      return await this.humanReview(context);
    }
    return context;
  }

  on_tool_calls(_stateName: string, _toolCalls: any[], context: Context): Context {
    const content = context._tool_loop_content;
    if (typeof content === 'string' && content.trim()) {
      console.log();
      console.log(dim(content.trim()));
    }

    const usage = context._tool_loop_usage ?? {};
    const parts: string[] = [];
    const inputTokens = usage.input_tokens;
    const outputTokens = usage.output_tokens;
    if (inputTokens !== undefined || outputTokens !== undefined) {
      parts.push(`tokens: ${inputTokens ?? 0}→${outputTokens ?? 0}`);
    }

    const cost = context._tool_loop_cost;
    if (typeof cost === 'number' && Number.isFinite(cost)) {
      parts.push(`$${cost.toFixed(4)}`);
    }

    if (parts.length) {
      console.log(dim(parts.join(' | ')));
    }

    return context;
  }

  on_tool_result(_stateName: string, toolCallResult: Record<string, any>, context: Context): Context {
    const name = String(toolCallResult.name ?? '');
    const args = (toolCallResult.arguments ?? {}) as Record<string, any>;
    const result = (toolCallResult.result ?? {}) as Record<string, any>;
    const isError = Boolean(result.is_error);

    let label = `${name}: ${JSON.stringify(args)}`;
    if (name === 'bash') {
      label = `bash: ${String(args.command ?? '')}`;
    } else if (name === 'read') {
      label = `read: ${String(args.path ?? '')}`;
      const offset = args.offset;
      const limit = args.limit;
      const extras: string[] = [];
      if (offset !== undefined && offset !== null) extras.push(`offset=${offset}`);
      if (limit !== undefined && limit !== null) extras.push(`limit=${limit}`);
      if (extras.length) {
        label += ` (${extras.join(', ')})`;
      }
    } else if (name === 'write') {
      const bytes = Buffer.byteLength(String(args.content ?? ''), 'utf8');
      label = `write: ${String(args.path ?? '')} (${bytes} bytes)`;
    } else if (name === 'edit') {
      label = `edit: ${String(args.path ?? '')}`;
    }

    const status = isError ? '✗' : '✓';
    console.log(`  ${status} ${bold(label)}`);

    if (!isError && (name === 'write' || name === 'edit')) {
      const path = String(args.path ?? '');
      if (path) {
        const modified = Array.isArray(context.files_modified) ? context.files_modified : [];
        if (!modified.includes(path)) {
          modified.push(path);
        }
        context.files_modified = modified;
      }
    }

    return context;
  }

  private async humanReview(context: Context): Promise<Context> {
    const result = context.result;
    if (typeof result === 'string' && result) {
      console.log();
      console.log(result);
    }

    const files = Array.isArray(context.files_modified) ? context.files_modified : [];
    if (files.length) {
      console.log();
      console.log(dim(`Files modified: ${files.join(', ')}`));
    }

    if (this.autoApprove) {
      context.human_approved = true;
      return context;
    }

    console.log();
    const response = await prompt('> ');

    if (response) {
      const chain = Array.isArray(context._tool_loop_chain) ? context._tool_loop_chain : [];
      chain.push({ role: 'user', content: response });
      context._tool_loop_chain = chain;
      context.human_approved = false;
    } else {
      context.human_approved = true;
    }

    return context;
  }
}

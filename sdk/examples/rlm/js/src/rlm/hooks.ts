import type { MachineHooks } from '@memgrafter/flatmachines';
import { REPLExecutor } from './repl.js';

type Context = Record<string, any>;

export class RLMHooks implements MachineHooks {
  async onAction(action: string, context: Context): Promise<Context> {
    const handlers: Record<string, (ctx: Context) => Promise<Context> | Context> = {
      init_repl: this.initRepl.bind(this),
      execute_repl: this.executeRepl.bind(this),
      extract_chunk: this.extractChunk.bind(this),
      log_error: this.logError.bind(this),
      log_chunk_error: this.logChunkError.bind(this),
    };

    const handler = handlers[action];
    if (handler) {
      return await handler(context);
    }

    console.warn(`Unknown action: ${action}`);
    return context;
  }

  private initRepl(context: Context): Context {
    const content = context.context_content ?? '';
    if (!content) {
      console.warn('No context content provided');
      return context;
    }

    context.content_type = detectContentType(content);
    context.structure_summary = getStructureSummary(content);

    console.log(`RLM initialized with ${content.length} character context`);
    return context;
  }

  private executeRepl(context: Context): Context {
    const code = context.code ?? '';
    if (!code) {
      console.warn('No code to execute');
      return context;
    }

    const repl = new REPLExecutor();
    repl.setContext(context.context_content ?? '');

    const result = repl.execute(code);

    const history = context.exploration_history ?? [];
    history.push({
      code,
      result: result.output || result.return_value || result.error,
      success: result.success,
    });
    context.exploration_history = history;

    if (!result.success) {
      context.last_error = result.error ?? 'Unknown error';
    }

    return context;
  }

  private extractChunk(context: Context): Context {
    const content = context.context_content ?? '';
    const subTask = context.sub_task ?? {};

    let start = Math.max(0, subTask.chunk_start ?? 0);
    let end = Math.min(content.length, subTask.chunk_end ?? content.length);

    if (start > end) {
      [start, end] = [end, start];
    }

    context.chunk_content = content.slice(start, end);
    return context;
  }

  private logError(context: Context): Context {
    const error = context.last_error ?? 'Unknown error';
    const round = context.exploration_round ?? 0;
    console.error(`Exploration error in round ${round}: ${error}`);
    return context;
  }

  private logChunkError(context: Context): Context {
    const error = context.last_error ?? 'Unknown error';
    const subTask = context.sub_task ?? {};
    console.error(`Chunk error for ${subTask.id ?? 'unknown'}: ${error}`);
    return context;
  }
}

function detectContentType(content: string): string {
  if (content.trim().startsWith('{') || content.trim().startsWith('[')) {
    return 'json_data';
  }
  if (content.includes('```') || content.includes('def ') || content.includes('class ')) {
    return 'code';
  }
  if (content.split('\n').length > 100 && ['#', '##', '###'].some(marker => content.includes(marker))) {
    return 'markdown_document';
  }
  if (content.includes('\t') && content.split('\n').length > 50) {
    return 'tabular_data';
  }
  if (content.split('.').length > content.split('\n').length / 2) {
    return 'prose_document';
  }
  return 'mixed_content';
}

function getStructureSummary(content: string): string {
  const lines = content.split('\n').length;
  const chars = content.length;
  const preview = content.slice(0, 100).replace(/\n/g, ' ');
  return `${lines} lines, ${chars} chars. Starts: ${preview}...`;
}

import { promises as fs } from 'fs';
import { dirname, isAbsolute, join, resolve as pathResolve } from 'path';
import { randomUUID } from 'crypto';
import { homedir, tmpdir } from 'os';
import { spawn } from 'child_process';
import type { ToolProvider, ToolResult } from '@memgrafter/flatmachines';
import { toolResult } from '@memgrafter/flatmachines';

const MAX_LINES = 2000;
const MAX_BYTES = 50 * 1024;

function byteLength(text: string): number {
  return Buffer.byteLength(text, 'utf8');
}

function truncateHead(content: string, maxLines = MAX_LINES, maxBytes = MAX_BYTES): {
  content: string;
  truncated: boolean;
  totalLines: number;
} {
  const lines = content.split('\n');
  const totalLines = lines.length;

  if (totalLines <= maxLines && byteLength(content) <= maxBytes) {
    return { content, truncated: false, totalLines };
  }

  const output: string[] = [];
  let bytes = 0;

  for (let i = 0; i < lines.length; i += 1) {
    if (i >= maxLines) break;
    const line = lines[i];
    const lineBytes = byteLength(line) + (i > 0 ? 1 : 0);
    if (bytes + lineBytes > maxBytes) break;
    output.push(line);
    bytes += lineBytes;
  }

  return {
    content: output.join('\n'),
    truncated: true,
    totalLines,
  };
}

function truncateTail(content: string, maxLines = MAX_LINES, maxBytes = MAX_BYTES): {
  content: string;
  truncated: boolean;
  totalLines: number;
} {
  const lines = content.split('\n');
  const totalLines = lines.length;

  if (totalLines <= maxLines && byteLength(content) <= maxBytes) {
    return { content, truncated: false, totalLines };
  }

  const output: string[] = [];
  let bytes = 0;

  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i];
    const lineBytes = byteLength(line) + (output.length > 0 ? 1 : 0);
    if (bytes + lineBytes > maxBytes) break;
    if (output.length >= maxLines) break;
    output.unshift(line);
    bytes += lineBytes;
  }

  return {
    content: output.join('\n'),
    truncated: true,
    totalLines,
  };
}

function expandUser(pathInput: string): string {
  if (pathInput === '~') {
    return homedir();
  }
  if (pathInput.startsWith('~/')) {
    return join(homedir(), pathInput.slice(2));
  }
  return pathInput;
}

function resolvePath(pathInput: string, workingDir: string): string {
  const expanded = expandUser(pathInput);
  if (isAbsolute(expanded)) {
    return expanded;
  }
  return join(workingDir, expanded);
}

function toInt(value: any, fallback: number): number {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`Invalid number: ${value}`);
  }
  return Math.trunc(parsed);
}

export async function toolRead(workingDir: string, _id: string, args: Record<string, any>): Promise<ToolResult> {
  const path = String(args.path ?? '');
  const offsetRaw = args.offset;
  const limitRaw = args.limit;

  try {
    const fullPath = resolvePath(path, workingDir);
    const stat = await fs.stat(fullPath).catch(() => null);

    if (!stat) {
      return toolResult(`File not found: ${path}`, true);
    }
    if (!stat.isFile()) {
      return toolResult(`Not a file: ${path}`, true);
    }

    const text = await fs.readFile(fullPath, 'utf8');
    const allLines = text.split('\n');
    const totalLines = allLines.length;

    let start = 0;
    if (offsetRaw !== undefined && offsetRaw !== null) {
      start = Math.max(0, toInt(offsetRaw, 1) - 1);
      if (start >= totalLines) {
        return toolResult(`Offset ${offsetRaw} beyond end of file (${totalLines} lines)`, true);
      }
    }

    let selected = allLines.slice(start);
    if (limitRaw !== undefined && limitRaw !== null) {
      selected = selected.slice(0, toInt(limitRaw, selected.length));
    }

    let content = selected.join('\n');
    const truncated = truncateHead(content);
    content = truncated.content;

    if (truncated.truncated) {
      const shown = content ? content.split('\n').length : 0;
      const endLine = start + shown;
      content += `\n\n[Showing lines ${start + 1}-${endLine} of ${totalLines}. Use offset=${endLine + 1} to continue]`;
    } else if (limitRaw !== undefined && limitRaw !== null) {
      const shown = selected.length;
      const endLine = start + shown;
      const remaining = totalLines - endLine;
      if (remaining > 0) {
        content += `\n\n[${remaining} more lines in file. Use offset=${endLine + 1} to continue]`;
      }
    }

    return toolResult(content);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return toolResult(`Error reading ${path}: ${message}`, true);
  }
}

type BashExecResult = {
  stdout: string;
  stderr: string;
  code: number | null;
  timedOut: boolean;
};

async function runBash(command: string, workingDir: string, timeoutSeconds: number): Promise<BashExecResult> {
  return await new Promise<BashExecResult>((resolve, reject) => {
    const child = spawn('bash', ['-c', command], {
      cwd: workingDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: process.env,
    });

    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let resolved = false;

    const timeoutMs = Math.max(1, timeoutSeconds) * 1000;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      setTimeout(() => child.kill('SIGKILL'), 1000).unref();
    }, timeoutMs);

    child.stdout.on('data', chunk => {
      stdout += String(chunk);
    });

    child.stderr.on('data', chunk => {
      stderr += String(chunk);
    });

    child.on('error', err => {
      clearTimeout(timer);
      if (!resolved) {
        resolved = true;
        reject(err);
      }
    });

    child.on('close', code => {
      clearTimeout(timer);
      if (!resolved) {
        resolved = true;
        resolve({ stdout, stderr, code, timedOut });
      }
    });
  });
}

export async function toolBash(workingDir: string, _id: string, args: Record<string, any>): Promise<ToolResult> {
  const command = String(args.command ?? '');
  const timeout = toInt(args.timeout, 30);

  try {
    const result = await runBash(command, workingDir, timeout);

    if (result.timedOut) {
      return toolResult(`Command timed out after ${timeout}s`, true);
    }

    let output = '';
    if (result.stdout) output += result.stdout;
    if (result.stderr) {
      if (output) output += '\n';
      output += result.stderr;
    }
    if (!output) {
      output = '(no output)';
    }

    const { content: truncatedOutput, truncated, totalLines } = truncateTail(output);
    let finalOutput = truncatedOutput;

    if (truncated) {
      const tempPath = join(tmpdir(), `cli-bash-${randomUUID()}.log`);
      await fs.writeFile(tempPath, output, 'utf8');
      const outputLines = truncatedOutput ? truncatedOutput.split('\n').length : 0;
      const startLine = Math.max(1, totalLines - outputLines + 1);
      finalOutput += `\n\n[Showing lines ${startLine}-${totalLines} of ${totalLines}. Full output: ${tempPath}]`;
    }

    if ((result.code ?? 0) !== 0) {
      return toolResult(`${finalOutput}\n\nCommand exited with code ${result.code}`, true);
    }

    return toolResult(finalOutput);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return toolResult(`Error executing command: ${message}`, true);
  }
}

export async function toolWrite(workingDir: string, _id: string, args: Record<string, any>): Promise<ToolResult> {
  const path = String(args.path ?? '');
  const content = String(args.content ?? '');

  try {
    const fullPath = resolvePath(path, workingDir);
    await fs.mkdir(dirname(fullPath), { recursive: true });
    await fs.writeFile(fullPath, content, 'utf8');
    return toolResult(`Successfully wrote ${byteLength(content)} bytes to ${fullPath}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return toolResult(`Error writing ${path}: ${message}`, true);
  }
}

export async function toolEdit(workingDir: string, _id: string, args: Record<string, any>): Promise<ToolResult> {
  const path = String(args.path ?? '');
  const oldText = String(args.oldText ?? '');
  const newText = String(args.newText ?? '');

  try {
    const fullPath = resolvePath(path, workingDir);
    const stat = await fs.stat(fullPath).catch(() => null);

    if (!stat) {
      return toolResult(`File not found: ${path}`, true);
    }
    if (!stat.isFile()) {
      return toolResult(`Not a file: ${path}`, true);
    }

    const content = await fs.readFile(fullPath, 'utf8');

    if (!content.includes(oldText)) {
      return toolResult(
        `oldText not found in ${path}. Make sure it matches exactly (including whitespace).`,
        true,
      );
    }

    const count = content.split(oldText).length - 1;
    if (count > 1) {
      return toolResult(`oldText matches ${count} locations in ${path}. Make it more specific.`, true);
    }

    const updated = content.replace(oldText, newText);
    await fs.writeFile(fullPath, updated, 'utf8');
    return toolResult(`Successfully edited ${path}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return toolResult(`Error editing ${path}: ${message}`, true);
  }
}

export class CLIToolProvider implements ToolProvider {
  private readonly workingDir: string;

  constructor(workingDir = '.') {
    this.workingDir = pathResolve(workingDir);
  }

  get_tool_definitions(): Array<Record<string, any>> {
    // Tool definitions come from config/agent.yml to keep a single source of truth.
    return [];
  }

  async execute_tool(name: string, toolCallId: string, args: Record<string, any>): Promise<ToolResult> {
    if (name === 'read') {
      return await toolRead(this.workingDir, toolCallId, args);
    }
    if (name === 'bash') {
      return await toolBash(this.workingDir, toolCallId, args);
    }
    if (name === 'write') {
      return await toolWrite(this.workingDir, toolCallId, args);
    }
    if (name === 'edit') {
      return await toolEdit(this.workingDir, toolCallId, args);
    }
    return toolResult(`Unknown tool: ${name}`, true);
  }
}

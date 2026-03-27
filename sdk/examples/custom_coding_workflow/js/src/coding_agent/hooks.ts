import type { MachineHooks } from '@memgrafter/flatmachines';
import { spawnSync } from 'child_process';
import { existsSync, readFileSync, mkdirSync, writeFileSync, unlinkSync } from 'fs';
import { dirname, resolve, relative, join } from 'path';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';

type Context = Record<string, any>;

type DiffOperation = {
  path: string;
  action: 'create' | 'modify' | 'delete';
  content?: string;
  search?: string;
  replace?: string;
  is_diff?: boolean;
};

export class CodingAgentHooks implements MachineHooks {
  private workingDir: string;

  constructor(workingDir = '.') {
    this.workingDir = resolve(workingDir);
  }

  onStateEnter(_stateName: string, context: Context): Context {
    for (const key of ['iteration', 'max_iterations', 'token_budget', 'frozen_token_count']) {
      const value = context[key];
      if (typeof value === 'string') {
        const parsed = Number.parseInt(value, 10);
        if (!Number.isNaN(parsed)) {
          context[key] = parsed;
        }
      }
    }
    return context;
  }

  private getApprovalResponse(kind: 'plan' | 'result'): string | null {
    const key = kind === 'plan' ? 'CODING_AGENT_APPROVAL_PLAN' : 'CODING_AGENT_APPROVAL_RESULT';
    const value = process.env[key];
    if (value === undefined) return null;
    return value.trim();
  }

  async onAction(action: string, context: Context): Promise<Context> {
    const handlers: Record<string, (ctx: Context) => Promise<Context> | Context> = {
      explore_codebase: this.exploreCodebase.bind(this),
      run_tree: this.runTree.bind(this),
      run_ripgrep: this.runRipgrep.bind(this),
      read_file: this.readFile.bind(this),
      read_plan_files: this.readPlanFiles.bind(this),
      human_review_plan: this.humanReviewPlan.bind(this),
      human_review_result: this.humanReviewResult.bind(this),
      apply_changes: this.applyChanges.bind(this),
    };

    const handler = handlers[action];
    if (handler) {
      return await handler(context);
    }
    return context;
  }

  private runCommand(cmd: string, cwd: string, timeoutMs: number): string {
    try {
      const result = spawnSync(cmd, {
        shell: true,
        cwd,
        encoding: 'utf8',
        timeout: timeoutMs,
      });

      if (result.error) {
        return `Error: ${result.error.message}`;
      }

      const output = (result.stdout || result.stderr || '').trimEnd();
      if (!output) {
        return result.status === 0 ? '(no output)' : `Error: command failed (${result.status ?? 'unknown'})`;
      }
      return output;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return `Error: ${message}`;
    }
  }

  private runCodebaseRipper(context: Context, workingDir: string): string | null {
    const home = process.env.HOME;
    if (!home) return null;

    const ripperScript = join(home, '.agents', 'skills', 'codebase-ripper', 'run.sh');
    if (!existsSync(ripperScript)) {
      return null;
    }

    const task = String(context.task ?? 'Explore this codebase');
    const tokenBudget = Number.parseInt(String(context.token_budget ?? '12000'), 10);
    const maxIterations = Number.parseInt(String(context.explorer_iterations ?? '2'), 10);

    const result = spawnSync('bash', [
      ripperScript,
      task,
      '-d', workingDir,
      '--token-budget', Number.isNaN(tokenBudget) ? '12000' : String(tokenBudget),
      '--max-iterations', Number.isNaN(maxIterations) ? '2' : String(maxIterations),
      '--json',
    ], {
      encoding: 'utf8',
      timeout: 300000,
      maxBuffer: 20 * 1024 * 1024,
    });

    if (result.status !== 0) {
      const stderr = (result.stderr ?? '').trim();
      if (stderr) {
        console.warn(`Codebase-ripper failed, falling back to local exploration: ${stderr}`);
      }
      return null;
    }

    try {
      const parsed = JSON.parse(result.stdout || '{}');
      const extracted = typeof parsed.context === 'string' ? parsed.context.trim() : '';
      if (!extracted) return null;
      return extracted;
    } catch {
      return null;
    }
  }

  private exploreCodebase(context: Context): Context {
    const workingDir = context.working_dir ? resolve(context.working_dir) : this.workingDir;

    // Preferred path: use codebase-ripper skill for broad, parallel exploration.
    const ripperContext = this.runCodebaseRipper(context, workingDir);
    if (ripperContext) {
      context.codebase_context = ripperContext;
      context.explorer_source = 'codebase-ripper';
      return context;
    }

    // Fallback: minimal local exploration if ripper is unavailable.
    const contextParts: string[] = [];

    const treeOutput = this.runCommand('tree -L 3 -I "__pycache__|node_modules|.git|.venv|*.pyc"', workingDir, 10000);
    if (!treeOutput.startsWith('Error')) {
      contextParts.push(`## Directory Structure\n\n\n\`\`\`\n${treeOutput}\n\`\`\``);
    } else {
      const lsOutput = this.runCommand('ls -la', workingDir, 5000);
      contextParts.push(`## Files\n\n\n\`\`\`\n${lsOutput}\n\`\`\``);
    }

    const readmeNames = ['README.md', 'README.txt', 'README'];
    for (const readme of readmeNames) {
      const readmePath = resolve(workingDir, readme);
      if (existsSync(readmePath)) {
        try {
          const content = readFileSync(readmePath, 'utf8').slice(0, 2000);
          contextParts.push(`## ${readme}\n${content}`);
          break;
        } catch {
          // Ignore read errors
        }
      }
    }

    context.codebase_context = contextParts.length
      ? contextParts.join('\n\n')
      : `Working directory: ${workingDir}`;
    context.explorer_source = 'fallback-local';
    return context;
  }

  private runTree(context: Context): Context {
    let cmd = (context.action_command ?? '').trim();
    const workingDir = context.working_dir ? resolve(context.working_dir) : this.workingDir;

    if (!cmd || !cmd.startsWith('tree')) {
      const path = cmd || '.';
      cmd = `tree -L 3 --noreport ${path}`;
    }

    const output = this.runCommand(cmd, workingDir, 30000);

    context.latest_output = output;
    context.latest_action = 'tree';

    const treeOutputs = context.tree_outputs ?? [];
    treeOutputs.push({ command: cmd, output });
    context.tree_outputs = treeOutputs;

    return context;
  }

  private runRipgrep(context: Context): Context {
    let cmd = (context.action_command ?? '').trim();
    const workingDir = context.working_dir ? resolve(context.working_dir) : this.workingDir;

    if (!cmd || !cmd.startsWith('rg')) {
      const pattern = cmd || 'TODO';
      cmd = `rg '${pattern}' --type-add 'code:*.{py,js,ts,yml,yaml}' --type code`;
    }

    let output = this.runCommand(cmd, workingDir, 60000);
    if (!output) {
      output = '(no matches)';
    }

    if (output.length > 50000) {
      output = `${output.slice(0, 50000)}\n... (truncated)`;
    }

    context.latest_output = output;
    context.latest_action = 'rg';

    const rgResults = context.rg_results ?? [];
    rgResults.push({ command: cmd, output });
    context.rg_results = rgResults;

    return context;
  }

  private isWithin(basePath: string, targetPath: string): boolean {
    const rel = relative(basePath, targetPath);
    return !rel.startsWith('..') && !rel.startsWith('/') && rel !== '' ? true : rel === '';
  }

  private readFile(context: Context): Context {
    const filepath = (context.action_command ?? '').trim();
    const workingDir = context.working_dir ? resolve(context.working_dir) : this.workingDir;

    if (!filepath) {
      context.latest_output = 'Error: no file path specified';
      context.latest_action = 'read';
      return context;
    }

    const fullPath = resolve(workingDir, filepath);
    if (!this.isWithin(workingDir, fullPath)) {
      context.latest_output = 'Error: path outside working directory';
      context.latest_action = 'read';
      return context;
    }

    let outputText = '';
    try {
      let content = readFileSync(fullPath, 'utf8');
      if (content.length > 100000) {
        content = `${content.slice(0, 100000)}\n... (truncated)`;
      }
      outputText = content;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      outputText = `Error reading file: ${message}`;
    }

    context.latest_output = outputText;
    context.latest_action = 'read';

    const fileContents = context.file_contents ?? {};
    fileContents[filepath] = outputText;
    context.file_contents = fileContents;

    return context;
  }

  private readPlanFiles(context: Context): Context {
    const planRaw = context.plan ?? '';
    const plan = typeof planRaw === 'object' && planRaw?.content ? planRaw.content : String(planRaw);
    const workingDir = context.working_dir ? resolve(context.working_dir) : this.workingDir;

    const pathPattern = /(?:^|\s|`|\[|\()(\.?\/?(?:[\w.-]+\/)*[\w.-]+\.(?:py|js|ts|jsx|tsx|yml|yaml|json|md|txt|sh|go|rs|rb|java|c|cpp|h|hpp|css|html|sql))(?:\s|$|`|\]|\)|:)/g;
    const matches: string[] = [];
    for (const match of plan.matchAll(pathPattern) as Iterable<RegExpMatchArray>) {
      if (match[1]) matches.push(match[1]);
    }
    const uniquePaths = Array.from(new Set(matches.map(p => p.replace(/^\.\//, ''))));

    const fileContents = context.file_contents ?? {};
    const filesRead: string[] = [];

    for (const filepath of uniquePaths.slice(0, 20)) {
      const fullPath = resolve(workingDir, filepath);
      if (!this.isWithin(workingDir, fullPath)) {
        continue;
      }
      try {
        if (existsSync(fullPath)) {
          let content = readFileSync(fullPath, 'utf8');
          if (content.length > 50000) {
            content = `${content.slice(0, 50000)}\n... (truncated)`;
          }
          fileContents[filepath] = content;
          filesRead.push(filepath);
        }
      } catch {
        // Ignore read errors
      }
    }

    context.file_contents = fileContents;

    console.log(`\n📂 Read ${filesRead.length} files for coder context:`);
    for (const file of filesRead) {
      console.log(`   - ${file}`);
    }

    return context;
  }

  private async prompt(question: string): Promise<string> {
    const rl = createInterface({ input, output });
    const answer = await rl.question(question);
    rl.close();
    return answer.trim();
  }

  private async humanReviewPlan(context: Context): Promise<Context> {
    const planRaw = context.plan ?? '';
    const plan = typeof planRaw === 'object' && planRaw?.content ? planRaw.content : planRaw;

    console.log(`\n${'='.repeat(70)}`);
    console.log('📋 PLAN REVIEW');
    console.log('='.repeat(70));

    console.log(`\n📝 Task: ${context.task ?? 'Unknown'}\n`);

    if (plan && String(plan).trim()) {
      console.log('-'.repeat(70));
      console.log(String(plan));
      console.log('-'.repeat(70));
    } else {
      console.log('[WARNING] No plan content received');
    }

    console.log(`\n${'-'.repeat(70)}`);
    let response = this.getApprovalResponse('plan');
    if (response === null) {
      response = await this.prompt('Approve plan? (y/yes to approve, or enter feedback): ');
    }

    if (response.toLowerCase() === 'y' || response.toLowerCase() === 'yes' || response.toLowerCase() === 'approved' || response === '') {
      context.plan_approved = true;
      context.human_feedback = null;
      console.log('✅ Plan approved!');
    } else {
      context.plan_approved = false;
      context.human_feedback = response;

      const planHistory = context.plan_history ?? [];
      planHistory.push({
        content: plan,
        feedback: response,
      });
      context.plan_history = planHistory;
      console.log('🔄 Feedback recorded. Revising plan...');
    }

    console.log(`${'='.repeat(70)}\n`);
    return context;
  }

  private async humanReviewResult(context: Context): Promise<Context> {
    const changesRaw = context.changes ?? '';
    const issuesRaw = context.issues ?? '';
    const reviewSummaryRaw = context.review_summary ?? '';

    const changes = typeof changesRaw === 'object' && changesRaw?.content ? changesRaw.content : changesRaw;
    const issues = typeof issuesRaw === 'object' && issuesRaw?.content ? issuesRaw.content : issuesRaw;
    const reviewSummary = typeof reviewSummaryRaw === 'object' && reviewSummaryRaw?.content
      ? reviewSummaryRaw.content
      : reviewSummaryRaw;

    console.log(`\n${'='.repeat(70)}`);
    console.log('🔍 RESULT REVIEW');
    console.log('='.repeat(70));

    console.log(`\n📝 Task: ${context.task ?? 'Unknown'}`);
    console.log(`🔄 Iteration: ${context.iteration ?? '?'}`);

    if (changes && String(changes).trim()) {
      console.log('\nProposed Changes:');
      console.log('-'.repeat(70));
      console.log(String(changes));
      console.log('-'.repeat(70));
    } else {
      console.log('[WARNING] No changes content received');
    }

    if (issues && String(issues).trim()) {
      console.log(`\n📊 Reviewer Assessment:`);
      console.log(String(issues));
    }

    if (reviewSummary && String(reviewSummary).trim()) {
      console.log(`\n📊 Review: ${reviewSummary}`);
    }

    console.log(`\n${'-'.repeat(70)}`);
    let response = this.getApprovalResponse('result');
    if (response === null) {
      response = await this.prompt('Approve changes? (y/yes to approve, or enter feedback): ');
    }

    if (response.toLowerCase() === 'y' || response.toLowerCase() === 'yes' || response.toLowerCase() === 'approved' || response === '') {
      context.result_approved = true;
      context.human_feedback = null;
      console.log('✅ Changes approved!');
    } else {
      context.result_approved = false;
      context.human_feedback = response;

      const changesHistory = context.changes_history ?? [];
      changesHistory.push({
        content: changes,
        feedback: response,
        issues,
      });
      context.changes_history = changesHistory;
      console.log('🔄 Feedback recorded. Revising changes...');
    }

    console.log(`${'='.repeat(70)}\n`);
    return context;
  }

  private parseDiffs(text: string): DiffOperation[] {
    const quadPattern = /````[a-zA-Z]*\n([^\n]+)\n<<<<<<< SEARCH\n?([\s\S]*?)\n?=======\n([\s\S]*?)\n>>>>>>> REPLACE\s*````/g;
    const triplePattern = /```[a-zA-Z]*\n([^\n]+)\n<<<<<<< SEARCH\n?([\s\S]*?)\n?=======\n([\s\S]*?)\n>>>>>>> REPLACE\s*```/g;

    const blocks = new Map<string, DiffOperation>();

    const applyMatch = (match: RegExpExecArray) => {
      const filepath = match[1].trim();
      const searchContent = match[2];
      const replaceContent = match[3];
      const key = `${filepath}\u0000${searchContent}`;

      if (!searchContent.trim()) {
        blocks.set(key, { path: filepath, action: 'create', content: replaceContent });
      } else {
        blocks.set(key, {
          path: filepath,
          action: 'modify',
          search: searchContent,
          replace: replaceContent,
          is_diff: true,
        });
      }
    };

    let match: RegExpExecArray | null;
    while ((match = quadPattern.exec(text)) !== null) {
      applyMatch(match);
    }
    while ((match = triplePattern.exec(text)) !== null) {
      applyMatch(match);
    }

    return Array.from(blocks.values());
  }

  private applyChanges(context: Context): Context {
    const changesRaw = context.changes ?? '';
    const changes = typeof changesRaw === 'object' && changesRaw?.content ? changesRaw.content : changesRaw;

    const workingDir = context.working_dir ? resolve(context.working_dir) : this.workingDir;
    const basePath = resolve(workingDir);
    const safetyBase = context.user_cwd ? resolve(context.user_cwd) : basePath;

    console.log(`\n${'='.repeat(70)}`);
    console.log('📝 APPLYING CHANGES');
    console.log('='.repeat(70));

    let operations: DiffOperation[] = [];
    if (typeof changes === 'string' && changes.trim()) {
      operations = this.parseDiffs(changes);
    } else if (typeof changes === 'object' && changes?.files) {
      operations = changes.files as DiffOperation[];
    }

    const applied: string[] = [];
    const errors: string[] = [];

    for (const op of operations) {
      const path = op.path;
      if (!path) {
        continue;
      }
      const filePath = resolve(basePath, path);
      if (!this.isWithin(safetyBase, filePath)) {
        const message = `🚫 BLOCKED: Path outside allowed directory: ${path}`;
        errors.push(message);
        console.log(`  🚫 BLOCKED: ${path} (outside ${safetyBase})`);
        continue;
      }

      try {
        if (op.action === 'create') {
          mkdirSync(dirname(filePath), { recursive: true });
          writeFileSync(filePath, op.content ?? '', 'utf8');
          applied.push(`➕ Created: ${path}`);
          console.log(`  ➕ Created: ${path}`);
          continue;
        }

        if (op.action === 'modify') {
          if (!existsSync(filePath)) {
            errors.push(`File not found for modify: ${path}`);
            console.log(`  ⚠️  File not found: ${path}`);
            continue;
          }

          const original = readFileSync(filePath, 'utf8');
          if (op.is_diff && op.search !== undefined) {
            const search = op.search;
            const replace = op.replace ?? '';
            const matchCount = search ? original.split(search).length - 1 : 0;

            if (matchCount === 0) {
              errors.push(`SEARCH not found in: ${path}`);
              console.log(`  ⚠️  SEARCH not found: ${path}`);
              continue;
            }
            if (matchCount > 1) {
              const firstLine = search.split('\n')[0];
              const lines = original.split('\n');
              const lineMatches: number[] = [];
              if (firstLine) {
                lines.forEach((line, index) => {
                  if (line.includes(firstLine)) {
                    lineMatches.push(index + 1);
                  }
                });
              }
              errors.push(`Multiple matches (${matchCount}) in ${path} at lines: ${lineMatches.join(', ')}`);
              console.log(`  ⚠️  AMBIGUOUS: ${matchCount} matches in ${path} at lines ${lineMatches.join(', ')}`);
              continue;
            }

            const newContent = original.replace(search, replace);
            if (!newContent.trim()) {
              unlinkSync(filePath);
              applied.push(`🗑️  Deleted (empty): ${path}`);
              console.log(`  🗑️  Deleted (empty): ${path}`);
            } else {
              writeFileSync(filePath, newContent, 'utf8');
              applied.push(`✏️  Modified: ${path}`);
              console.log(`  ✏️  Modified: ${path}`);
            }
          } else {
            writeFileSync(filePath, op.content ?? '', 'utf8');
            applied.push(`✏️  Modified: ${path}`);
            console.log(`  ✏️  Modified: ${path}`);
          }
          continue;
        }

        if (op.action === 'delete') {
          if (existsSync(filePath)) {
            unlinkSync(filePath);
            applied.push(`🗑️  Deleted: ${path}`);
            console.log(`  🗑️  Deleted: ${path}`);
          } else {
            errors.push(`File not found for delete: ${path}`);
            console.log(`  ⚠️  File not found: ${path}`);
          }
          continue;
        }

        errors.push(`Unknown action '${op.action}' for: ${path}`);
        console.log(`  ⚠️  Unknown action '${op.action}': ${path}`);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        errors.push(`Error with ${path}: ${message}`);
        console.log(`  ❌ Error: ${path} - ${message}`);
      }
    }

    context.applied_changes = applied;
    context.apply_errors = errors;

    console.log(`\n✅ Applied ${applied.length} changes`);
    if (errors.length) {
      console.log(`⚠️  ${errors.length} errors`);
    }
    console.log(`${'='.repeat(70)}\n`);

    return context;
  }
}

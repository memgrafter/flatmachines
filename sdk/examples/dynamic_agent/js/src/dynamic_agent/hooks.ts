import { FlatAgent, type MachineHooks, type AgentConfig } from '@memgrafter/flatmachines';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';
import { join } from 'path';

type Metrics = {
  agents_generated: number;
  agents_executed: number;
  supervisor_rejections: number;
  human_denials: number;
};

export class OTFAgentHooks implements MachineHooks {
  private metrics: Metrics = {
    agents_generated: 0,
    agents_executed: 0,
    supervisor_rejections: 0,
    human_denials: 0,
  };
  private configDir: string;
  private profilesFile: string;

  constructor(configDir: string) {
    this.configDir = configDir;
    this.profilesFile = join(configDir, 'profiles.yml');
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action === 'parse_generator_spec') {
      return this.parseGeneratorSpec(context);
    }
    if (action === 'parse_supervisor_review') {
      return this.parseSupervisorReview(context);
    }
    if (action === 'human_review_otf') {
      return this.humanReviewOtf(context);
    }
    if (action === 'otf_execute') {
      return this.otfExecute(context);
    }
    return context;
  }

  getMetrics(): Metrics {
    return { ...this.metrics };
  }

  private async prompt(question: string): Promise<string> {
    const rl = createInterface({ input, output });
    const answer = await rl.question(question);
    rl.close();
    return answer.trim();
  }

  private normalizeTemperature(value: unknown, fallback = 0.6): 0.6 | 1.0 {
    const parsed = typeof value === 'string' ? Number(value) : Number(value);
    const temp = Number.isFinite(parsed) ? parsed : fallback;
    return temp >= 0.8 ? 1.0 : 0.6;
  }

  private parseOutputFieldsBlock(text: string): Record<string, any> {
    const block = (text ?? '').trim();
    if (!block) return { content: 'The creative writing output' };

    if (block.startsWith('{')) {
      try {
        const parsed = JSON.parse(block);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, any>;
        }
      } catch {
        // fall through
      }
    }

    const fields: Record<string, string> = {};
    for (const line of block.split('\n')) {
      const match = line.match(/^\s*(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$/);
      if (match) {
        fields[match[1]] = match[2].trim();
      }
    }

    if (!Object.keys(fields).length) return { content: 'The creative writing output' };
    return fields;
  }

  private parseGeneratorSpec(context: Record<string, any>): Record<string, any> {
    const raw = String(context.raw_generator ?? '');

    let name: string | null = null;
    const systemLines: string[] = [];
    const userLines: string[] = [];
    const outputLines: string[] = [];
    let temperature: string | null = null;
    let section: 'system' | 'user' | 'output' | null = null;

    for (const line of raw.replace(/\r\n/g, '\n').split('\n')) {
      const nameMatch = line.match(/^\s*Name\s*:\s*(.*)$/i);
      if (nameMatch) {
        name = (nameMatch[1] ?? '').trim() || name;
        section = null;
        continue;
      }

      const systemMatch = line.match(/^\s*System Prompt\s*:\s*(.*)$/i);
      if (systemMatch) {
        section = 'system';
        const first = (systemMatch[1] ?? '').trimEnd();
        if (first) systemLines.push(first);
        continue;
      }

      const userMatch = line.match(/^\s*User Prompt Template\s*:\s*(.*)$/i);
      if (userMatch) {
        section = 'user';
        const first = (userMatch[1] ?? '').trimEnd();
        if (first) userLines.push(first);
        continue;
      }

      const tempMatch = line.match(/^\s*Temperature\s*:\s*(.*)$/i);
      if (tempMatch) {
        temperature = (tempMatch[1] ?? '').trim();
        section = null;
        continue;
      }

      const outputMatch = line.match(/^\s*Output Fields\s*:\s*(.*)$/i);
      if (outputMatch) {
        section = 'output';
        const first = (outputMatch[1] ?? '').trimEnd();
        if (first) outputLines.push(first);
        continue;
      }

      if (section === 'system') systemLines.push(line);
      else if (section === 'user') userLines.push(line);
      else if (section === 'output') outputLines.push(line);
    }

    let parsedUser = userLines.join('\n').trim() || '{{ input.task }}';
    if (!/<<\s*input\.task\s*>>/.test(parsedUser) && !/\{\{\s*input\.task\s*\}\}/.test(parsedUser)) {
      parsedUser = parsedUser ? `${parsedUser}\n\n{{ input.task }}` : '{{ input.task }}';
    }

    context.otf_name = (name ?? 'otf-agent').trim();
    context.otf_system = systemLines.join('\n').trim() || 'You are a helpful creative writer.';
    context.otf_user = parsedUser;
    context.otf_temperature = this.normalizeTemperature(temperature, 0.6);
    context.otf_output_fields = this.parseOutputFieldsBlock(outputLines.join('\n'));

    if (!raw.trim()) {
      context.supervisor_concerns = 'Generator returned empty text; used default fallbacks.';
    }

    return context;
  }

  private extractSupervisorBlock(text: string, label: string, nextLabel?: string): string {
    const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (nextLabel) {
      const escapedNext = nextLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`^\\s*${escapedLabel}\\s*:\\s*([\\s\\S]*?)^\\s*${escapedNext}\\s*:`, 'im');
      const match = text.match(regex);
      return (match?.[1] ?? '').trim();
    }
    const regex = new RegExp(`^\\s*${escapedLabel}\\s*:\\s*([\\s\\S]*)$`, 'im');
    const match = text.match(regex);
    return (match?.[1] ?? '').trim();
  }

  private parseSupervisorReview(context: Record<string, any>): Record<string, any> {
    const raw = String(context.raw_supervisor ?? '');
    const decisionMatch = raw.match(/^\s*DECISION\s*:\s*(APPROVE|REJECT)\b/im);

    let approved = false;
    if (decisionMatch) {
      approved = decisionMatch[1].toUpperCase() === 'APPROVE';
    } else if (/\breject\b/i.test(raw)) {
      approved = false;
    } else if (/\bapprove\b/i.test(raw)) {
      approved = true;
    }

    let analysis = this.extractSupervisorBlock(raw, 'ANALYSIS', 'CONCERNS');
    let concerns = this.extractSupervisorBlock(raw, 'CONCERNS');

    if (!analysis) analysis = raw.trim() || '(no supervisor analysis returned)';
    if (/^(none|\(none\)|n\/a|no concerns)$/i.test(concerns.trim())) {
      concerns = '';
    }
    if (!approved && !concerns.trim()) {
      concerns = 'Supervisor rejected the spec but did not provide explicit concerns.';
    }

    context.supervisor_approved = approved;
    context.supervisor_analysis = analysis;
    context.supervisor_concerns = concerns;
    return context;
  }

  private async humanReviewOtf(context: Record<string, any>): Promise<Record<string, any>> {
    console.log(`\n${'='.repeat(70)}`);
    console.log('OTF AGENT REVIEW');
    console.log('='.repeat(70));

    console.log('\n📋 ORIGINAL TASK:');
    console.log(`   ${context.task ?? '(unknown)'}`);

    const name = context.otf_name ?? 'unnamed';
    const system = context.otf_system ?? '(none)';
    const user = context.otf_user ?? '(none)';
    const temperature = context.otf_temperature ?? 'N/A';

    console.log(`\n🤖 GENERATED AGENT: ${name}`);
    console.log('-'.repeat(50));
    console.log(`Temperature: ${temperature}`);
    const systemText = system ? String(system) : '(none)';
    console.log(`\nSystem Prompt:\n${systemText}`);
    const taskText = context.task ? String(context.task) : '';
    const userText = user ? String(user) : '(none)';
    const userRendered = userText
      .replace(/<<\s*input\.task\s*>>/g, taskText)
      .replace(/\{\{\s*input\.task\s*\}\}/g, taskText);
    console.log(`\nUser Prompt Template:\n${userRendered}`);

    console.log(`\n${'-'.repeat(50)}`);
    const supervisorApproved = Boolean(context.supervisor_approved);

    if (supervisorApproved) {
      console.log('✅ SUPERVISOR APPROVED');
    } else {
      console.log('❌ SUPERVISOR REJECTED');
      this.metrics.supervisor_rejections += 1;
    }

    console.log(`\n📊 ANALYSIS:\n${context.supervisor_analysis ?? '(none)'}`);
    if (context.supervisor_concerns) {
      console.log(`\n⚠️  CONCERNS:\n${context.supervisor_concerns}`);
    }

    console.log('-'.repeat(50));

    if (supervisorApproved) {
      console.log('\nThe supervisor approved this agent.');
      const response = await this.prompt('Your decision: [a]pprove / [d]eny / [q]uit: ');
      const normalized = response.toLowerCase();

      if (normalized === '' || normalized === 'a' || normalized === 'approve') {
        context.human_approved = true;
        context.human_acknowledged = true;
        console.log('✓ Approved! Agent will be executed.');
      } else if (normalized === 'q' || normalized === 'quit') {
        throw new Error('Execution cancelled by user.');
      } else {
        context.human_approved = false;
        context.human_acknowledged = true;
        this.metrics.human_denials += 1;
        console.log('✗ Denied. Will regenerate agent.');
      }
    } else {
      console.log('\nThe supervisor rejected this agent. You can only acknowledge.');
      const response = await this.prompt('Press Enter to acknowledge and regenerate, or "q" to quit: ');
      const normalized = response.toLowerCase();

      if (normalized === 'q' || normalized === 'quit') {
        throw new Error('Execution cancelled by user.');
      }

      context.human_approved = false;
      context.human_acknowledged = true;
      console.log('→ Acknowledged. Will regenerate agent with feedback.');
    }

    console.log(`${'='.repeat(70)}\n`);
    return context;
  }

  private async otfExecute(context: Record<string, any>): Promise<Record<string, any>> {
    const name = context.otf_name ?? 'otf-agent';
    const system = context.otf_system ?? 'You are a helpful creative writer.';
    const user = context.otf_user ?? '{{ input.task }}';
    const temperature = this.normalizeTemperature(context.otf_temperature ?? 0.6, 0.6);

    console.log(`\n${'='.repeat(70)}`);
    console.log(`🚀 EXECUTING OTF AGENT: ${name}`);
    console.log('='.repeat(70));

    const profileName = temperature === 0.6 ? 'creative' : 'default';
    const normalizedUser = String(user)
      .replace(/<<\s*input\.task\s*>>/g, '{{ input.task }}')
      .trim();

    // Keep execution plain-text: do not force output schema/json mode.
    const agentConfig: AgentConfig = {
      spec: 'flatagent',
      spec_version: '2.0.0',
      data: {
        name,
        model: profileName,
        system: String(system),
        user: normalizedUser,
      },
    };

    try {
      const agent = new FlatAgent({
        config: agentConfig,
        configDir: this.configDir,
        profilesFile: this.profilesFile,
      });
      this.metrics.agents_generated += 1;

      const result: any = await agent.call({ task: context.task ?? '' });

      if (result?.error) {
        const errorType = result.error.error_type ?? result.error.type ?? 'AgentError';
        const message = result.error.message ?? String(result.error);
        const errorText = `${errorType}: ${message}`;
        context.otf_result = { error: errorText };
        console.log(`\n❌ Error: ${errorText}`);
        console.log(`${'='.repeat(70)}\n`);
        return context;
      }

      this.metrics.agents_executed += 1;
      const content = String(result?.content ?? '').trim();
      context.otf_result = { content: content || '(empty response)' };

      console.log('\n📝 OUTPUT:');
      console.log('-'.repeat(50));
      console.log(context.otf_result.content);
      console.log('-'.repeat(50));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      context.otf_result = { error: message };
      console.log(`\n❌ Error: ${message}`);
    }

    console.log(`${'='.repeat(70)}\n`);
    return context;
  }
}

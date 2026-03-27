import { join } from 'path';
import { loadAgent, updateAgentPrompts, createLogger } from './utils.js';
import type { AgentConfig } from '@memgrafter/flatagents';

export type PromptCandidate = {
  system_prompt: string;
  user_prompt: string;
  changes_made: string[];
  factual_knowledge: string[];
  strategies_preserved: string[];
};

export class PromptEvolver {
  private reflectiveUpdater;
  private logger;
  private stats = { reflective_updater_calls: 0, reflective_updater_cost: 0 };

  constructor(private configDir: string, options: { verbose?: boolean } = {}) {
    const agentsDir = join(configDir, 'agents');
    this.reflectiveUpdater = loadAgent(join(agentsDir, 'reflective_updater.yml'));
    this.logger = createLogger(options.verbose ?? true);
    this.logger.info('PromptEvolver initialized with reflective updater agent');
  }

  async reflectiveUpdate(currentConfig: AgentConfig, traces: Array<Record<string, any>>): Promise<PromptCandidate> {
    const data = currentConfig.data ?? {};
    const currentSystem = data.system ?? '';
    const currentUser = data.user ?? '';

    const currentInstruction = `SYSTEM PROMPT:\n${currentSystem}\n\nUSER PROMPT TEMPLATE:\n${currentUser}`;

    this.stats.reflective_updater_calls += 1;
    const result = await this.reflectiveUpdater.call({
      current_instruction: currentInstruction,
      traces,
    });

    const output = result.output ?? {};
    const newInstruction = output.new_instruction ?? '';
    const { systemPrompt, userPrompt } = this.parseInstruction(newInstruction, currentSystem, currentUser);

    return {
      system_prompt: systemPrompt,
      user_prompt: userPrompt,
      changes_made: output.corrections_made ?? [],
      factual_knowledge: output.factual_knowledge_extracted ?? [],
      strategies_preserved: output.strategies_preserved ?? [],
    };
  }

  parseInstruction(newInstruction: string, fallbackSystem: string, fallbackUser: string): { systemPrompt: string; userPrompt: string } {
    const systemMatch = newInstruction.match(/SYSTEM PROMPT:\s*([\s\S]*?)(?=USER PROMPT|USER TEMPLATE|$)/i);
    const userMatch = newInstruction.match(/USER (?:PROMPT|TEMPLATE)[:\s]*([\s\S]*)$/i);

    let systemPrompt = fallbackSystem;
    let userPrompt = fallbackUser;

    if (systemMatch && userMatch) {
      systemPrompt = systemMatch[1].trim();
      userPrompt = userMatch[1].trim();
    } else if (/```SYSTEM|'''SYSTEM/i.test(newInstruction)) {
      const blocks = newInstruction.match(/['"`]{3}([\s\S]*?)['"`]{3}/g) ?? [];
      if (blocks.length >= 2) {
        systemPrompt = (blocks[0] ?? '').replace(/['"`]{3}/g, '').trim();
        userPrompt = (blocks[1] ?? '').replace(/['"`]{3}/g, '').trim();
      } else if (blocks.length === 1) {
        systemPrompt = (blocks[0] ?? '').replace(/['"`]{3}/g, '').trim();
      }
    } else if (newInstruction.length > 100) {
      systemPrompt = newInstruction.trim();
    }

    systemPrompt = systemPrompt.replace(/^SYSTEM PROMPT:?\s*/i, '').trim();
    userPrompt = userPrompt.replace(/^USER (?:PROMPT|TEMPLATE):?\s*/i, '').trim();

    if (!systemPrompt || systemPrompt.length < 20) {
      systemPrompt = fallbackSystem;
    }
    if (!userPrompt || userPrompt.length < 10) {
      userPrompt = fallbackUser;
    }

    return { systemPrompt, userPrompt };
  }

  createCandidateConfig(originalConfig: AgentConfig, candidate: PromptCandidate): AgentConfig {
    return updateAgentPrompts(originalConfig, candidate.system_prompt, candidate.user_prompt);
  }

  getStats(): Record<string, number> {
    return { ...this.stats };
  }
}

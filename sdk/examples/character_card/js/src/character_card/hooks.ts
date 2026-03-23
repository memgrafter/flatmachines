import { FlatAgent, type MachineHooks } from '@memgrafter/flatmachines';
import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { createInterface } from 'readline/promises';
import { stdin as input, stdout as output } from 'process';
import { parseCard } from './card_parser.js';

type PersonaFile = {
  name?: string;
  description?: string;
};

type Message = {
  role: string;
  content: string;
};

type Options = {
  cardPath: string;
  userName?: string;
  noSystemPrompt?: boolean;
  userPersona?: string | null;
  personaFile?: string | null;
  messagesFile?: string | null;
  autoUser?: boolean;
  scriptResponses?: string[];
  maxTurns?: number | null;
  configDir: string;
};

export class CharacterCardHooks implements MachineHooks {
  private cardPath: string;
  private userName: string;
  private noSystemPrompt: boolean;
  private userPersona?: string | null;
  private personaFile?: string | null;
  private messagesFile?: string | null;
  private autoUser: boolean;
  private scriptResponses: string[];
  private scriptIndex = 0;
  private maxTurns?: number | null;
  private turnCount = 0;
  private cardData: Record<string, any> | null = null;
  private userAgent: FlatAgent | null = null;
  private configDir: string;

  constructor(options: Options) {
    this.cardPath = options.cardPath;
    this.userName = options.userName ?? 'User';
    this.noSystemPrompt = Boolean(options.noSystemPrompt);
    this.userPersona = options.userPersona ?? null;
    this.personaFile = options.personaFile ?? null;
    this.messagesFile = options.messagesFile ?? null;
    this.autoUser = Boolean(options.autoUser);
    this.scriptResponses = options.scriptResponses ? [...options.scriptResponses] : [];
    this.maxTurns = options.maxTurns ?? null;
    this.configDir = options.configDir;
  }

  async onAction(action: string, context: Record<string, any>): Promise<Record<string, any>> {
    if (action === 'load_card') {
      return this.loadCard(context);
    }
    if (action === 'show_greeting') {
      return this.showGreeting(context);
    }
    if (action === 'get_user_input') {
      return this.getUserInput(context);
    }
    if (action === 'update_chat_history') {
      return this.updateChatHistory(context);
    }
    return context;
  }

  private loadPersona(): { name: string; persona?: string | null } {
    let name = this.userName;
    let persona = this.userPersona ?? null;

    if (this.personaFile && existsSync(this.personaFile)) {
      try {
        const data = JSON.parse(readFileSync(this.personaFile, 'utf8')) as PersonaFile;
        name = data.name ?? name;
        persona = data.description ?? persona;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.warn(`Failed to load persona file: ${message}`);
      }
    }

    return { name, persona };
  }

  private loadMessages(): Message[] {
    if (!this.messagesFile || !existsSync(this.messagesFile)) {
      return [];
    }

    try {
      const data = JSON.parse(readFileSync(this.messagesFile, 'utf8')) as any;
      if (Array.isArray(data)) {
        return data as Message[];
      }
      if (data && Array.isArray(data.messages)) {
        return data.messages as Message[];
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`Failed to load messages file: ${message}`);
    }

    return [];
  }

  private loadCard(context: Record<string, any>): Record<string, any> {
    this.cardData = parseCard(this.cardPath);

    const { name: userName, persona } = this.loadPersona();
    this.userName = userName;

    context.card_name = this.cardData.name;
    context.card_description = this.cardData.description;
    context.card_personality = this.cardData.personality;
    context.card_scenario = this.cardData.scenario;
    context.card_system_prompt = this.cardData.system_prompt;
    context.card_first_mes = this.cardData.first_mes;
    context.card_mes_example = this.cardData.mes_example;
    context.post_history_instructions = this.cardData.post_history_instructions;

    context.user_name = userName;
    context.user_persona = persona;
    context.no_system_prompt = this.noSystemPrompt;
    context.auto_user = this.autoUser;

    context.messages = this.loadMessages();

    if (this.autoUser) {
      const agentPath = join(this.configDir, 'user_agent.yml');
      this.userAgent = new FlatAgent({ config: agentPath, configDir: this.configDir });
    }

    console.log('-'.repeat(60));
    console.log(`Character: ${this.cardData.name}`);
    if (this.cardData.creator) {
      console.log(`By: ${this.cardData.creator}`);
    }
    console.log(`User: ${userName}`);
    if (persona) {
      const preview = persona.length > 100 ? `${persona.slice(0, 100)}...` : persona;
      console.log(`Persona: ${preview}`);
    }
    if (context.messages.length) {
      console.log(`Injected messages: ${context.messages.length}`);
    }
    if (this.autoUser) {
      const maxStr = this.maxTurns ? `, max ${this.maxTurns} turns` : '';
      console.log(`Mode: Auto-user (LLM-driven${maxStr})`);
    } else if (this.scriptResponses.length) {
      console.log(`Mode: Scripted (${this.scriptResponses.length} responses)`);
    }
    console.log('-'.repeat(60));

    return context;
  }

  private showGreeting(context: Record<string, any>): Record<string, any> {
    if (context.messages && context.messages.length) {
      console.log('Using injected messages');
      const recent = context.messages.slice(-4);
      for (const msg of recent) {
        const role = msg.role === 'user' ? context.user_name : context.card_name;
        const preview = msg.content.length > 100 ? `${msg.content.slice(0, 100)}...` : msg.content;
        console.log(`${role}: ${preview}`);
      }
      console.log();
      return context;
    }

    const firstMes = context.card_first_mes ?? '';
    const name = context.card_name ?? 'Character';

    if (firstMes) {
      context.messages.push({ role: 'user', content: '[Start]' });
      context.messages.push({ role: 'assistant', content: firstMes });
      console.log(`\n${name}: ${firstMes}\n`);
    }

    return context;
  }

  private async generateUserResponse(context: Record<string, any>): Promise<string> {
    if (!this.userAgent) {
      return '/quit';
    }

    const result = await this.userAgent.call({
      user_name: context.user_name ?? 'User',
      user_persona: context.user_persona ?? '',
      card_name: context.card_name ?? 'Character',
      card_description: context.card_description ?? '',
      messages: context.messages ?? [],
    });

    if (result.output && typeof result.output.response === 'string') {
      return result.output.response;
    }
    if (typeof result.content === 'string' && result.content.trim().length > 0) {
      return result.content.trim();
    }
    return '/quit';
  }

  private async promptUser(): Promise<string> {
    const rl = createInterface({ input, output });
    const answer = await rl.question(`${this.userName}: `);
    rl.close();
    return answer.trim();
  }

  private async getUserInput(context: Record<string, any>): Promise<Record<string, any>> {
    if (this.scriptResponses.length && this.scriptIndex < this.scriptResponses.length) {
      const response = this.scriptResponses[this.scriptIndex];
      this.scriptIndex += 1;
      console.log(`${this.userName}: ${response}`);
      context.user_message = response;
      return context;
    }

    if (this.autoUser && this.userAgent) {
      if (this.maxTurns && this.maxTurns > 0 && this.turnCount >= this.maxTurns) {
        console.log(`Reached max turns: ${this.maxTurns}`);
        context.user_message = '/quit';
        return context;
      }

      if (this.maxTurns === 0 && this.turnCount > 0) {
        await new Promise(resolve => setTimeout(resolve, 2000));
      }

      this.turnCount += 1;

      try {
        const response = await this.generateUserResponse(context);
        console.log(`${this.userName}: ${response}`);
        context.user_message = response;
        return context;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.warn(`Auto-user error: ${message}`);
        context.user_message = '/quit';
        return context;
      }
    }

    try {
      const answer = await this.promptUser();
      context.user_message = answer || '/quit';
    } catch {
      context.user_message = '/quit';
      console.log();
    }

    return context;
  }

  private updateChatHistory(context: Record<string, any>): Record<string, any> {
    const userMsg = context.user_message ?? '';
    const assistantMsg = context.assistant_message ?? '';
    const name = context.card_name ?? 'Character';

    context.messages.push({ role: 'user', content: userMsg });
    context.messages.push({ role: 'assistant', content: assistantMsg });

    console.log(`\n${name}: ${assistantMsg}\n`);

    return context;
  }
}

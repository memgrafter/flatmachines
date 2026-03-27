import { FlatAgent } from '@memgrafter/flatagents';
import Ajv, { ValidateFunction } from 'ajv';

type ParsingConfig = Record<string, { pattern: string; type?: string }>;

type MDAPConfig = {
  k_margin: number;
  max_candidates: number;
  max_steps: number;
  max_response_tokens: number;
};

type MDAPMetrics = {
  total_samples: number;
  total_red_flags: number;
  red_flags_by_reason: Record<string, number>;
  samples_per_step: number[];
};

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`;
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  const entries = keys.map(key => `${JSON.stringify(key)}:${stableStringify(obj[key])}`);
  return `{${entries.join(',')}}`;
}

export class MDAPOrchestrator {
  private agent: FlatAgent;
  config: MDAPConfig;
  metrics: MDAPMetrics;
  private parsingConfig: ParsingConfig;
  private validationSchema?: Record<string, any>;
  private patterns: Record<string, { regex: RegExp; type: string }> = {};
  private validator?: ValidateFunction;

  constructor(agent: FlatAgent, config?: Partial<MDAPConfig>) {
    this.agent = agent;

    const metadata = (agent as any).config?.metadata ?? {};
    const mdapConfig = metadata.mdap ?? {};

    this.config = {
      k_margin: config?.k_margin ?? mdapConfig.k_margin ?? 3,
      max_candidates: config?.max_candidates ?? mdapConfig.max_candidates ?? 10,
      max_steps: config?.max_steps ?? mdapConfig.max_steps ?? 100,
      max_response_tokens: config?.max_response_tokens ?? mdapConfig.max_response_tokens ?? 2048,
    };

    this.metrics = {
      total_samples: 0,
      total_red_flags: 0,
      red_flags_by_reason: {},
      samples_per_step: [],
    };

    this.parsingConfig = metadata.parsing ?? {};
    this.validationSchema = metadata.validation ?? undefined;

    for (const [fieldName, fieldConfig] of Object.entries(this.parsingConfig)) {
      if (fieldConfig.pattern) {
        this.patterns[fieldName] = {
          regex: new RegExp(fieldConfig.pattern, 's'),
          type: fieldConfig.type ?? 'str',
        };
      }
    }

    if (this.validationSchema) {
      const ajv = new Ajv({ allErrors: true });
      this.validator = ajv.compile(this.validationSchema);
    }
  }

  private parseResponse(content: string): Record<string, any> | null {
    if (!Object.keys(this.patterns).length) {
      return null;
    }

    const result: Record<string, any> = {};
    for (const [fieldName, { regex, type }] of Object.entries(this.patterns)) {
      const match = regex.exec(content);
      if (!match) {
        return null;
      }
      const value = match[1];
      if (type === 'json') {
        try {
          result[fieldName] = JSON.parse(value);
        } catch {
          return null;
        }
      } else if (type === 'int') {
        const parsed = Number.parseInt(value, 10);
        if (Number.isNaN(parsed)) {
          return null;
        }
        result[fieldName] = parsed;
      } else {
        result[fieldName] = value;
      }
    }

    return result;
  }

  private validateParsed(parsed: Record<string, any> | null): boolean {
    if (!parsed) return false;
    if (!this.validator) return true;
    return Boolean(this.validator(parsed));
  }

  private recordRedFlag(reason: string): void {
    this.metrics.total_red_flags += 1;
    this.metrics.red_flags_by_reason[reason] = (this.metrics.red_flags_by_reason[reason] ?? 0) + 1;
  }

  private checkRedFlags(content: string, parsed: Record<string, any> | null): string | null {
    if (!parsed) {
      return 'format_error';
    }
    if (!this.validateParsed(parsed)) {
      return 'validation_failed';
    }
    const estimatedTokens = Math.floor(content.length / 4);
    if (estimatedTokens > this.config.max_response_tokens) {
      return 'length_exceeded';
    }
    return null;
  }

  async sampleOnce(inputData: Record<string, any>): Promise<{ content: string; parsed: Record<string, any> | null }> {
    const result = await this.agent.call(inputData);
    const content = result.content ?? '';
    const parsed = this.parseResponse(content);
    return { content, parsed };
  }

  async firstToAheadByK(inputData: Record<string, any>): Promise<{ result: Record<string, any> | null; samples: number }> {
    const votes = new Map<string, number>();
    const responses = new Map<string, Record<string, any>>();
    let numSamples = 0;

    for (let i = 0; i < this.config.max_candidates; i += 1) {
      try {
        const { content, parsed } = await this.sampleOnce(inputData);
        numSamples += 1;
        this.metrics.total_samples += 1;

        const flagReason = this.checkRedFlags(content, parsed);
        if (flagReason) {
          this.recordRedFlag(flagReason);
          continue;
        }

        if (!parsed) {
          continue;
        }

        const key = stableStringify(parsed);
        votes.set(key, (votes.get(key) ?? 0) + 1);
        responses.set(key, parsed);

        const count = votes.get(key) ?? 0;
        if (count >= this.config.k_margin) {
          return { result: parsed, samples: numSamples };
        }

        if (votes.size >= 2) {
          const sorted = Array.from(votes.entries()).sort((a, b) => b[1] - a[1]);
          if (sorted[0][1] - sorted[1][1] >= this.config.k_margin) {
            const winner = responses.get(sorted[0][0]) ?? null;
            return { result: winner, samples: numSamples };
          }
        }
      } catch {
        continue;
      }
    }

    if (votes.size > 0) {
      const winner = Array.from(votes.entries()).sort((a, b) => b[1] - a[1])[0][0];
      return { result: responses.get(winner) ?? null, samples: numSamples };
    }

    return { result: null, samples: numSamples };
  }
}

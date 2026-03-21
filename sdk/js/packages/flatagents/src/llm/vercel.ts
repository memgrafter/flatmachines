/**
 * VercelAIBackend — LLM backend using Vercel AI SDK.
 *
 * Supports multiple providers through Vercel AI SDK:
 * - OpenAI
 * - Anthropic
 * - Cerebras
 * - OpenAI-compatible (Groq, Together, Fireworks, etc.)
 */

import { generateText, LanguageModel } from 'ai';
import { createOpenAI } from '@ai-sdk/openai';
import { createAnthropic } from '@ai-sdk/anthropic';
import { createCerebras } from '@ai-sdk/cerebras';
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import { LLMBackend, LLMBackendConfig, LLMOptions, Message } from './types';

// Known provider base URLs for OpenAI-compatible providers
const PROVIDER_BASE_URLS: Record<string, string> = {
  cerebras: 'https://api.cerebras.ai/v1',
  groq: 'https://api.groq.com/openai/v1',
  together: 'https://api.together.xyz/v1',
  fireworks: 'https://api.fireworks.ai/inference/v1',
  deepseek: 'https://api.deepseek.com/v1',
  mistral: 'https://api.mistral.ai/v1',
  perplexity: 'https://api.perplexity.ai',
};

export class VercelAIBackend implements LLMBackend {
  totalCost = 0;
  totalApiCalls = 0;

  private model: LanguageModel;

  constructor(config: LLMBackendConfig) {
    this.model = this.createModel(config);
  }

  private createModel(config: LLMBackendConfig): LanguageModel {
    const { provider = 'openai', name: modelName, apiKey, baseURL } = config;
    const providerLower = provider.toLowerCase();
    const providerUpper = provider.toUpperCase();

    // Get API key from config or environment
    const resolvedApiKey = apiKey ?? process.env[`${providerUpper}_API_KEY`];
    const resolvedBaseURL = baseURL ?? process.env[`${providerUpper}_BASE_URL`] ?? PROVIDER_BASE_URLS[providerLower];

    if (providerLower === 'openai') {
      const openai = createOpenAI({ apiKey: resolvedApiKey });
      return openai.chat(modelName);
    }

    if (providerLower === 'anthropic') {
      const anthropic = createAnthropic({ apiKey: resolvedApiKey });
      return anthropic(modelName);
    }

    if (providerLower === 'cerebras') {
      const cerebras = createCerebras({ apiKey: resolvedApiKey });
      return cerebras(modelName);
    }

    // Use createOpenAICompatible for any other OpenAI-compatible provider
    if (!resolvedBaseURL) {
      throw new Error(
        `Unknown provider "${provider}". Set ${providerUpper}_BASE_URL environment variable.`
      );
    }

    const compatible = createOpenAICompatible({
      name: providerLower,
      baseURL: resolvedBaseURL,
      headers: {
        Authorization: `Bearer ${resolvedApiKey}`,
      },
    });

    return compatible(modelName);
  }

  async call(messages: Message[], options?: LLMOptions): Promise<string> {
    const response = await this.callRaw(messages, options);
    return response.text;
  }

  async callRaw(messages: Message[], options?: LLMOptions): Promise<any> {
    this.totalApiCalls++;

    // Extract system and user messages
    const systemMessage = messages.find(m => m.role === 'system');
    const userMessage = messages.find(m => m.role === 'user');

    const generateParams: any = {
      model: this.model,
      system: systemMessage?.content,
      prompt: userMessage?.content,
    };

    // Apply options
    if (options?.temperature !== undefined) generateParams.temperature = options.temperature;
    if (options?.max_tokens !== undefined) generateParams.maxTokens = options.max_tokens;
    if (options?.top_p !== undefined) generateParams.topP = options.top_p;
    if (options?.frequency_penalty !== undefined) generateParams.frequencyPenalty = options.frequency_penalty;
    if (options?.presence_penalty !== undefined) generateParams.presencePenalty = options.presence_penalty;

    const response = await generateText(generateParams);

    // Track cost if available (provider-dependent)
    // Note: Vercel AI SDK doesn't expose cost directly, this would need provider-specific handling
    // this.totalCost += response.usage?.cost ?? 0;

    return response;
  }
}
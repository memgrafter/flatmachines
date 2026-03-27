/**
 * LLM backend types.
 *
 * Matches flatagents-runtime.d.ts specification.
 * These types abstract over different LLM providers.
 */

export interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  tool_call_id?: string;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string; // JSON string
  };
}

export interface LLMOptions {
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  top_k?: number;
  frequency_penalty?: number;
  presence_penalty?: number;
  seed?: number;
  tools?: ToolDefinition[];
  response_format?: { type: 'json_object' } | { type: 'text' };
}

export interface ToolDefinition {
  type: 'function';
  function: {
    name: string;
    description?: string;
    parameters?: Record<string, any>; // JSON Schema
  };
}

/**
 * Abstraction over LLM providers.
 * See flatagents-runtime.d.ts for canonical definition.
 */
export interface LLMBackend {
  /** Total cost accumulated across all calls. */
  totalCost: number;

  /** Total API calls made. */
  totalApiCalls: number;

  /**
   * Call LLM and return content string.
   */
  call(messages: Message[], options?: LLMOptions): Promise<string>;

  /**
   * Call LLM and return raw provider response.
   */
  callRaw(messages: Message[], options?: LLMOptions): Promise<any>;
}

/**
 * Configuration for creating an LLM backend.
 */
export interface LLMBackendConfig {
  provider: string;
  name: string;
  apiKey?: string;
  baseURL?: string;
}
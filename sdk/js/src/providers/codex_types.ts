/**
 * Codex backend types — ports Python SDK's openai_codex_types.py
 */

export interface CodexOAuthCredential {
  access: string;
  refresh: string;
  expires: number;
  account_id?: string;
}

export interface CodexUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_tokens: number;
}

export interface CodexToolCall {
  id: string;
  name: string;
  arguments_json: string;
}

export interface CodexResult {
  content: string;
  tool_calls: CodexToolCall[];
  usage: CodexUsage;
  finish_reason?: string;
  status?: string;
  raw_events: Array<Record<string, any>>;
  response_headers: Record<string, string>;
  response_status_code?: number;
  request_meta: Record<string, any>;
}

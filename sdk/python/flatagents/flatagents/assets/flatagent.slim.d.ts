export const SPEC_VERSION = "2.4.0";
export interface AgentWrapper {
    spec: "flatagent";
    spec_version: string;
    data: AgentData;
    metadata?: Record<string, any>;
}
export interface AgentData {
    name?: string;
    model: string | ModelConfig | ProfiledModelConfig;
    system: string;
    user: string;
    instruction_suffix?: string;
    output?: OutputSchema;
    mcp?: MCPConfig;
    tools?: ToolDefinition[];
}
export interface ToolDefinition {
    type: "function";
    function: {
        name: string;
        description?: string;
        parameters?: Record<string, any>;
    };
}
export interface MCPConfig {
    servers: Record<string, MCPServerDef>;
    tool_filter?: ToolFilter;
    tool_prompt: string;
}
export interface MCPServerDef {
    command?: string;
    args?: string[];
    env?: Record<string, string>;
    server_url?: string;
    headers?: Record<string, string>;
    timeout?: number;
}
export interface ToolFilter {
    allow?: string[];
    deny?: string[];
}
export interface OAuthConfig {
    provider?: "openai-codex" | string;
    auth_file?: string;
    refresh?: boolean;
    originator?: string;
    timeout_seconds?: number;
    max_retries?: number;
    token_url?: string;
    client_id?: string;
}
export interface ModelConfig {
    name: string;
    provider?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    top_k?: number;
    frequency_penalty?: number;
    presence_penalty?: number;
    seed?: number;
    base_url?: string;
    backend?: "litellm" | "aisuite" | "codex";
    api?: string;
    oauth?: OAuthConfig;
}
export interface ProfiledModelConfig extends Partial<ModelConfig> {
    profile: string;
}
export type OutputSchema = Record<string, OutputFieldDef>;
export interface OutputFieldDef {
    type: "str" | "int" | "float" | "bool" | "json" | "list" | "object";
    description?: string;
    enum?: string[];
    required?: boolean;
    items?: OutputFieldDef;
    properties?: OutputSchema;
}
export type FlatagentsConfig = AgentWrapper;

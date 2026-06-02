export const SPEC_VERSION = "4.2.1";
import { PromptWrapper, PromptData, PromptRef, OutputSchema, MCPConfig, ToolDefinition, } from "./prompt";
import { ProfileWrapper, ProfileData, ProfileRef, ModelConfig, OAuthConfig, } from "./profile";
export interface AgentWrapper {
    spec: "flatagent";
    spec_version: string;
    data: AgentData;
    metadata?: Record<string, any>;
}
export interface AgentData {
    prompt: PromptRef;
    profile: ProfileRef;
}
export { PromptWrapper, PromptData, PromptRef, ProfileWrapper, ProfileData, ProfileRef, OutputSchema, MCPConfig, ToolDefinition, ModelConfig, OAuthConfig, };
export type FlatagentsConfig = AgentWrapper;

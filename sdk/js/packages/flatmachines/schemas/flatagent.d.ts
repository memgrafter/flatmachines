/**
 * FlatAgent Configuration Schema
 * =============================
 *
 * FlatAgent is a convenience bundle of exactly two things:
 * - a prompt
 * - a profile
 *
 * Each may be provided inline or by reference.
 */

export const SPEC_VERSION = "4.2.0";

import {
  PromptWrapper,
  PromptData,
  PromptRef,
  OutputSchema,
  MCPConfig,
  ToolDefinition,
} from "./prompt";
import {
  ProfileWrapper,
  ProfileData,
  ProfileRef,
  ModelConfig,
  OAuthConfig,
} from "./profile";

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

export {
  PromptWrapper,
  PromptData,
  PromptRef,
  ProfileWrapper,
  ProfileData,
  ProfileRef,
  OutputSchema,
  MCPConfig,
  ToolDefinition,
  ModelConfig,
  OAuthConfig,
};

export type FlatagentsConfig = AgentWrapper;

/**
 * FlatAgents Model Profiles Schema
 * =================================
 *
 * Model profiles provide reusable model configurations that agents can reference
 * by name. This enables centralized model management and easy switching between
 * configurations (e.g., development vs production, fast vs quality).
 *
 * STRUCTURE:
 * ----------
 * spec           - Fixed string "flatprofiles"
 * spec_version   - Semver string
 * data           - Profile definitions and settings
 * metadata       - Extensibility layer
 *
 * DERIVED SCHEMAS:
 * ----------------
 * This file (/profiles.d.ts) is the SOURCE OF TRUTH for all profile schemas.
 * Other schemas (JSON Schema, etc.) are DERIVED from this file using scripts.
 * See: /scripts/generate-spec-assets.ts
 *
 * PROFILE RESOLUTION ORDER (low to high priority):
 * ------------------------------------------------
 * 1. default profile from profiles.yml (fallback when agent has no model config)
 * 2. Named profile from agent's model: "profile-name"
 * 3. Inline overrides from agent's model: { profile: "name", temperature: 0.5 }
 * 4. override profile from profiles.yml (trumps all agent configs)
 *
 * AGENT USAGE:
 * ------------
 * String shorthand - profile lookup:
 *
 *   data:
 *     model: "fast-cheap"
 *
 * Profile with overrides:
 *
 *   data:
 *     model:
 *       profile: "fast-cheap"
 *       temperature: 0.9
 *
 * Inline config (no profile):
 *
 *   data:
 *     model:
 *       provider: cerebras
 *       name: zai-glm-4.6
 *       temperature: 0.6
 *
 * EXAMPLE CONFIGURATION:
 * ----------------------
 *
 *   spec: flatprofiles
 *   spec_version: "0.7.0"
 *
 *   data:
 *     model_profiles:
 *       fast-cheap:
 *         provider: cerebras
 *         name: zai-glm-4.6
 *         temperature: 0.6
 *         max_tokens: 2048
 *
 *       smart-expensive:
 *         provider: anthropic
 *         name: claude-3-opus-20240229
 *         temperature: 0.3
 *         max_tokens: 4096
 *
 *       local-dev:
 *         provider: ollama
 *         name: llama3
 *         base_url: http://localhost:11434
 *         temperature: 0.7
 *
 *       deterministic:
 *         provider: openai
 *         name: gpt-4-turbo
 *         temperature: 0
 *         seed: 42
 *
 *     default: fast-cheap
 *     # override: smart-expensive
 *
 *   metadata:
 *     description: "Model profiles for the project"
 *
 * PROFILESDATA FIELDS:
 * --------------------
 * model_profiles - Named model profiles, keyed by profile name
 * default        - Default profile name, used when agent has no model config
 * override       - Override profile name, trumps all agent model configs
 *
 * MODELPROFILECONFIG FIELDS:
 * --------------------------
 * Defines all parameters for an LLM model.
 * name              - Model name (e.g., "gpt-4", "zai-glm-4.6", "claude-3-opus-20240229")
 * provider          - Provider name (e.g., "openai", "anthropic", "cerebras", "ollama")
 * temperature       - Sampling temperature (0.0 to 2.0)
 * max_tokens        - Maximum tokens to generate
 * top_p             - Nucleus sampling parameter (0.0 to 1.0)
 * top_k             - Top-k sampling parameter
 * frequency_penalty - Frequency penalty (-2.0 to 2.0)
 * presence_penalty  - Presence penalty (-2.0 to 2.0)
 * seed              - Random seed for reproducibility
 * base_url          - Custom base URL for the API (e.g., for local models or proxies)
 * stream            - Enable streaming responses (default: false)
 * backend           - Runtime backend override (litellm, aisuite, codex)
 * oauth             - OAuth settings (used by codex backend)
 */

export const SPEC_VERSION = "2.4.0";

export interface ProfilesWrapper {
  spec: "flatprofiles";
  spec_version: string;
  data: ProfilesData;
  metadata?: Record<string, any>;
}

export interface ProfilesData {
  model_profiles: Record<string, ModelProfileConfig>;
  default?: string;
  override?: string;
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

export interface ModelProfileConfig {
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
  stream?: boolean;
  backend?: "litellm" | "aisuite" | "codex";
  api?: string;
  oauth?: OAuthConfig;
}

export type FlatprofilesConfig = ProfilesWrapper;

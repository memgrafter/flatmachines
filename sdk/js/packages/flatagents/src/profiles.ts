/**
 * Model profile management.
 *
 * Provides centralized model configuration through profiles.yml files.
 * Profiles enable easy switching between model configurations (e.g., dev vs prod).
 *
 * Resolution order (low to high priority):
 * 1. default profile (fallback)
 * 2. Named profile from agent's model field
 * 3. Inline overrides from agent's model field
 * 4. override profile (trumps all)
 */

import { readFileSync, existsSync } from "fs";
import { join, dirname } from "path";
import yaml from "yaml";
import type { ModelConfig, ModelProfileConfig, ProfilesConfig } from "./types";

// Cache loaded profile managers by directory
const profileManagerCache: Map<string, ProfileManager> = new Map();

/**
 * Manages model profiles from profiles.yml files.
 *
 * Resolution order (low to high priority):
 * 1. default profile (fallback)
 * 2. Named profile from agent's model field
 * 3. Inline overrides from agent's model field
 * 4. override profile (trumps all)
 *
 * @example
 * ```typescript
 * const manager = new ProfileManager("config/profiles.yml");
 * const config = manager.resolveModelConfig("fast-cheap");
 * console.log(config);
 * // { provider: 'cerebras', name: 'zai-glm-4.6', temperature: 0.6 }
 * ```
 */
export class ProfileManager {
  private profiles: Record<string, ModelProfileConfig> = {};
  private defaultProfile: string | undefined;
  private overrideProfile: string | undefined;
  readonly profilesFile: string | undefined;

  constructor(profilesFile?: string) {
    this.profilesFile = profilesFile;
    if (profilesFile) {
      this.loadProfiles(profilesFile);
    }
  }

  /**
   * Get or create a ProfileManager for a directory.
   * Caches instances by directory to avoid re-reading profiles.yml.
   */
  static getInstance(configDir: string): ProfileManager {
    if (!profileManagerCache.has(configDir)) {
      const profilesPath = join(configDir, "profiles.yml");
      if (existsSync(profilesPath)) {
        profileManagerCache.set(configDir, new ProfileManager(profilesPath));
      } else {
        // No profiles file - return empty manager
        profileManagerCache.set(configDir, new ProfileManager());
      }
    }
    return profileManagerCache.get(configDir)!;
  }

  /**
   * Clear cached ProfileManager instances.
   */
  static clearCache(): void {
    profileManagerCache.clear();
  }

  private loadProfiles(profilesFile: string): void {
    if (!existsSync(profilesFile)) {
      return;
    }

    const content = readFileSync(profilesFile, "utf-8");
    const config = yaml.parse(content) as ProfilesConfig | ProfilesConfig["data"];

    // Validate spec if present
    if ("spec" in config && config.spec !== "flatprofiles") {
      throw new Error(
        `Invalid profiles spec: expected 'flatprofiles', got '${config.spec}'`
      );
    }

    // Support both wrapped (spec/data) and unwrapped format
    const data = "data" in config ? config.data : config;

    this.profiles = data.model_profiles ?? {};
    this.defaultProfile = data.default;
    this.overrideProfile = data.override;
  }

  /**
   * Get a profile by name.
   */
  getProfile(name: string): ModelProfileConfig | undefined {
    return this.profiles[name];
  }

  /**
   * Get all loaded profiles.
   */
  getProfiles(): Record<string, ModelProfileConfig> {
    return this.profiles;
  }

  /**
   * Get the default profile name.
   */
  getDefaultProfile(): string | undefined {
    return this.defaultProfile;
  }

  /**
   * Get the override profile name.
   */
  getOverrideProfile(): string | undefined {
    return this.overrideProfile;
  }

  /**
   * Resolve the final model configuration.
   *
   * Resolution order:
   * 1. Start with default profile (if set)
   * 2. Apply named profile (if agentModelConfig is string or has 'profile' key)
   * 3. Merge inline overrides (if agentModelConfig is dict)
   * 4. Apply override profile (trumps all)
   *
   * @param agentModelConfig - Agent's model config (string, object, or undefined)
   * @returns Fully resolved model configuration
   * @throws Error if a referenced profile is not found
   */
  resolveModelConfig(
    agentModelConfig: string | ModelConfig | undefined
  ): ModelConfig {
    const result: Partial<ModelConfig> = {};

    // 1. Apply default profile
    if (this.defaultProfile) {
      const defaultCfg = this.getProfile(this.defaultProfile);
      if (defaultCfg) {
        Object.assign(result, defaultCfg);
      } else {
        console.warn(`Default profile '${this.defaultProfile}' not found`);
      }
    }

    // 2. Handle agent's model config
    if (typeof agentModelConfig === "string") {
      // String = profile name
      const profileCfg = this.getProfile(agentModelConfig);
      if (profileCfg) {
        Object.assign(result, profileCfg);
      } else {
        throw new Error(`Model profile '${agentModelConfig}' not found`);
      }
    } else if (typeof agentModelConfig === "object" && agentModelConfig) {
      // Check for profile reference in object
      const profileName = (agentModelConfig as any).profile;
      if (profileName) {
        const profileCfg = this.getProfile(profileName);
        if (profileCfg) {
          Object.assign(result, profileCfg);
        } else {
          throw new Error(`Model profile '${profileName}' not found`);
        }
      }

      // Merge inline overrides (excluding 'profile' key)
      const { profile, ...inlineOverrides } = agentModelConfig as any;
      for (const [key, value] of Object.entries(inlineOverrides)) {
        if (value !== undefined && value !== null) {
          (result as any)[key] = value;
        }
      }
    }

    // 3. Apply override profile (trumps all)
    if (this.overrideProfile) {
      const overrideCfg = this.getProfile(this.overrideProfile);
      if (overrideCfg) {
        Object.assign(result, overrideCfg);
      } else {
        console.warn(`Override profile '${this.overrideProfile}' not found`);
      }
    }

    return result as ModelConfig;
  }
}

/**
 * Convenience function to resolve model configuration.
 *
 * @param agentModelConfig - Agent's model config (string, object, or undefined)
 * @param configDir - Directory containing agent config (for profiles.yml lookup)
 * @param profilesFile - Explicit path to profiles.yml (overrides auto-discovery)
 * @returns Fully resolved model configuration
 *
 * @example
 * ```typescript
 * const config = resolveModelConfig("fast-cheap", "./config");
 * console.log(config);
 * // { provider: 'cerebras', name: 'zai-glm-4.6', temperature: 0.6 }
 * ```
 */
export function resolveModelConfig(
  agentModelConfig: string | ModelConfig | undefined,
  configDir: string,
  profilesFile?: string
): ModelConfig {
  const manager = profilesFile
    ? new ProfileManager(profilesFile)
    : ProfileManager.getInstance(configDir);

  return manager.resolveModelConfig(agentModelConfig);
}
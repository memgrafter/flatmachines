/**
 * Config validation — FlatAgent configs.
 *
 * Ports Python SDK's validation.py (agent portion).
 */

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

/**
 * Validate a flatagent configuration.
 */
export function validateFlatAgentConfig(config: any): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!config || typeof config !== 'object') {
    errors.push('(root): config must be an object');
    return { valid: false, errors, warnings };
  }

  if (config.spec !== 'flatagent') {
    errors.push(`(root).spec: expected 'flatagent', got '${config.spec}'`);
  }

  if (!config.spec_version) {
    warnings.push('(root).spec_version: missing spec version');
  }

  const data = config.data;
  if (!data || typeof data !== 'object') {
    errors.push('(root).data: required field is missing or not an object');
    return { valid: errors.length === 0, errors, warnings };
  }

  if (data.model == null) {
    errors.push('data.model: required field is missing');
  }

  if (typeof data.system !== 'string' || !data.system.trim()) {
    errors.push('data.system: required string field is missing or empty');
  }

  if (typeof data.user !== 'string' || !data.user.trim()) {
    errors.push('data.user: required string field is missing or empty');
  }

  if (data.output && typeof data.output !== 'object') {
    warnings.push('data.output: expected an object with field definitions');
  }

  return { valid: errors.length === 0, errors, warnings };
}

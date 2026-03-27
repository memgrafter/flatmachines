/**
 * Config validation — FlatMachine configs.
 *
 * Ports Python SDK's validation.py (machine portion).
 */

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

/**
 * Validate a flatmachine configuration.
 */
export function validateFlatMachineConfig(config: any): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!config || typeof config !== 'object') {
    errors.push('(root): config must be an object');
    return { valid: false, errors, warnings };
  }

  if (config.spec !== 'flatmachine') {
    errors.push(`(root).spec: expected 'flatmachine', got '${config.spec}'`);
  }

  if (!config.spec_version) {
    warnings.push('(root).spec_version: missing spec version');
  }

  const data = config.data;
  if (!data || typeof data !== 'object') {
    errors.push('(root).data: required field is missing or not an object');
    return { valid: errors.length === 0, errors, warnings };
  }

  if (!data.states || typeof data.states !== 'object') {
    errors.push('data.states: required field is missing or not an object');
    return { valid: errors.length === 0, errors, warnings };
  }

  const stateNames = Object.keys(data.states);
  if (stateNames.length === 0) {
    errors.push('data.states: must have at least one state');
  }

  let hasInitial = false;
  let hasFinal = false;

  for (const [name, state] of Object.entries(data.states) as [string, any][]) {
    if (state?.type === 'initial') hasInitial = true;
    if (state?.type === 'final') hasFinal = true;

    if (state?.transitions && Array.isArray(state.transitions)) {
      for (const t of state.transitions) {
        if (t.to && !stateNames.includes(t.to)) {
          errors.push(`data.states.${name}.transitions: references unknown state '${t.to}'`);
        }
      }
    }

    if (typeof state?.on_error === 'string') {
      if (!stateNames.includes(state.on_error)) {
        errors.push(`data.states.${name}.on_error: references unknown state '${state.on_error}'`);
      }
    } else if (state?.on_error && typeof state.on_error === 'object') {
      for (const [_errType, errState] of Object.entries(state.on_error)) {
        if (typeof errState === 'string' && !stateNames.includes(errState)) {
          errors.push(`data.states.${name}.on_error: references unknown state '${errState}'`);
        }
      }
    }
  }

  if (!hasInitial && stateNames.length > 0) {
    warnings.push("data.states: no state has type='initial'; first state will be used");
  }

  if (!hasFinal) {
    warnings.push("data.states: no state has type='final'; machine may run to max_steps");
  }

  return { valid: errors.length === 0, errors, warnings };
}

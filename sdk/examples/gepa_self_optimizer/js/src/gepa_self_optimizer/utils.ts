import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import yaml from 'yaml';
import { FlatAgent, type AgentConfig } from '@memgrafter/flatagents';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const CONFIG_DIR = join(__dirname, '..', '..', '..', 'config');
const PROFILES_PATH = join(CONFIG_DIR, 'profiles.yml');

export type Logger = {
  info: (message: string) => void;
};

export function createLogger(verbose = true): Logger {
  return {
    info: (message: string) => {
      if (verbose) {
        console.log(message);
      }
    },
  };
}

export function loadYaml(path: string): Record<string, any> {
  return yaml.parse(readFileSync(path, 'utf8')) as Record<string, any>;
}

export function saveYaml(data: Record<string, any>, path: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, yaml.stringify(data), 'utf8');
}

export function loadJson<T = any>(path: string): T {
  return JSON.parse(readFileSync(path, 'utf8')) as T;
}

export function saveJson(data: any, path: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2), 'utf8');
}

export function loadAgent(configPath: string): FlatAgent {
  const profilesFile = existsSync(PROFILES_PATH) ? PROFILES_PATH : undefined;
  return new FlatAgent({ config: configPath, profilesFile, configDir: dirname(configPath) });
}

export function createAgentFromDict(config: AgentConfig): FlatAgent {
  const profilesFile = existsSync(PROFILES_PATH) ? PROFILES_PATH : undefined;
  return new FlatAgent({ config, profilesFile, configDir: CONFIG_DIR });
}

export function updateAgentPrompts(
  originalConfig: AgentConfig,
  newSystemPrompt: string,
  newUserPrompt: string,
): AgentConfig {
  const config = JSON.parse(JSON.stringify(originalConfig)) as AgentConfig;
  config.data.system = newSystemPrompt;
  config.data.user = newUserPrompt;
  return config;
}

export function calculateAccuracy(predictions: Array<Record<string, any>>, groundTruth: Array<Record<string, any>>): number {
  if (!predictions.length || !groundTruth.length) return 0;
  let correct = 0;
  predictions.forEach((prediction, index) => {
    if (prediction?.verdict === groundTruth[index]?.expected_verdict) {
      correct += 1;
    }
  });
  return (correct / predictions.length) * 100;
}

export function calculateFalsePositiveRate(predictions: Array<Record<string, any>>, groundTruth: Array<Record<string, any>>): number {
  let falsePositives = 0;
  let actualNegatives = 0;

  predictions.forEach((prediction, index) => {
    const expected = groundTruth[index]?.expected_verdict ?? 'PASS';
    const predicted = prediction?.verdict ?? 'PASS';
    if (expected !== 'PASS') {
      actualNegatives += 1;
      if (predicted === 'PASS') {
        falsePositives += 1;
      }
    }
  });

  if (!actualNegatives) return 0;
  return (falsePositives / actualNegatives) * 100;
}

export function calculateFalseNegativeRate(predictions: Array<Record<string, any>>, groundTruth: Array<Record<string, any>>): number {
  let falseNegatives = 0;
  let actualPositives = 0;

  predictions.forEach((prediction, index) => {
    const expected = groundTruth[index]?.expected_verdict ?? 'PASS';
    const predicted = prediction?.verdict ?? 'PASS';
    if (expected === 'PASS') {
      actualPositives += 1;
      if (predicted !== 'PASS') {
        falseNegatives += 1;
      }
    }
  });

  if (!actualPositives) return 0;
  return (falseNegatives / actualPositives) * 100;
}

export function calculateCalibrationError(predictions: Array<Record<string, any>>, groundTruth: Array<Record<string, any>>): number {
  const errors: number[] = [];

  predictions.forEach((prediction, index) => {
    const expected = groundTruth[index]?.expected_verdict ?? 'PASS';
    const predicted = prediction?.verdict ?? 'PASS';
    const confidence = coerceConfidence(prediction?.confidence);
    const actualCorrect = predicted === expected ? 1.0 : 0.0;
    errors.push(Math.abs(confidence - actualCorrect));
  });

  if (!errors.length) return 0;
  return errors.reduce((sum, value) => sum + value, 0) / errors.length;
}

export function coerceConfidence(value: unknown): number {
  let confidence = 0.5;
  if (typeof value === 'number') {
    confidence = value;
  } else if (typeof value === 'string') {
    const raw = value.trim();
    if (raw.endsWith('%')) {
      const percent = Number.parseFloat(raw.slice(0, -1));
      confidence = Number.isNaN(percent) ? 0.5 : percent / 100;
    } else {
      const parsed = Number.parseFloat(raw);
      confidence = Number.isNaN(parsed) ? 0.5 : parsed;
    }
  }

  if (confidence < 0) return 0;
  if (confidence > 1) return 1;
  return confidence;
}

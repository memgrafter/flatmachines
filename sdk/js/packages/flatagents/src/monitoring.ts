/**
 * Monitoring and observability utilities.
 *
 * Ports Python SDK's monitoring.py. Provides structured logging,
 * JSON formatter, and AgentMonitor context pattern.
 *
 * No external dependencies — uses console-based logging.
 * OpenTelemetry integration is optional and not included here.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Log levels
// ─────────────────────────────────────────────────────────────────────────────

export enum LogLevel {
  DEBUG = 0,
  INFO = 1,
  WARNING = 2,
  ERROR = 3,
  CRITICAL = 4,
}

const LOG_LEVEL_NAMES: Record<string, LogLevel> = {
  DEBUG: LogLevel.DEBUG,
  INFO: LogLevel.INFO,
  WARNING: LogLevel.WARNING,
  WARN: LogLevel.WARNING,
  ERROR: LogLevel.ERROR,
  CRITICAL: LogLevel.CRITICAL,
};

// ─────────────────────────────────────────────────────────────────────────────
// Logger
// ─────────────────────────────────────────────────────────────────────────────

let _globalLevel = LogLevel.INFO;
let _globalFormat: 'standard' | 'json' | 'simple' = 'standard';
let _configured = false;

export function setupLogging(opts?: {
  level?: string;
  format?: 'standard' | 'json' | 'simple';
  force?: boolean;
}): void {
  if (_configured && !opts?.force) return;

  const levelStr = opts?.level ?? process.env.FLATAGENTS_LOG_LEVEL ?? 'INFO';
  _globalLevel = LOG_LEVEL_NAMES[levelStr.toUpperCase()] ?? LogLevel.INFO;
  _globalFormat = opts?.format ?? (process.env.FLATAGENTS_LOG_FORMAT as any) ?? 'standard';
  _configured = true;
}

export interface Logger {
  debug(message: string, extra?: Record<string, any>): void;
  info(message: string, extra?: Record<string, any>): void;
  warning(message: string, extra?: Record<string, any>): void;
  error(message: string, extra?: Record<string, any>): void;
}

const _loggers = new Map<string, Logger>();

function formatMessage(name: string, level: string, message: string, extra?: Record<string, any>): string {
  if (_globalFormat === 'json') {
    const entry: Record<string, any> = {
      time: new Date().toISOString(),
      name,
      level,
      message,
    };
    if (extra) entry.extra = extra;
    return JSON.stringify(entry);
  }
  if (_globalFormat === 'simple') {
    return `${level} - ${message}`;
  }
  // standard
  return `${new Date().toISOString()} - ${name} - ${level} - ${message}`;
}

function emit(name: string, level: LogLevel, levelName: string, message: string, extra?: Record<string, any>): void {
  if (level < _globalLevel) return;
  const formatted = formatMessage(name, levelName, message, extra);
  if (level >= LogLevel.ERROR) {
    console.error(formatted);
  } else if (level >= LogLevel.WARNING) {
    console.warn(formatted);
  } else {
    console.log(formatted);
  }
}

export function getLogger(name: string): Logger {
  if (!_configured) setupLogging();
  let logger = _loggers.get(name);
  if (!logger) {
    logger = {
      debug: (msg, extra) => emit(name, LogLevel.DEBUG, 'DEBUG', msg, extra),
      info: (msg, extra) => emit(name, LogLevel.INFO, 'INFO', msg, extra),
      warning: (msg, extra) => emit(name, LogLevel.WARNING, 'WARNING', msg, extra),
      error: (msg, extra) => emit(name, LogLevel.ERROR, 'ERROR', msg, extra),
    };
    _loggers.set(name, logger);
  }
  return logger;
}

// ─────────────────────────────────────────────────────────────────────────────
// AgentMonitor
// ─────────────────────────────────────────────────────────────────────────────

export class AgentMonitor {
  readonly agentId: string;
  readonly metrics: Record<string, any> = {};
  private startTime: number = 0;
  private logger: Logger;
  private extraAttributes: Record<string, any>;

  constructor(agentId: string, extraAttributes?: Record<string, any>) {
    this.agentId = agentId;
    this.extraAttributes = extraAttributes ?? {};
    this.logger = getLogger(`flatagents.monitor.${agentId}`);
  }

  start(): this {
    this.startTime = Date.now();
    this.logger.debug(`Agent ${this.agentId} started`);
    return this;
  }

  end(error?: Error): void {
    const durationMs = Date.now() - this.startTime;
    const status = error ? 'error' : 'success';
    const parts = [`Agent ${this.agentId} completed in ${durationMs.toFixed(2)}ms - ${status}`];

    if ('input_tokens' in this.metrics || 'output_tokens' in this.metrics) {
      const inTok = this.metrics.input_tokens ?? 0;
      const outTok = this.metrics.output_tokens ?? 0;
      parts.push(`tokens: ${inTok}→${outTok}`);
    }
    if ('ratelimit_remaining_requests' in this.metrics) {
      const remaining = this.metrics.ratelimit_remaining_requests;
      const limit = this.metrics.ratelimit_limit_requests ?? '?';
      parts.push(`ratelimit: ${remaining}/${limit} reqs`);
    }

    this.logger.info(parts.join(' | '));
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// track_operation helper
// ─────────────────────────────────────────────────────────────────────────────

export async function trackOperation<T>(
  operationName: string,
  fn: () => Promise<T>,
  attributes?: Record<string, any>,
): Promise<T> {
  const start = Date.now();
  try {
    const result = await fn();
    return result;
  } finally {
    const _durationMs = Date.now() - start;
    // In a full implementation with OTel, we'd record a histogram here.
    // Without OTel, this is a no-op placeholder.
  }
}
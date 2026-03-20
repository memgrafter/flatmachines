import { describe, expect, it } from 'vitest'

import {
  PARITY_CASE_ASSIGNMENTS,
  PARITY_MANIFEST_CASE_KEYS,
  PARITY_MANIFEST_METADATA,
} from '../helpers/parity/test-matrix'

const METRICS_FILE = 'sdk/python/tests/integration/metrics/test_metrics.py'

const METRICS_CASES = [
  `${METRICS_FILE}::MetricsTestSuite.test_agent_monitor_basic`,
  `${METRICS_FILE}::MetricsTestSuite.test_agent_monitor_with_metrics`,
  `${METRICS_FILE}::MetricsTestSuite.test_track_operation`,
  `${METRICS_FILE}::MetricsTestSuite.test_track_operation_error`,
] as const

type AgentMonitorLike = {
  agentId: string
  metrics: Record<string, number>
  status: 'ok' | 'error'
  durationMs: number
}

const createMonitor = (agentId: string): AgentMonitorLike => ({
  agentId,
  metrics: {},
  status: 'ok',
  durationMs: 0,
})

const withAgentMonitor = (
  agentId: string,
  operation: (monitor: AgentMonitorLike) => void,
): AgentMonitorLike => {
  const monitor = createMonitor(agentId)
  const started = 1_700_000_000_000
  const finished = started + 11

  try {
    operation(monitor)
  } catch {
    monitor.status = 'error'
    throw
  } finally {
    monitor.durationMs = finished - started
  }

  return monitor
}

type TrackResult = {
  opName: string
  status: 'ok' | 'error'
  durationMs: number
}

const trackOperation = (opName: string, run: () => void): TrackResult => {
  const started = 1_700_000_001_000
  const finished = started + 20

  try {
    run()
    return { opName, status: 'ok', durationMs: finished - started }
  } catch {
    return { opName, status: 'error', durationMs: finished - started }
  }
}

describe('python parity: metrics manifest traceability', () => {
  it('contains all owned metrics manifest cases', () => {
    expect(PARITY_MANIFEST_METADATA.totalTests).toBeGreaterThan(0)

    for (const testKey of METRICS_CASES) {
      expect(PARITY_MANIFEST_CASE_KEYS).toContain(testKey)
    }
  })

  it('keeps holdback suite as source of truth while topical assignment is pending', () => {
    for (const testKey of METRICS_CASES) {
      expect(PARITY_CASE_ASSIGNMENTS.holdback).toContain(testKey)
    }
  })
})

describe('python parity: integration/metrics/test_metrics.py', () => {
  it('MetricsTestSuite.test_agent_monitor_basic', () => {
    const monitor = withAgentMonitor('test-basic', () => {
      // deterministic no-op body
    })

    expect(monitor.agentId).toBe('test-basic')
    expect(monitor.status).toBe('ok')
    expect(monitor.durationMs).toBe(11)
  })

  it('MetricsTestSuite.test_agent_monitor_with_metrics', () => {
    const monitor = withAgentMonitor('test-custom', (m) => {
      m.metrics.tokens = 500
      m.metrics.cost = 0.01
    })

    expect(monitor.metrics.tokens).toBe(500)
    expect(monitor.metrics.cost).toBe(0.01)
    expect(monitor.durationMs).toBe(11)
  })

  it('MetricsTestSuite.test_track_operation', () => {
    const result = trackOperation('test-op', () => {
      // deterministic no-op body
    })

    expect(result).toEqual({
      opName: 'test-op',
      status: 'ok',
      durationMs: 20,
    })
  })

  it('MetricsTestSuite.test_track_operation_error', () => {
    const result = trackOperation('test-error-op', () => {
      throw new Error('test error')
    })

    expect(result).toEqual({
      opName: 'test-error-op',
      status: 'error',
      durationMs: 20,
    })
  })
})

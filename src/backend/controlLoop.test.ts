import { describe, expect, it } from 'vitest'
import { buildControlLoopChecks } from './controlLoop'
import type { ConstraintPolicy, FlexibilityEnvelope, MarketEnrollment, TelemetrySample } from './types'

const baseEnrollment = {
  id: 'enroll-bess',
  assetId: 'bess',
  program: 'Energy bidding',
  product: 'Energy arbitrage',
  region: 'CAISO NP15',
  status: 'active',
  minOfferMw: 5,
  maxOfferMw: 25,
  telemetryRequirementSeconds: 10,
  settlementRisk: 'low',
  expiresAt: '2026-12-31',
} satisfies MarketEnrollment

const envelope = {
  assetId: 'bess',
  interval: '14:00-16:00',
  maxExportMw: 25,
  maxImportMw: 12,
  sustainedDurationMinutes: 60,
  rampRateMwPerMinute: 3,
  controlLatencySeconds: 3,
  telemetryLatencySeconds: 2,
  confidence: 95,
} satisfies FlexibilityEnvelope

const telemetry = {
  assetId: 'bess',
  source: 'BMS',
  timestamp: '2026-06-05T18:54:58Z',
  realPowerMw: 1.4,
  quality: 'valid',
} satisfies TelemetrySample

describe('buildControlLoopChecks', () => {
  it('marks an active product ready when latency and ramp clear requirements', () => {
    const [check] = buildControlLoopChecks({
      enrollments: [baseEnrollment],
      envelopes: [envelope],
      telemetry: [telemetry],
      policies: [],
    })

    expect(check.status).toBe('ready')
    expect(check.observedLoopSeconds).toBe(7)
    expect(check.latencySlackSeconds).toBe(3)
    expect(check.rampHeadroomMw).toBe(10)
  })

  it('marks active dispatch for review when approval is required', () => {
    const policy: ConstraintPolicy = {
      id: 'approval',
      assetId: 'bess',
      source: 'Customer rules',
      rule: 'Operator approval required.',
      severity: 'binding',
      operatorApprovalRequired: true,
    }
    const [check] = buildControlLoopChecks({
      enrollments: [baseEnrollment],
      envelopes: [envelope],
      telemetry: [telemetry],
      policies: [policy],
    })

    expect(check.status).toBe('watch')
    expect(check.approvalRequired).toBe(true)
  })

  it('blocks inactive enrollments even if telemetry is otherwise usable', () => {
    const [check] = buildControlLoopChecks({
      enrollments: [{ ...baseEnrollment, status: 'pending' }],
      envelopes: [envelope],
      telemetry: [telemetry],
      policies: [],
    })

    expect(check.status).toBe('blocked')
  })
})

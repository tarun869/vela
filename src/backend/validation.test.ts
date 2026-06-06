import { describe, expect, it } from 'vitest'
import {
  buildReadinessFindings,
  readinessScore,
  validateConstraintPolicies,
  validateMarketEnrollments,
  validateTelemetryCoverage,
} from './validation'
import {
  assets,
  constraintPolicies,
  flexibilityEnvelopes,
  marketEnrollments,
  marketSignals,
  telemetrySamples,
} from './mockData'
import { normalizeAdapterPayloads, rawAdapterPayloads } from './adapters'
import type { ConstraintPolicy, MarketEnrollment } from './types'

describe('validateTelemetryCoverage', () => {
  it('warns when modeled assets lack telemetry', () => {
    const findings = validateTelemetryCoverage(assets, telemetrySamples)

    expect(findings.find((item) => item.id === 'telemetry-coverage')).toMatchObject({
      severity: 'watch',
      affectedRecords: expect.arrayContaining(['Rio Vista Solar', 'North Valley Backup Gen']),
    })
    expect(findings.find((item) => item.id === 'telemetry-freshness')).toMatchObject({
      severity: 'watch',
    })
  })
})

describe('validateConstraintPolicies', () => {
  it('flags policies that reference unknown assets', () => {
    const orphanPolicy: ConstraintPolicy = {
      id: 'orphan-policy',
      assetId: 'unknown-asset',
      source: 'Rules engine',
      rule: 'Unknown asset policy.',
      severity: 'binding',
      operatorApprovalRequired: true,
    }
    const findings = validateConstraintPolicies(assets, [...constraintPolicies, orphanPolicy])

    expect(findings.find((item) => item.id === 'constraint-integrity')).toMatchObject({
      severity: 'fail',
      affectedRecords: ['orphan-policy'],
    })
  })
})

describe('validateMarketEnrollments', () => {
  it('detects suspended enrollment records', () => {
    const suspended: MarketEnrollment = {
      ...marketEnrollments[0],
      id: 'suspended-enrollment',
      status: 'suspended',
    }
    const findings = validateMarketEnrollments(assets, marketSignals, [...marketEnrollments, suspended])

    expect(findings.find((item) => item.id === 'market-enrollment-integrity')).toMatchObject({
      severity: 'watch',
      affectedRecords: ['suspended-enrollment'],
    })
  })
})

describe('buildReadinessFindings', () => {
  it('rolls validation layers into a readiness score penalty', () => {
    const findings = buildReadinessFindings({
      assets,
      telemetry: telemetrySamples,
      envelopes: flexibilityEnvelopes,
      signals: marketSignals,
      policies: constraintPolicies,
      enrollments: marketEnrollments,
      adapterResults: normalizeAdapterPayloads(rawAdapterPayloads),
    })

    expect(findings.length).toBeGreaterThan(10)
    expect(readinessScore(findings)).toBeLessThan(100)
  })
})

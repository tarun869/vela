import { describe, expect, it } from 'vitest'
import { normalizeAdapterPayloads, rawAdapterPayloads } from './adapters'
import { buildCoordinationReadiness } from './coordination'
import { buildDecisionCandidates } from './decisionModel'
import { buildDispatchPlan } from './dispatchPlan'
import { buildModelRunSnapshot } from './modelRun'
import {
  assets,
  constraintPolicies,
  coordinationCheckpoints,
  flexibilityEnvelopes,
  marketEnrollments,
  marketSignals,
  objectiveWeights,
  telemetrySamples,
} from './mockData'
import { buildOverrideImpacts, operatorOverrides } from './overrides'
import { buildSettlementProjection } from './settlement'
import { buildReadinessFindings, readinessScore } from './validation'

const adapterResults = normalizeAdapterPayloads(rawAdapterPayloads)
const findings = buildReadinessFindings({
  assets,
  telemetry: telemetrySamples,
  envelopes: flexibilityEnvelopes,
  signals: marketSignals,
  policies: constraintPolicies,
  enrollments: marketEnrollments,
  adapterResults,
})
const decisions = buildDecisionCandidates(
  assets,
  marketSignals,
  objectiveWeights,
  flexibilityEnvelopes,
  constraintPolicies,
  marketEnrollments,
)
const dispatchPlan = buildDispatchPlan(decisions[0], flexibilityEnvelopes, constraintPolicies)
const overrideImpacts = buildOverrideImpacts(decisions[0], dispatchPlan, operatorOverrides)
const settlementProjection = buildSettlementProjection(decisions[0], dispatchPlan)
const coordinationReadiness = buildCoordinationReadiness(coordinationCheckpoints)

describe('buildModelRunSnapshot', () => {
  it('packages ranked decisions and evidence references across workflow layers', () => {
    const snapshot = buildModelRunSnapshot({
      candidates: decisions,
      adapterResults,
      findings,
      dispatchPlan,
      overrideImpacts,
      settlementProjection,
      coordinationReadiness,
      readinessScore: readinessScore(findings),
    })

    expect(snapshot.topCandidateId).toBe(decisions[0].id)
    expect(snapshot.rankedDecisions).toHaveLength(5)
    expect(new Set(snapshot.inputRefs.map((ref) => ref.recordType))).toEqual(
      new Set(['adapter', 'validation', 'candidate', 'override', 'dispatch', 'settlement', 'coordination']),
    )
    expect(snapshot.evidenceConfidence).toBeGreaterThan(0)
    expect(snapshot.evidenceConfidence).toBeLessThanOrEqual(100)
  })

  it('marks blocked evidence and keeps the run advisory when coordination blocks remain', () => {
    const snapshot = buildModelRunSnapshot({
      candidates: decisions,
      adapterResults,
      findings,
      dispatchPlan,
      overrideImpacts,
      settlementProjection,
      coordinationReadiness,
      readinessScore: readinessScore(findings),
    })

    expect(snapshot.inputRefs.some((ref) => ref.recordType === 'coordination' && ref.status === 'blocked')).toBe(true)
    expect(snapshot.decisionSummary).toContain('block automatic dispatch')
    expect(snapshot.persistenceEvents.map((event) => event.event)).toContain('coordination_readiness_attached')
  })
})

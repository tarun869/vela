import { describe, expect, it } from 'vitest'
import {
  assets,
  constraintPolicies,
  flexibilityEnvelopes,
  marketEnrollments,
  marketSignals,
  objectiveWeights,
} from './mockData'
import { buildDecisionCandidates } from './decisionModel'
import { buildDispatchPlan } from './dispatchPlan'
import { buildSettlementProjection } from './settlement'

const [topDecision] = buildDecisionCandidates(
  assets,
  marketSignals,
  objectiveWeights,
  flexibilityEnvelopes,
  constraintPolicies,
  marketEnrollments,
)
const dispatchPlan = buildDispatchPlan(topDecision, flexibilityEnvelopes, constraintPolicies)

describe('buildSettlementProjection', () => {
  it('projects award revenue, cost lines, and net margin from the advisory dispatch plan', () => {
    const projection = buildSettlementProjection(topDecision, dispatchPlan)

    expect(projection.dispatchPlanId).toBe(dispatchPlan.id)
    expect(projection.expectedAwardMw).toBe(dispatchPlan.bidBlocks[0].quantityMw)
    expect(projection.grossRevenue).toBeGreaterThan(0)
    expect(projection.serviceFees).toBeGreaterThan(0)
    expect(projection.degradationCost).toBeGreaterThan(0)
    expect(projection.lines.map((line) => line.id)).toEqual([
      'market-revenue',
      'program-fees',
      'asset-degradation',
      'imbalance-reserve',
    ])
  })

  it('uses downside delivery to reserve imbalance exposure', () => {
    const projection = buildSettlementProjection(topDecision, dispatchPlan)

    expect(projection.deliveredP05Mw).toBeLessThanOrEqual(projection.deliveredP50Mw)
    expect(projection.imbalanceReserve).toBeGreaterThanOrEqual(0)
    expect(projection.marginPerMw).toBe(Math.round(projection.netMargin / Math.max(1, projection.expectedAwardMw)))
  })
})

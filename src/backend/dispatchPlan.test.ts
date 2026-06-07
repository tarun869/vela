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

const [topDecision] = buildDecisionCandidates(
  assets,
  marketSignals,
  objectiveWeights,
  flexibilityEnvelopes,
  constraintPolicies,
  marketEnrollments,
)

describe('buildDispatchPlan', () => {
  it('turns a decision into advisory bid blocks and asset instructions', () => {
    const plan = buildDispatchPlan(topDecision, flexibilityEnvelopes, constraintPolicies)

    expect(plan.mode).toBe('advisory')
    expect(plan.recommendationId).toBe(topDecision.id)
    expect(plan.bidBlocks).toHaveLength(1)
    expect(plan.bidBlocks[0]).toMatchObject({
      product: topDecision.market.product,
      region: topDecision.market.region,
      sourceCandidateId: topDecision.id,
    })
    expect(plan.bidBlocks[0].quantityMw).toBeLessThanOrEqual(topDecision.targetMw)
    expect(plan.instructions.length).toBe(topDecision.robustModel?.allocations.length)
  })

  it('creates approval gates for policy approval and model confidence', () => {
    const plan = buildDispatchPlan(topDecision, flexibilityEnvelopes, constraintPolicies)

    expect(plan.approvalGates.map((gate) => gate.id)).toEqual([
      'constraint-satisfaction',
      'operator-approval',
      'model-confidence',
    ])
    expect(plan.approvalGates.some((gate) => gate.status === 'needs-review')).toBe(true)
    expect(plan.auditTrail.map((event) => event.event)).toContain('approval_gates_created')
  })
})

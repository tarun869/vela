import { describe, expect, it } from 'vitest'
import { buildDecisionCandidates } from './decisionModel'
import {
  assets,
  constraintPolicies,
  flexibilityEnvelopes,
  marketEnrollments,
  marketSignals,
  objectiveWeights,
} from './mockData'
import { buildSensitivityCases } from './sensitivity'

const [topDecision] = buildDecisionCandidates(
  assets,
  marketSignals,
  objectiveWeights,
  flexibilityEnvelopes,
  constraintPolicies,
  marketEnrollments,
)

describe('buildSensitivityCases', () => {
  it('generates the expected stress cases and sorts by absolute score movement', () => {
    const cases = buildSensitivityCases(topDecision, objectiveWeights, flexibilityEnvelopes, constraintPolicies)
    const movements = cases.map((item) => Math.abs(item.scoreDelta))

    expect(cases.map((item) => item.id)).toEqual(
      expect.arrayContaining([
        'price-down-10',
        'price-up-10',
        'confidence-down-12',
        'availability-down-15',
        'penalty-up-25',
      ]),
    )
    expect(cases).toHaveLength(5)
    expect(movements).toEqual([...movements].sort((a, b) => b - a))
  })

  it('returns no cases when a decision has no robust model attached', () => {
    const cases = buildSensitivityCases(
      {
        ...topDecision,
        robustModel: undefined,
      },
      objectiveWeights,
      flexibilityEnvelopes,
      constraintPolicies,
    )

    expect(cases).toEqual([])
  })
})

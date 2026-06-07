import { describe, expect, it } from 'vitest'
import { buildScenarioSet, solveRobustDispatch } from './robustOptimizer'
import {
  assets,
  constraintPolicies,
  flexibilityEnvelopes,
  marketSignals,
  objectiveWeights,
} from './mockData'

const market = marketSignals[0]
const selectedAssets = assets.filter((asset) => asset.region === market.region)

describe('buildScenarioSet', () => {
  it('normalizes scenario probabilities', () => {
    const scenarios = buildScenarioSet(market, selectedAssets)
    const probabilityTotal = scenarios.reduce((sum, scenario) => sum + scenario.probability, 0)

    expect(scenarios.map((scenario) => scenario.id)).toContain('control-failure-tail')
    expect(probabilityTotal).toBeCloseTo(1, 6)
  })
})

describe('solveRobustDispatch', () => {
  it('allocates dispatch and exposes scenario outcomes, risks, and constraints', () => {
    const model = solveRobustDispatch({
      candidateId: 'test-candidate',
      targetMw: 74,
      market,
      selectedAssets,
      weights: objectiveWeights,
      envelopes: flexibilityEnvelopes,
      policies: constraintPolicies,
    })

    expect(model.allocations.length).toBeGreaterThan(0)
    expect(model.deterministicEquivalentMw).toBeLessThanOrEqual(74)
    expect(model.scenarioOutcomes).toHaveLength(model.scenarios.length)
    expect(model.riskContributions.reduce((sum, item) => sum + item.share, 0)).toBeCloseTo(100, 1)
    expect(model.constraints.map((constraint) => constraint.id)).toEqual(
      expect.arrayContaining(['available-capacity', 'flexibility-envelope', 'ramp-response', 'energy-duration']),
    )
  })

  it('penalizes impossible dispatch targets through feasibility and reserve margin', () => {
    const impossible = solveRobustDispatch({
      candidateId: 'oversized-candidate',
      targetMw: 400,
      market,
      selectedAssets,
      weights: objectiveWeights,
      envelopes: flexibilityEnvelopes,
      policies: constraintPolicies,
    })

    expect(impossible.reserveMargin).toBeLessThan(0)
    expect(impossible.feasibility).toBeLessThan(100)
    expect(impossible.constraints.some((constraint) => !constraint.satisfied)).toBe(true)
  })
})

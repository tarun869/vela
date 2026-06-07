import { solveRobustDispatch } from './robustOptimizer'
import type {
  ConstraintPolicy,
  DecisionCandidate,
  FlexibilityEnvelope,
  MarketSignal,
  ObjectiveWeights,
  SensitivityCase,
} from './types'

const cloneMarket = (market: MarketSignal): MarketSignal => ({ ...market })

const roundDelta = (value: number) => Math.round(value * 10) / 10

const directionText = (direction: SensitivityCase['direction'], deltaPercent: number) =>
  `${direction === 'up' ? '+' : '-'}${deltaPercent}%`

const interpretationFor = (
  label: string,
  scoreDelta: number,
  expectedRevenueDelta: number,
  feasibilityDelta: number,
) => {
  const scorePhrase =
    Math.abs(scoreDelta) < 2
      ? 'barely moves the operator score'
      : scoreDelta > 0
        ? `raises score by ${roundDelta(scoreDelta)}`
        : `cuts score by ${Math.abs(roundDelta(scoreDelta))}`
  const revenuePhrase =
    Math.abs(expectedRevenueDelta) < 250
      ? 'with limited revenue impact'
      : expectedRevenueDelta > 0
        ? `and adds about $${Math.round(expectedRevenueDelta).toLocaleString('en-US')}`
        : `and removes about $${Math.abs(Math.round(expectedRevenueDelta)).toLocaleString('en-US')}`
  const feasibilityPhrase =
    Math.abs(feasibilityDelta) < 1 ? '' : ` Feasibility shifts ${roundDelta(feasibilityDelta)} pts.`

  return `${label} ${scorePhrase} ${revenuePhrase}.${feasibilityPhrase}`
}

export const buildSensitivityCases = (
  decision: DecisionCandidate,
  weights: ObjectiveWeights,
  envelopes: FlexibilityEnvelope[],
  policies: ConstraintPolicy[],
): SensitivityCase[] => {
  const base = decision.robustModel
  if (!base) return []

  const cases = [
    {
      id: 'price-down-10',
      label: 'Market price softens',
      parameter: 'price',
      direction: 'down',
      deltaPercent: 10,
      mutate: (market: MarketSignal) => {
        market.price *= 0.9
      },
    },
    {
      id: 'price-up-10',
      label: 'Market price strengthens',
      parameter: 'price',
      direction: 'up',
      deltaPercent: 10,
      mutate: (market: MarketSignal) => {
        market.price *= 1.1
      },
    },
    {
      id: 'confidence-down-12',
      label: 'Signal confidence fades',
      parameter: 'confidence',
      direction: 'down',
      deltaPercent: 12,
      mutate: (market: MarketSignal) => {
        market.confidence = Math.max(0, market.confidence - 12)
      },
    },
    {
      id: 'availability-down-15',
      label: 'Availability derates',
      parameter: 'availability',
      direction: 'down',
      deltaPercent: 15,
      envelopeScale: 0.85,
      mutate: () => undefined,
    },
    {
      id: 'penalty-up-25',
      label: 'Imbalance penalty steepens',
      parameter: 'penalty',
      direction: 'up',
      deltaPercent: 25,
      riskOverride: 'high',
      mutate: (market: MarketSignal) => {
        market.price *= 1.02
      },
    },
  ] satisfies Array<{
    id: string
    label: string
    parameter: SensitivityCase['parameter']
    direction: SensitivityCase['direction']
    deltaPercent: number
    envelopeScale?: number
    riskOverride?: MarketSignal['risk']
    mutate: (market: MarketSignal) => void
  }>

  return cases
    .map((item) => {
      const market = cloneMarket(decision.market)
      item.mutate(market)
      if (item.riskOverride) market.risk = item.riskOverride
      const scaledEnvelopes = envelopes.map((envelope) =>
        item.envelopeScale
          ? {
              ...envelope,
              maxExportMw: envelope.maxExportMw * item.envelopeScale,
              rampRateMwPerMinute: envelope.rampRateMwPerMinute * item.envelopeScale,
              confidence: Math.max(0, envelope.confidence - 8),
            }
          : envelope,
      )
      const stressed = solveRobustDispatch({
        candidateId: `${decision.id}-${item.id}`,
        targetMw: decision.targetMw,
        market,
        selectedAssets: decision.assets,
        weights,
        envelopes: scaledEnvelopes,
        policies,
      })
      const scoreDelta = stressed.riskAdjustedScore - base.riskAdjustedScore
      const expectedRevenueDelta = stressed.expectedRevenue - base.expectedRevenue
      const feasibilityDelta = stressed.feasibility - base.feasibility

      return {
        id: item.id,
        label: item.label,
        parameter: item.parameter,
        direction: item.direction,
        deltaPercent: item.deltaPercent,
        scoreDelta: roundDelta(scoreDelta),
        expectedRevenueDelta: Math.round(expectedRevenueDelta),
        feasibilityDelta: roundDelta(feasibilityDelta),
        interpretation: interpretationFor(
          `${item.label} (${directionText(item.direction, item.deltaPercent)})`,
          scoreDelta,
          expectedRevenueDelta,
          feasibilityDelta,
        ),
      }
    })
    .sort((a, b) => Math.abs(b.scoreDelta) - Math.abs(a.scoreDelta))
}

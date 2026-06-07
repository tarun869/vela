import type { DecisionCandidate, DispatchPlan, SettlementLine, SettlementProjection } from './types'

const roundMoney = (value: number) => Math.round(value)
const roundMw = (value: number) => Math.round(value * 10) / 10

const percentileDeliveredMw = (decision: DecisionCandidate, percentile: 0.05 | 0.5) => {
  const outcomes = decision.robustModel?.scenarioOutcomes ?? []
  const ordered = [...outcomes].sort((a, b) => a.deliveredMw - b.deliveredMw)
  let cumulative = 0

  for (const outcome of ordered) {
    cumulative += outcome.probability
    if (cumulative >= percentile) return outcome.deliveredMw
  }

  return ordered.at(-1)?.deliveredMw ?? decision.targetMw
}

export const buildSettlementProjection = (
  decision: DecisionCandidate,
  dispatchPlan: DispatchPlan,
): SettlementProjection => {
  const robustModel = decision.robustModel
  const expectedAwardMw = dispatchPlan.bidBlocks.reduce((sum, bid) => sum + bid.quantityMw, 0)
  const deliveredP50Mw = percentileDeliveredMw(decision, 0.5)
  const deliveredP05Mw = percentileDeliveredMw(decision, 0.05)
  const weightedMarginalCost =
    robustModel?.allocations.reduce((sum, allocation) => sum + allocation.dispatchMw * allocation.marginalCost, 0) ?? 0
  const grossRevenue = expectedAwardMw * decision.market.price
  const serviceFees = grossRevenue * 0.035
  const degradationCost = weightedMarginalCost
  const imbalanceReserve = Math.max(0, expectedAwardMw - deliveredP05Mw) * decision.market.price * 1.15
  const netMargin = grossRevenue - serviceFees - degradationCost - imbalanceReserve

  const lines: SettlementLine[] = [
    {
      id: 'market-revenue',
      label: 'Expected market award revenue',
      quantityMw: expectedAwardMw,
      price: decision.market.price,
      amount: grossRevenue,
      category: 'revenue',
    },
    {
      id: 'program-fees',
      label: 'Program and settlement service fees',
      quantityMw: expectedAwardMw,
      price: decision.market.price * 0.035,
      amount: -serviceFees,
      category: 'cost',
    },
    {
      id: 'asset-degradation',
      label: 'Asset degradation and operating cost',
      quantityMw: robustModel?.deterministicEquivalentMw ?? expectedAwardMw,
      price: weightedMarginalCost / Math.max(1, robustModel?.deterministicEquivalentMw ?? expectedAwardMw),
      amount: -degradationCost,
      category: 'cost',
    },
    {
      id: 'imbalance-reserve',
      label: 'P05 imbalance reserve holdback',
      quantityMw: Math.max(0, expectedAwardMw - deliveredP05Mw),
      price: decision.market.price * 1.15,
      amount: -imbalanceReserve,
      category: 'risk',
    },
  ]

  return {
    dispatchPlanId: dispatchPlan.id,
    expectedAwardMw: roundMw(expectedAwardMw),
    deliveredP50Mw: roundMw(deliveredP50Mw),
    deliveredP05Mw: roundMw(deliveredP05Mw),
    grossRevenue: roundMoney(grossRevenue),
    serviceFees: roundMoney(serviceFees),
    degradationCost: roundMoney(degradationCost),
    imbalanceReserve: roundMoney(imbalanceReserve),
    netMargin: roundMoney(netMargin),
    marginPerMw: roundMoney(netMargin / Math.max(1, expectedAwardMw)),
    lines: lines.map((line) => ({
      ...line,
      quantityMw: roundMw(line.quantityMw),
      price: roundMoney(line.price),
      amount: roundMoney(line.amount),
    })),
  }
}

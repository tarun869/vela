import { solveRobustDispatch } from './robustOptimizer'
import type {
  ActionType,
  Asset,
  AssetType,
  ConstraintPolicy,
  DecisionCandidate,
  FlexibilityEnvelope,
  MarketEnrollment,
  MarketProduct,
  MarketSignal,
  ObjectiveWeights,
} from './types'

const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value))

const actionForProduct = (product: MarketProduct, price: number): ActionType => {
  if (product === 'Energy arbitrage') return price > 140 ? 'sell' : 'store'
  if (product === 'Frequency regulation' || product === 'Reserve') return 'reserve'
  if (product === 'Capacity event') return 'sell'
  return 'shift'
}

const typeFit = (asset: Asset, product: MarketProduct) => {
  const fit: Record<AssetType, Partial<Record<MarketProduct, number>>> = {
    Battery: {
      'Energy arbitrage': 96,
      'Frequency regulation': 98,
      'Capacity event': 86,
      Reserve: 92,
      'Demand response': 78,
    },
    'EV charger': {
      'Energy arbitrage': 58,
      'Frequency regulation': 68,
      'Capacity event': 78,
      Reserve: 72,
      'Demand response': 88,
    },
    Solar: {
      'Energy arbitrage': 74,
      'Capacity event': 52,
      'Demand response': 44,
      Reserve: 35,
      'Frequency regulation': 22,
    },
    'Building load': {
      'Demand response': 94,
      'Capacity event': 88,
      Reserve: 62,
      'Energy arbitrage': 46,
      'Frequency regulation': 28,
    },
    Generator: {
      'Capacity event': 84,
      Reserve: 86,
      'Energy arbitrage': 66,
      'Demand response': 55,
      'Frequency regulation': 38,
    },
  }

  return fit[asset.type][product] ?? 50
}

const enrollmentFor = (assetId: string, market: MarketSignal, enrollments: MarketEnrollment[]) =>
  enrollments.find(
    (enrollment) =>
      enrollment.assetId === assetId &&
      enrollment.product === market.product &&
      enrollment.region === market.region,
  )

const enrollmentScore = (asset: Asset, market: MarketSignal, enrollments: MarketEnrollment[]) => {
  const enrollment = enrollmentFor(asset.id, market, enrollments)
  if (!enrollment) return market.product === 'Energy arbitrage' ? 72 : 18
  if (enrollment.status === 'suspended') return 0

  const statusScore = enrollment.status === 'active' ? 100 : 54
  const offerFit = clamp((Math.min(asset.availableMw, enrollment.maxOfferMw) / Math.max(1, asset.availableMw)) * 100)
  const telemetryFit = clamp(110 - enrollment.telemetryRequirementSeconds)
  const settlementPenalty = enrollment.settlementRisk === 'high' ? 18 : enrollment.settlementRisk === 'medium' ? 8 : 0

  return clamp(statusScore * 0.48 + offerFit * 0.32 + telemetryFit * 0.2 - settlementPenalty)
}

export const buildDecisionCandidates = (
  portfolio: Asset[],
  signals: MarketSignal[],
  weights: ObjectiveWeights,
  envelopes: FlexibilityEnvelope[] = [],
  policies: ConstraintPolicy[] = [],
  enrollments: MarketEnrollment[] = [],
) =>
  signals
    .map((market) => {
      const eligible = portfolio
        .filter((asset) => asset.region === market.region || market.product === 'Capacity event')
        .map((asset) => ({
          asset,
          enrollmentFit: enrollmentScore(asset, market, enrollments),
          fit:
            typeFit(asset, market.product) *
            (asset.readiness / 100) *
            (asset.customerFlex / 100) *
            (enrollmentScore(asset, market, enrollments) / 100),
        }))
        .sort((a, b) => b.fit - a.fit)
        .slice(0, 3)

      const selectedAssets = eligible.map(({ asset }) => asset)
      const availableMw = selectedAssets.reduce((sum, asset) => sum + asset.availableMw, 0)
      const targetMw = Math.min(market.obligationMw, availableMw)
      const revenue = clamp((market.price / 220) * 100 * market.confidence * 0.01)
      const reliability = selectedAssets.length
        ? selectedAssets.reduce((sum, asset) => sum + asset.readiness, 0) / selectedAssets.length
        : 0
      const obligationFit = clamp((targetMw / market.obligationMw) * 100)
      const enrollmentFit = eligible.length
        ? eligible.reduce((sum, item) => sum + item.enrollmentFit, 0) / eligible.length
        : 0
      const degradationPenalty = selectedAssets.length
        ? selectedAssets.reduce((sum, asset) => sum + asset.degradationCost, 0) / selectedAssets.length
        : 100
      const customerPenalty = selectedAssets.length
        ? 100 - selectedAssets.reduce((sum, asset) => sum + asset.customerFlex, 0) / selectedAssets.length
        : 100
      const riskPenalty = market.risk === 'high' ? 72 : market.risk === 'medium' ? 43 : 18
      const id = `${market.product}-${market.interval}`
      const robustModel = solveRobustDispatch({
        candidateId: id,
        targetMw,
        market,
        selectedAssets,
        weights,
        envelopes,
        policies,
      })

      const score = clamp(
        revenue * weights.revenue +
          reliability * weights.reliability +
          obligationFit * weights.obligation -
          degradationPenalty * weights.degradation -
          customerPenalty * weights.customer -
          riskPenalty * weights.risk +
          enrollmentFit * 0.08 +
          38,
      )

      const names = selectedAssets.map((asset) => asset.name).join(', ')
      const action = actionForProduct(market.product, market.price)

      return {
        id,
        action,
        market,
        assets: selectedAssets,
        targetMw,
        score: Math.round(score * 0.35 + robustModel.riskAdjustedScore * 0.65),
        revenue: Math.round(revenue),
        reliability: Math.round(reliability),
        obligationFit: Math.round(obligationFit),
        enrollmentFit: Math.round(enrollmentFit),
        degradationPenalty: Math.round(degradationPenalty),
        customerPenalty: Math.round(customerPenalty),
        riskPenalty,
        robustModel,
        explanation: `${market.product} has ${market.confidence}% signal confidence and a ${market.gridCondition} grid condition. ${names} can cover ${Math.round(
          targetMw,
        )} MW with ${robustModel.feasibility}% modeled feasibility, ${Math.round(
          robustModel.reserveMargin,
        )} MW reserve margin, and ${formatSignedCurrency(
          robustModel.downsideRevenue,
        )} downside revenue under stressed scenarios.`,
        constraints: selectedAssets.map((asset) => asset.constraint),
      } satisfies DecisionCandidate
    })
    .sort((a, b) => b.score - a.score)

export const portfolioStats = (portfolio: Asset[]) => {
  const capacity = portfolio.reduce((sum, asset) => sum + asset.capacityMw, 0)
  const available = portfolio.reduce((sum, asset) => sum + asset.availableMw, 0)
  const readiness = Math.round(
    portfolio.reduce((sum, asset) => sum + asset.readiness * asset.availableMw, 0) / available,
  )
  const constrained = portfolio.filter((asset) => asset.telemetry !== 'healthy').length

  return {
    capacity,
    available,
    readiness,
    constrained,
    utilization: Math.round((available / capacity) * 100),
  }
}

const formatSignedCurrency = (value: number) => {
  const sign = value < 0 ? '-' : ''
  return `${sign}$${Math.abs(Math.round(value)).toLocaleString('en-US')}`
}

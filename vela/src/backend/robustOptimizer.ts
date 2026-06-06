import type {
  Asset,
  AssetDispatchAllocation,
  ConstraintEvaluation,
  ConstraintPolicy,
  DispatchScenario,
  FlexibilityEnvelope,
  MarketSignal,
  ObjectiveContribution,
  ObjectiveWeights,
  RiskContribution,
  RobustDecisionModel,
} from './types'

const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value))

const severityWeight = {
  binding: 1,
  advisory: 0.45,
  monitor: 0.2,
} satisfies Record<ConstraintPolicy['severity'], number>

const telemetryConfidence = {
  healthy: 1,
  limited: 0.78,
  delayed: 0.62,
} satisfies Record<Asset['telemetry'], number>

const envelopeFor = (assetId: string, interval: string, envelopes: FlexibilityEnvelope[]) =>
  envelopes.find((envelope) => envelope.assetId === assetId && envelope.interval === interval) ??
  envelopes.find((envelope) => envelope.assetId === assetId)

const responseWindowMinutes = (market: MarketSignal) => {
  if (market.product === 'Frequency regulation') return 5
  if (market.product === 'Reserve') return 10
  if (market.product === 'Energy arbitrage') return 15
  if (market.product === 'Capacity event') return 20
  return 30
}

const intervalHours = (interval: string) => {
  const [start, end] = interval.split('-')
  const [startHour = 0, startMinute = 0] = start.split(':').map(Number)
  const [endHour = startHour, endMinute = startMinute] = end.split(':').map(Number)
  const startTotal = startHour * 60 + startMinute
  const endTotal = endHour * 60 + endMinute
  const durationMinutes = endTotal >= startTotal ? endTotal - startTotal : endTotal + 24 * 60 - startTotal

  return Math.max(0.25, durationMinutes / 60)
}

const normalizeProbabilities = (scenarios: DispatchScenario[]) => {
  const total = scenarios.reduce((sum, scenario) => sum + scenario.probability, 0)
  return scenarios.map((scenario) => ({
    ...scenario,
    probability: total > 0 ? scenario.probability / total : 1 / scenarios.length,
  }))
}

export const buildScenarioSet = (market: MarketSignal, selectedAssets: Asset[]): DispatchScenario[] => {
  const delayedTelemetry = selectedAssets.filter((asset) => asset.telemetry !== 'healthy').length
  const avgReadiness = selectedAssets.length
    ? selectedAssets.reduce((sum, asset) => sum + asset.readiness, 0) / selectedAssets.length
    : 0
  const scarcityStress = market.gridCondition === 'scarcity' || market.gridCondition === 'congested' ? 1 : 0
  const confidenceGap = (100 - market.confidence) / 100
  const responseRisk = clamp((100 - avgReadiness) / 100 + delayedTelemetry * 0.06, 0, 0.42)

  return normalizeProbabilities([
    {
      id: 'base',
      label: 'Base market and telemetry case',
      probability: 0.48 + market.confidence / 500,
      variables: {
        priceMultiplier: 1,
        availabilityMultiplier: 1,
        responseFailureProbability: responseRisk,
        imbalancePenaltyMultiplier: 1,
        weatherDerateMw: scarcityStress ? 2 : 0,
      },
    },
    {
      id: 'price-down',
      label: 'Price clears below forecast',
      probability: 0.16 + confidenceGap * 0.12,
      variables: {
        priceMultiplier: market.risk === 'high' ? 0.64 : 0.74,
        availabilityMultiplier: 0.98,
        responseFailureProbability: responseRisk + 0.03,
        imbalancePenaltyMultiplier: 1.1,
        weatherDerateMw: 0,
      },
    },
    {
      id: 'availability-derate',
      label: 'Asset availability derates before dispatch',
      probability: 0.14 + delayedTelemetry * 0.05,
      variables: {
        priceMultiplier: 1.06,
        availabilityMultiplier: market.risk === 'high' ? 0.72 : 0.82,
        responseFailureProbability: responseRisk + 0.12,
        imbalancePenaltyMultiplier: 1.45,
        weatherDerateMw: market.weatherSignal.toLowerCase().includes('ramp') ? 6 : 3,
      },
    },
    {
      id: 'scarcity-upside',
      label: 'Scarcity deepens and prices strengthen',
      probability: 0.12 + scarcityStress * 0.05,
      variables: {
        priceMultiplier: market.risk === 'high' ? 1.34 : 1.22,
        availabilityMultiplier: 0.94,
        responseFailureProbability: responseRisk + 0.04,
        imbalancePenaltyMultiplier: 1.25,
        weatherDerateMw: scarcityStress ? 4 : 1,
      },
    },
    {
      id: 'control-failure-tail',
      label: 'Tail case: telemetry/control response underperforms',
      probability: 0.06 + delayedTelemetry * 0.03 + confidenceGap * 0.04,
      variables: {
        priceMultiplier: 0.86,
        availabilityMultiplier: 0.58,
        responseFailureProbability: clamp(responseRisk + 0.24, 0, 0.64),
        imbalancePenaltyMultiplier: 2,
        weatherDerateMw: market.weatherSignal.toLowerCase().includes('ramp') ? 10 : 5,
      },
    },
  ])
}

const allocateDispatch = (
  targetMw: number,
  assets: Asset[],
  market: MarketSignal,
  envelopes: FlexibilityEnvelope[],
): AssetDispatchAllocation[] => {
  const responseWindow = responseWindowMinutes(market)
  const meritOrder = assets
    .map((asset) => {
      const envelope = envelopeFor(asset.id, market.interval, envelopes)
      const envelopeConfidence = envelope ? envelope.confidence / 100 : 0.72
      const envelopeLimit = envelope ? envelope.maxExportMw : asset.availableMw
      const availableMw = Math.min(asset.availableMw, envelopeLimit)
      const responseTimeSeconds = (envelope?.controlLatencySeconds ?? 30) + (envelope?.telemetryLatencySeconds ?? 30)
      const latencyPenalty = clamp((responseTimeSeconds - responseWindow * 60 * 0.35) / 12, 0, 24)
      const confidence =
        telemetryConfidence[asset.telemetry] *
        (asset.readiness / 100) *
        envelopeConfidence *
        (1 - latencyPenalty / 100)
      const marginalCost =
        asset.degradationCost + (100 - asset.customerFlex) * 0.22 + (1 - confidence) * 18 + latencyPenalty * 0.7

      return { asset, availableMw, confidence, latencyPenalty, marginalCost, responseTimeSeconds }
    })
    .sort((a, b) => a.marginalCost - b.marginalCost || b.confidence - a.confidence)

  let remaining = targetMw
  const allocations = meritOrder.map(({ asset, availableMw, confidence, latencyPenalty, marginalCost, responseTimeSeconds }) => {
    const envelope = envelopeFor(asset.id, market.interval, envelopes)
    const dispatchMw = Math.max(0, Math.min(availableMw, remaining))
    remaining -= dispatchMw
    const rampFeasibleMw = Math.min(
      dispatchMw,
      Math.max(0, envelope?.rampRateMwPerMinute ?? 1) * Math.max(0.5, responseWindow),
    )

    return {
      assetId: asset.id,
      dispatchMw,
      participationFactor: targetMw > 0 ? dispatchMw / targetMw : 0,
      marginalCost,
      confidence: confidence * 100,
      rampFeasibleMw,
      responseTimeSeconds,
      latencyPenalty,
    }
  })

  return allocations.filter((allocation) => allocation.dispatchMw > 0.05)
}

const evaluateConstraints = (
  targetMw: number,
  selectedAssets: Asset[],
  allocations: AssetDispatchAllocation[],
  market: MarketSignal,
  envelopes: FlexibilityEnvelope[],
  policies: ConstraintPolicy[],
): ConstraintEvaluation[] => {
  const totalAvailable = selectedAssets.reduce((sum, asset) => sum + asset.availableMw, 0)
  const envelopeCapacity = selectedAssets.reduce((sum, asset) => {
    const envelope = envelopeFor(asset.id, market.interval, envelopes)
    return sum + Math.min(asset.availableMw, envelope?.maxExportMw ?? asset.availableMw)
  }, 0)
  const weightedConfidence =
    allocations.reduce((sum, allocation) => sum + allocation.confidence * allocation.participationFactor, 0) || 0
  const rampFeasibleMw = allocations.reduce((sum, allocation) => sum + allocation.rampFeasibleMw, 0)
  const durationHours = intervalHours(market.interval)
  const requiredMwh = targetMw * durationHours
  const energyFeasibleMwh = allocations.reduce((sum, allocation) => {
    const asset = selectedAssets.find((item) => item.id === allocation.assetId)
    const envelope = envelopeFor(allocation.assetId, market.interval, envelopes)
    const sustainedHours = (envelope?.sustainedDurationMinutes ?? durationHours * 60) / 60
    const sustainedMwh = allocation.dispatchMw * Math.min(durationHours, sustainedHours)
    const stateOfChargeMwh =
      asset?.type === 'Battery' && typeof asset.stateOfCharge === 'number'
        ? asset.capacityMw * (asset.stateOfCharge / 100)
        : Number.POSITIVE_INFINITY

    return sum + Math.min(sustainedMwh, stateOfChargeMwh)
  }, 0)

  const systemConstraints: ConstraintEvaluation[] = [
    {
      id: 'available-capacity',
      label: 'Dispatch target within available MW',
      lhs: targetMw,
      operator: '<=',
      rhs: totalAvailable,
      slack: totalAvailable - targetMw,
      severity: 'binding',
      satisfied: targetMw <= totalAvailable,
    },
    {
      id: 'flexibility-envelope',
      label: 'Dispatch target within interval flexibility envelope',
      lhs: targetMw,
      operator: '<=',
      rhs: envelopeCapacity,
      slack: envelopeCapacity - targetMw,
      severity: 'binding',
      satisfied: targetMw <= envelopeCapacity,
    },
    {
      id: 'source-confidence',
      label: 'Weighted source confidence above operator floor',
      lhs: weightedConfidence,
      operator: '>=',
      rhs: market.risk === 'high' ? 78 : 70,
      slack: weightedConfidence - (market.risk === 'high' ? 78 : 70),
      severity: market.risk === 'high' ? 'binding' : 'advisory',
      satisfied: weightedConfidence >= (market.risk === 'high' ? 78 : 70),
    },
    {
      id: 'ramp-response',
      label: `Dispatch can ramp inside ${responseWindowMinutes(market)} min response window`,
      lhs: rampFeasibleMw,
      operator: '>=',
      rhs: targetMw,
      slack: rampFeasibleMw - targetMw,
      severity: market.product === 'Frequency regulation' || market.product === 'Reserve' ? 'binding' : 'advisory',
      satisfied: rampFeasibleMw >= targetMw,
    },
    {
      id: 'energy-duration',
      label: `Energy and duration support ${market.interval} dispatch`,
      lhs: energyFeasibleMwh,
      operator: '>=',
      rhs: requiredMwh,
      slack: energyFeasibleMwh - requiredMwh,
      severity: market.product === 'Energy arbitrage' || market.product === 'Capacity event' ? 'binding' : 'advisory',
      satisfied: energyFeasibleMwh >= requiredMwh,
    },
  ]

  const policyConstraints = policies
    .filter((policy) => selectedAssets.some((asset) => asset.id === policy.assetId))
    .map((policy) => {
      const allocation = allocations.find((item) => item.assetId === policy.assetId)
      const asset = selectedAssets.find((item) => item.id === policy.assetId)
      const approvalBuffer = policy.operatorApprovalRequired ? 0.82 : 1
      const rhs = (asset?.availableMw ?? 0) * approvalBuffer
      const lhs = allocation?.dispatchMw ?? 0

      return {
        id: policy.id,
        label: policy.rule,
        lhs,
        operator: '<=' as const,
        rhs,
        slack: rhs - lhs,
        severity: policy.severity,
        satisfied: lhs <= rhs,
      }
    })

  return [...systemConstraints, ...policyConstraints]
}

const weightedQuantile = (values: { value: number; probability: number }[], quantile: number) => {
  const ordered = [...values].sort((a, b) => a.value - b.value)
  let cumulative = 0
  for (const item of ordered) {
    cumulative += item.probability
    if (cumulative >= quantile) return item.value
  }
  return ordered.at(-1)?.value ?? 0
}

const downsideMean = (values: { value: number; probability: number }[], quantile: number) => {
  const threshold = weightedQuantile(values, quantile)
  const tail = values.filter((item) => item.value <= threshold)
  const probability = tail.reduce((sum, item) => sum + item.probability, 0)
  return probability > 0
    ? tail.reduce((sum, item) => sum + item.value * item.probability, 0) / probability
    : threshold
}

const riskSeverity = (value: number, high: number, medium: number): RiskContribution['severity'] => {
  if (value >= high) return 'high'
  if (value >= medium) return 'medium'
  return 'low'
}

const objectiveContributions = (
  weights: ObjectiveWeights,
  revenueScore: number,
  reliabilityScore: number,
  obligationScore: number,
  degradationPenalty: number,
  customerPenalty: number,
  riskPenalty: number,
): ObjectiveContribution[] => [
  {
    key: 'revenue',
    label: 'Expected net revenue',
    weight: weights.revenue,
    normalizedValue: revenueScore,
    weightedValue: revenueScore * weights.revenue,
  },
  {
    key: 'reliability',
    label: 'Telemetry and response confidence',
    weight: weights.reliability,
    normalizedValue: reliabilityScore,
    weightedValue: reliabilityScore * weights.reliability,
  },
  {
    key: 'obligation',
    label: 'Obligation coverage',
    weight: weights.obligation,
    normalizedValue: obligationScore,
    weightedValue: obligationScore * weights.obligation,
  },
  {
    key: 'degradation',
    label: 'Asset wear penalty',
    weight: weights.degradation,
    normalizedValue: 100 - degradationPenalty,
    weightedValue: (100 - degradationPenalty) * weights.degradation,
  },
  {
    key: 'customer',
    label: 'Customer constraint preservation',
    weight: weights.customer,
    normalizedValue: 100 - customerPenalty,
    weightedValue: (100 - customerPenalty) * weights.customer,
  },
  {
    key: 'risk',
    label: 'Tail-risk penalty',
    weight: weights.risk,
    normalizedValue: 100 - riskPenalty,
    weightedValue: (100 - riskPenalty) * weights.risk,
  },
]

export const solveRobustDispatch = ({
  candidateId,
  targetMw,
  market,
  selectedAssets,
  weights,
  envelopes,
  policies,
}: {
  candidateId: string
  targetMw: number
  market: MarketSignal
  selectedAssets: Asset[]
  weights: ObjectiveWeights
  envelopes: FlexibilityEnvelope[]
  policies: ConstraintPolicy[]
}): RobustDecisionModel => {
  const allocations = allocateDispatch(targetMw, selectedAssets, market, envelopes)
  const scenarios = buildScenarioSet(market, selectedAssets)
  const constraints = evaluateConstraints(targetMw, selectedAssets, allocations, market, envelopes, policies)
  const availableMw = selectedAssets.reduce((sum, asset) => sum + asset.availableMw, 0)
  const deterministicEquivalentMw = allocations.reduce((sum, allocation) => sum + allocation.dispatchMw, 0)
  const rampFeasibleMw = allocations.reduce((sum, allocation) => sum + allocation.rampFeasibleMw, 0)
  const rampShortfallMw = Math.max(0, targetMw - rampFeasibleMw)
  const reserveMargin = availableMw - targetMw
  const controlRiskPenalty =
    allocations.reduce(
      (sum, allocation) => sum + allocation.latencyPenalty * allocation.participationFactor,
      0,
    ) + rampShortfallMw * 1.7
  const weightedMarginalCost = allocations.reduce(
    (sum, allocation) => sum + allocation.marginalCost * allocation.dispatchMw,
    0,
  )

  const scenarioOutcomes = scenarios.map((scenario) => {
    const availableUnderScenario = Math.max(
      0,
      Math.min(deterministicEquivalentMw, rampFeasibleMw) * scenario.variables.availabilityMultiplier -
        scenario.variables.weatherDerateMw,
    )
    const deliveredMw = Math.min(targetMw, availableUnderScenario)
    const shortfallMw = Math.max(0, targetMw - deliveredMw)
    const responseRiskMw = targetMw * scenario.variables.responseFailureProbability
    const effectiveShortfallMw = shortfallMw + responseRiskMw
    const grossRevenue = deliveredMw * market.price * scenario.variables.priceMultiplier
    const variableCost = weightedMarginalCost
    const imbalancePenalty =
      effectiveShortfallMw * market.price * 1.25 * scenario.variables.imbalancePenaltyMultiplier
    const netRevenue = grossRevenue - variableCost - imbalancePenalty

    return {
      scenarioId: scenario.id,
      label: scenario.label,
      probability: scenario.probability,
      deliveredMw,
      effectiveShortfallMw,
      grossRevenue,
      variableCost,
      imbalancePenalty,
      netRevenue,
    }
  })

  const expectedRevenue = scenarioOutcomes.reduce((sum, outcome) => sum + outcome.netRevenue * outcome.probability, 0)
  const expectedDeliveredMw = scenarioOutcomes.reduce(
    (sum, outcome) => sum + outcome.deliveredMw * outcome.probability,
    0,
  )
  const expectedShortfallMw = scenarioOutcomes.reduce(
    (sum, outcome) => sum + outcome.effectiveShortfallMw * outcome.probability,
    0,
  )
  const downsideRevenue = downsideMean(
    scenarioOutcomes.map((outcome) => ({ value: outcome.netRevenue, probability: outcome.probability })),
    0.2,
  )
  const cvar95 = downsideMean(
    scenarioOutcomes.map((outcome) => ({ value: outcome.netRevenue, probability: outcome.probability })),
    0.05,
  )

  const violationPenalty = constraints.reduce((sum, constraint) => {
    const normalizedViolation = constraint.satisfied ? 0 : Math.abs(constraint.slack) / Math.max(1, constraint.rhs)
    return sum + normalizedViolation * 100 * severityWeight[constraint.severity]
  }, 0)
  const feasibility = clamp(100 - violationPenalty)
  const revenueScore = clamp((expectedRevenue / Math.max(1, targetMw * market.price)) * 92)
  const reliabilityScore = clamp(
    (expectedDeliveredMw / Math.max(1, targetMw)) * 100 - expectedShortfallMw * 1.8 - controlRiskPenalty,
  )
  const obligationScore = clamp((expectedDeliveredMw / Math.max(1, market.obligationMw)) * 100)
  const degradationPenalty = allocations.length
    ? allocations.reduce((sum, allocation) => sum + allocation.marginalCost * allocation.participationFactor, 0)
    : 100
  const customerPenalty = selectedAssets.length
    ? 100 - selectedAssets.reduce((sum, asset) => sum + asset.customerFlex, 0) / selectedAssets.length
    : 100
  const riskPenalty = clamp(
    expectedShortfallMw * 4 +
      Math.max(0, expectedRevenue - downsideRevenue) / 120 +
      violationPenalty +
      controlRiskPenalty,
  )
  const tailLoss = Math.max(0, expectedRevenue - cvar95)
  const reserveDeficit = Math.max(0, -reserveMargin)
  const totalRiskBasis = Math.max(
    1,
    expectedShortfallMw + violationPenalty + controlRiskPenalty + tailLoss / 100 + reserveDeficit,
  )
  const riskContributions: RiskContribution[] = [
    {
      id: 'expected-shortfall',
      label: 'Expected delivery shortfall',
      value: expectedShortfallMw,
      share: expectedShortfallMw / totalRiskBasis,
      severity: riskSeverity(expectedShortfallMw, targetMw * 0.18, targetMw * 0.08),
    },
    {
      id: 'constraint-violations',
      label: 'Constraint violation penalty',
      value: violationPenalty,
      share: violationPenalty / totalRiskBasis,
      severity: riskSeverity(violationPenalty, 24, 8),
    },
    {
      id: 'control-latency',
      label: 'Control and telemetry latency',
      value: controlRiskPenalty,
      share: controlRiskPenalty / totalRiskBasis,
      severity: riskSeverity(controlRiskPenalty, 18, 7),
    },
    {
      id: 'tail-revenue',
      label: 'Tail revenue at risk',
      value: tailLoss / 100,
      share: tailLoss / 100 / totalRiskBasis,
      severity: riskSeverity(tailLoss, targetMw * market.price * 0.65, targetMw * market.price * 0.28),
    },
    {
      id: 'reserve-deficit',
      label: 'Reserve margin deficit',
      value: reserveDeficit,
      share: reserveDeficit / totalRiskBasis,
      severity: riskSeverity(reserveDeficit, targetMw * 0.14, targetMw * 0.04),
    },
  ].sort((a, b) => b.share - a.share)
  const objectiveContributionSet = objectiveContributions(
    weights,
    revenueScore,
    reliabilityScore,
    obligationScore,
    degradationPenalty,
    customerPenalty,
    riskPenalty,
  )
  const utility = objectiveContributionSet.reduce((sum, contribution) => sum + contribution.weightedValue, 0)
  const riskAdjustedScore = clamp(utility * 0.72 + feasibility * 0.22 + clamp(reserveMargin, 0, 35) * 0.18)

  return {
    candidateId,
    utility: Math.round(utility),
    expectedRevenue: Math.round(expectedRevenue),
    downsideRevenue: Math.round(downsideRevenue),
    cvar95: Math.round(cvar95),
    feasibility: Math.round(feasibility),
    deterministicEquivalentMw: Math.round(deterministicEquivalentMw * 10) / 10,
    rampFeasibleMw: Math.round(rampFeasibleMw * 10) / 10,
    rampShortfallMw: Math.round(rampShortfallMw * 10) / 10,
    controlRiskPenalty: Math.round(controlRiskPenalty * 10) / 10,
    reserveMargin: Math.round(reserveMargin * 10) / 10,
    expectedShortfallMw: Math.round(expectedShortfallMw * 10) / 10,
    violationPenalty: Math.round(violationPenalty * 10) / 10,
    riskAdjustedScore: Math.round(riskAdjustedScore),
    allocations: allocations.map((allocation) => ({
      ...allocation,
      dispatchMw: Math.round(allocation.dispatchMw * 10) / 10,
      participationFactor: Math.round(allocation.participationFactor * 1000) / 1000,
      marginalCost: Math.round(allocation.marginalCost * 10) / 10,
      confidence: Math.round(allocation.confidence),
      rampFeasibleMw: Math.round(allocation.rampFeasibleMw * 10) / 10,
      responseTimeSeconds: Math.round(allocation.responseTimeSeconds),
      latencyPenalty: Math.round(allocation.latencyPenalty * 10) / 10,
    })),
    scenarioOutcomes: scenarioOutcomes.map((outcome) => ({
      ...outcome,
      probability: Math.round(outcome.probability * 1000) / 1000,
      deliveredMw: Math.round(outcome.deliveredMw * 10) / 10,
      effectiveShortfallMw: Math.round(outcome.effectiveShortfallMw * 10) / 10,
      grossRevenue: Math.round(outcome.grossRevenue),
      variableCost: Math.round(outcome.variableCost),
      imbalancePenalty: Math.round(outcome.imbalancePenalty),
      netRevenue: Math.round(outcome.netRevenue),
    })),
    riskContributions: riskContributions.map((risk) => ({
      ...risk,
      value: Math.round(risk.value * 10) / 10,
      share: Math.round(risk.share * 100),
    })),
    objectiveContributions: objectiveContributionSet.map((contribution) => ({
      ...contribution,
      normalizedValue: Math.round(contribution.normalizedValue),
      weightedValue: Math.round(contribution.weightedValue * 10) / 10,
    })),
    constraints: constraints.map((constraint) => ({
      ...constraint,
      lhs: Math.round(constraint.lhs * 10) / 10,
      rhs: Math.round(constraint.rhs * 10) / 10,
      slack: Math.round(constraint.slack * 10) / 10,
    })),
    scenarios,
    assumptions: [
      'Scenario probabilities are normalized from market confidence, telemetry quality, grid stress, and asset readiness.',
      'Dispatch allocation uses a merit order of degradation cost, customer friction, telemetry confidence, and flexibility-envelope limits.',
      'Tail risk is represented with downside revenue and CVaR-style expected loss over low-probability underperformance scenarios.',
      'Ramp feasibility and control latency are penalized separately from economic availability.',
      'Energy-duration feasibility checks sustained envelope duration and battery state of charge against interval MWh requirements.',
      'Constraint violations are penalized by severity before the final operator-facing score is produced.',
    ],
  }
}

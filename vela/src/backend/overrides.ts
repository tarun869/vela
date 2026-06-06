import type { DecisionCandidate, DispatchPlan, OperatorOverride, OverrideImpact } from './types'

const clamp = (value: number, min = 0, max = Number.POSITIVE_INFINITY) => Math.min(max, Math.max(min, value))

export const operatorOverrides: OperatorOverride[] = [
  {
    id: 'override-evening-reserve-floor',
    target: 'candidate',
    targetId: 'Energy arbitrage-14:00-16:00',
    requestedBy: 'Shift supervisor',
    createdAt: '2026-06-05T18:58:15Z',
    reason: 'Hold additional BESS headroom until the evening RA call is confirmed.',
    status: 'proposed',
    limitMw: 64,
    expiresAt: '2026-06-05T22:00:00Z',
  },
  {
    id: 'override-iso-price-floor',
    target: 'market',
    targetId: 'CAISO NP15',
    requestedBy: 'Trading desk',
    createdAt: '2026-06-05T18:59:42Z',
    reason: 'Do not submit the advisory block if the real-time floor clears below desk risk tolerance.',
    status: 'approved',
    priceFloor: 172,
    expiresAt: '2026-06-05T21:00:00Z',
  },
  {
    id: 'override-hvac-comfort',
    target: 'asset',
    targetId: 'hvac-east',
    requestedBy: 'Customer success',
    createdAt: '2026-06-05T19:01:09Z',
    reason: 'Keep occupied-building load reductions below customer comfort-review threshold.',
    status: 'proposed',
    limitMw: 18,
    expiresAt: '2026-06-06T01:00:00Z',
  },
]

export const buildOverrideImpacts = (
  decision: DecisionCandidate,
  dispatchPlan: DispatchPlan,
  overrides: OperatorOverride[],
): OverrideImpact[] =>
  overrides.map((override) => {
    const matchingInstruction = dispatchPlan.instructions.find((instruction) => instruction.assetId === override.targetId)
    const appliesToDecision =
      override.targetId === decision.id ||
      override.targetId === decision.market.region ||
      Boolean(matchingInstruction)
    const targetMwBefore = matchingInstruction?.targetMw ?? decision.targetMw
    const targetMwAfter =
      appliesToDecision && typeof override.limitMw === 'number'
        ? clamp(Math.min(targetMwBefore, override.limitMw))
        : targetMwBefore
    const mwDelta = targetMwAfter - targetMwBefore
    const scoreDelta =
      override.status === 'rejected'
        ? 0
        : Math.round(mwDelta * 0.45 - (override.status === 'proposed' ? 3 : 0) - (override.priceFloor ? 2 : 0))
    const approvalImpact =
      override.status === 'rejected' ? 'none' : override.status === 'proposed' ? 'adds-review' : 'none'

    return {
      overrideId: override.id,
      label:
        override.target === 'market'
          ? `Market override for ${override.targetId}`
          : override.target === 'asset'
            ? `Asset override for ${override.targetId}`
            : `Candidate override for ${override.targetId}`,
      status: override.status,
      affectedTarget: override.targetId,
      targetMwBefore: Math.round(targetMwBefore * 10) / 10,
      targetMwAfter: Math.round(targetMwAfter * 10) / 10,
      scoreDelta,
      approvalImpact,
      rationale: appliesToDecision
        ? override.reason
        : 'Override is tracked for portfolio governance but does not change the current recommendation.',
    }
  })

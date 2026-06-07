import type { ConstraintPolicy, DecisionCandidate, DispatchPlan, FlexibilityEnvelope } from './types'

const envelopeRampRate = (assetId: string, interval: string, envelopes: FlexibilityEnvelope[]) =>
  envelopes.find((envelope) => envelope.assetId === assetId && envelope.interval === interval)?.rampRateMwPerMinute ??
  envelopes.find((envelope) => envelope.assetId === assetId)?.rampRateMwPerMinute ??
  1

export const buildDispatchPlan = (
  decision: DecisionCandidate,
  envelopes: FlexibilityEnvelope[],
  policies: ConstraintPolicy[],
): DispatchPlan => {
  const robustModel = decision.robustModel
  const policyByAsset = policies.reduce<Record<string, ConstraintPolicy[]>>((index, policy) => {
    index[policy.assetId] = [...(index[policy.assetId] ?? []), policy]
    return index
  }, {})
  const instructions =
    robustModel?.allocations.map((allocation) => {
      const approvalPolicies = policyByAsset[allocation.assetId]?.filter((policy) => policy.operatorApprovalRequired) ?? []

      return {
        assetId: allocation.assetId,
        action: decision.action,
        interval: decision.market.interval,
        targetMw: allocation.dispatchMw,
        rampRateMwPerMinute: envelopeRampRate(allocation.assetId, decision.market.interval, envelopes),
        requiresApproval: approvalPolicies.length > 0,
        reason:
          approvalPolicies[0]?.rule ??
          `Selected by merit order with ${allocation.confidence}% confidence and ${allocation.marginalCost}/MW marginal cost.`,
      }
    }) ?? []

  const blockedConstraints = robustModel?.constraints.filter((constraint) => !constraint.satisfied) ?? []
  const approvalRequired = instructions.filter((instruction) => instruction.requiresApproval)
  const lowConfidence = (robustModel?.feasibility ?? 0) < 75
  const bidQuantity = Math.max(
    0,
    Math.min(decision.targetMw, robustModel?.deterministicEquivalentMw ?? decision.targetMw) -
      (robustModel?.expectedShortfallMw ?? 0),
  )

  return {
    id: `plan-${decision.id}`,
    recommendationId: decision.id,
    mode: 'advisory',
    bidBlocks: [
      {
        product: decision.market.product,
        region: decision.market.region,
        interval: decision.market.interval,
        quantityMw: Math.round(bidQuantity * 10) / 10,
        limitPrice: Math.round(decision.market.price * 0.82),
        confidence: Math.min(decision.market.confidence, robustModel?.feasibility ?? decision.score),
        sourceCandidateId: decision.id,
      },
    ],
    instructions,
    approvalGates: [
      {
        id: 'constraint-satisfaction',
        label: 'Constraint satisfaction',
        status: blockedConstraints.length > 0 ? 'blocked' : 'clear',
        rationale:
          blockedConstraints.length > 0
            ? `${blockedConstraints.length} modeled constraints are violated.`
            : 'Modeled hard and soft constraints are satisfied.',
      },
      {
        id: 'operator-approval',
        label: 'Operator approval',
        status: approvalRequired.length > 0 ? 'needs-review' : 'clear',
        rationale:
          approvalRequired.length > 0
            ? `${approvalRequired.length} asset instructions require human approval before dispatch.`
            : 'No selected instruction requires explicit approval.',
      },
      {
        id: 'model-confidence',
        label: 'Model confidence',
        status: lowConfidence ? 'needs-review' : 'clear',
        rationale: lowConfidence
          ? 'Feasibility is below the operator review threshold.'
          : 'Scenario feasibility clears the operator review threshold.',
      },
    ],
    auditTrail: [
      {
        timestamp: '2026-06-05T18:55:02Z',
        actor: 'VELA mock optimizer',
        event: 'candidate_scored',
        detail: `Scored ${decision.action} candidate at ${decision.score}/100.`,
      },
      {
        timestamp: '2026-06-05T18:55:03Z',
        actor: 'VELA robust model',
        event: 'risk_screened',
        detail: `Expected shortfall ${robustModel?.expectedShortfallMw ?? 0} MW, reserve margin ${
          robustModel?.reserveMargin ?? 0
        } MW.`,
      },
      {
        timestamp: '2026-06-05T18:55:04Z',
        actor: 'VELA operator workflow',
        event: 'approval_gates_created',
        detail: 'Created advisory gates for constraints, approval, and model confidence.',
      },
    ],
  }
}

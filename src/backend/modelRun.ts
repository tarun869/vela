import type {
  AdapterNormalizationResult,
  CoordinationReadiness,
  DecisionCandidate,
  DispatchPlan,
  ModelRunInputRef,
  ModelRunSnapshot,
  OverrideImpact,
  SettlementProjection,
  ValidationFinding,
} from './types'

const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value))

const findingConfidence = (finding: ValidationFinding) => {
  if (finding.severity === 'fail') return 35
  if (finding.severity === 'watch') return 72
  return 96
}

const findingStatus = (finding: ValidationFinding): ModelRunInputRef['status'] => {
  if (finding.severity === 'fail') return 'blocked'
  if (finding.severity === 'watch') return 'warning'
  return 'used'
}

const dominantRiskLabel = (candidate: DecisionCandidate) =>
  candidate.robustModel?.riskContributions[0]?.label ?? 'No modeled risk contribution'

export const buildModelRunSnapshot = ({
  candidates,
  adapterResults,
  findings,
  dispatchPlan,
  overrideImpacts = [],
  settlementProjection,
  coordinationReadiness,
  readinessScore,
}: {
  candidates: DecisionCandidate[]
  adapterResults: AdapterNormalizationResult[]
  findings: ValidationFinding[]
  dispatchPlan: DispatchPlan
  overrideImpacts?: OverrideImpact[]
  settlementProjection: SettlementProjection
  coordinationReadiness?: CoordinationReadiness
  readinessScore: number
}): ModelRunSnapshot => {
  const topCandidate = candidates[0]
  const adapterRefs: ModelRunInputRef[] = adapterResults.map((result) => ({
    id: result.payloadId,
    source: `${result.vendor} ${result.adapter}`,
    recordType: 'adapter',
    confidence: result.confidence,
    status: result.warnings.length > 0 ? 'warning' : 'used',
  }))
  const validationRefs: ModelRunInputRef[] = findings.map((finding) => ({
    id: finding.id,
    source: finding.label,
    recordType: 'validation',
    confidence: findingConfidence(finding),
    status: findingStatus(finding),
  }))
  const decisionRefs: ModelRunInputRef[] = candidates.slice(0, 5).map((candidate) => ({
    id: candidate.id,
    source: `${candidate.market.product} ${candidate.market.interval}`,
    recordType: 'candidate',
    confidence: candidate.score,
    status: candidate.robustModel && candidate.robustModel.feasibility < 70 ? 'warning' : 'used',
  }))
  const overrideRefs: ModelRunInputRef[] = overrideImpacts.map((impact) => ({
    id: impact.overrideId,
    source: impact.label,
    recordType: 'override',
    confidence: impact.approvalImpact === 'blocks' ? 40 : impact.approvalImpact === 'adds-review' ? 68 : 88,
    status: impact.approvalImpact === 'blocks' ? 'blocked' : impact.approvalImpact === 'adds-review' ? 'warning' : 'used',
  }))
  const workflowRefs: ModelRunInputRef[] = [
    {
      id: dispatchPlan.id,
      source: 'Advisory dispatch plan',
      recordType: 'dispatch',
      confidence: Math.min(topCandidate?.score ?? 0, topCandidate?.robustModel?.feasibility ?? 0),
      status: dispatchPlan.approvalGates.some((gate) => gate.status === 'blocked') ? 'blocked' : 'used',
    },
    {
      id: settlementProjection.dispatchPlanId,
      source: 'Settlement projection',
      recordType: 'settlement',
      confidence: settlementProjection.netMargin > 0 ? 86 : 62,
      status: settlementProjection.netMargin > 0 ? 'used' : 'warning',
    },
  ]
  const coordinationRefs: ModelRunInputRef[] =
    coordinationReadiness?.checkpoints.map((checkpoint) => ({
      id: checkpoint.id,
      source: checkpoint.label,
      recordType: 'coordination',
      confidence: checkpoint.status === 'ready' ? 92 : checkpoint.status === 'review' ? 66 : 38,
      status: checkpoint.status === 'blocked' ? 'blocked' : checkpoint.status === 'review' ? 'warning' : 'used',
    })) ?? []
  const inputRefs = [...adapterRefs, ...validationRefs, ...decisionRefs, ...overrideRefs, ...workflowRefs, ...coordinationRefs]
  const evidenceConfidence = inputRefs.length
    ? inputRefs.reduce((sum, ref) => sum + ref.confidence, 0) / inputRefs.length
    : 0
  const rankedDecisions = candidates.slice(0, 5).map((candidate) => ({
    candidateId: candidate.id,
    action: candidate.action,
    product: candidate.market.product,
    interval: candidate.market.interval,
    score: candidate.score,
    feasibility: candidate.robustModel?.feasibility ?? 0,
    downsideRevenue: candidate.robustModel?.downsideRevenue ?? 0,
    dominantRisk: dominantRiskLabel(candidate),
  }))
  const blockedInputs = inputRefs.filter((ref) => ref.status === 'blocked')
  const warningInputs = inputRefs.filter((ref) => ref.status === 'warning')

  return {
    id: `run-${topCandidate?.id ?? 'unknown'}-20260605T1855Z`,
    createdAt: '2026-06-05T18:55:05Z',
    modelVersion: 'mock-robust-dispatch-v0.4',
    topCandidateId: topCandidate?.id ?? 'none',
    readinessScore,
    evidenceConfidence: Math.round(clamp(evidenceConfidence)),
    inputRefs,
    rankedDecisions,
    persistenceEvents: [
      ...dispatchPlan.auditTrail,
      {
        timestamp: '2026-06-05T18:55:05Z',
        actor: 'VELA model ledger',
        event: 'model_run_snapshot_created',
        detail: `Captured ${inputRefs.length} evidence references and ${rankedDecisions.length} ranked decisions.`,
      },
      {
        timestamp: '2026-06-05T18:55:06Z',
        actor: 'VELA settlement model',
        event: 'settlement_projection_attached',
        detail: `Projected ${Math.round(settlementProjection.expectedAwardMw)} MW award with $${Math.round(
          settlementProjection.netMargin,
        ).toLocaleString('en-US')} net margin.`,
      },
      {
        timestamp: '2026-06-05T19:01:12Z',
        actor: 'VELA override ledger',
        event: 'operator_overrides_screened',
        detail: `Attached ${overrideImpacts.length} operator override impacts to the model run.`,
      },
      {
        timestamp: '2026-06-05T19:03:24Z',
        actor: 'VELA coordination ledger',
        event: 'coordination_readiness_attached',
        detail: `Attached ${coordinationReadiness?.checkpoints.length ?? 0} coordination checkpoints at ${
          coordinationReadiness?.score ?? 0
        }% readiness.`,
      },
    ],
    decisionSummary:
      blockedInputs.length > 0
        ? `${blockedInputs.length} evidence refs block automatic dispatch; keep advisory mode.`
        : `${warningInputs.length} evidence refs need review before approving ${topCandidate?.targetMw ?? 0} MW.`,
  }
}

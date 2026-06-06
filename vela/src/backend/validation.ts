import type {
  AdapterNormalizationResult,
  Asset,
  ConstraintPolicy,
  FlexibilityEnvelope,
  MarketEnrollment,
  MarketSignal,
  TelemetrySample,
  ValidationFinding,
} from './types'

const assetName = (assets: Asset[], assetId: string) => assets.find((asset) => asset.id === assetId)?.name ?? assetId

export const validateTelemetryCoverage = (assets: Asset[], telemetry: TelemetrySample[]): ValidationFinding[] => {
  const telemetryByAsset = new Set(telemetry.map((sample) => sample.assetId))
  const missing = assets.filter((asset) => !telemetryByAsset.has(asset.id))
  const stale = telemetry.filter((sample) => sample.quality === 'stale' || sample.quality === 'missing')

  return [
    {
      id: 'telemetry-coverage',
      severity: missing.length === 0 ? 'pass' : missing.length > 2 ? 'fail' : 'watch',
      label: 'Telemetry coverage',
      detail:
        missing.length === 0
          ? 'All modeled assets have at least one current telemetry record.'
          : `${missing.length} modeled assets are missing current telemetry.`,
      affectedRecords: missing.map((asset) => asset.name),
    },
    {
      id: 'telemetry-freshness',
      severity: stale.length === 0 ? 'pass' : stale.some((sample) => sample.quality === 'missing') ? 'fail' : 'watch',
      label: 'Telemetry freshness',
      detail:
        stale.length === 0
          ? 'Telemetry used for dispatch scoring is fresh enough for operator review.'
          : `${stale.length} telemetry sources are stale or missing.`,
      affectedRecords: stale.map((sample) => assetName(assets, sample.assetId)),
    },
  ]
}

export const validateFlexibilityCoverage = (assets: Asset[], envelopes: FlexibilityEnvelope[]): ValidationFinding[] => {
  const envelopeByAsset = new Set(envelopes.map((envelope) => envelope.assetId))
  const dispatchableAssets = assets.filter((asset) => asset.availableMw > 0)
  const missing = dispatchableAssets.filter((asset) => !envelopeByAsset.has(asset.id))
  const lowConfidence = envelopes.filter((envelope) => envelope.confidence < 70)

  return [
    {
      id: 'flexibility-coverage',
      severity: missing.length === 0 ? 'pass' : missing.length > 1 ? 'fail' : 'watch',
      label: 'Flexibility coverage',
      detail:
        missing.length === 0
          ? 'Dispatchable assets have interval flexibility envelopes.'
          : `${missing.length} dispatchable assets are missing interval envelopes.`,
      affectedRecords: missing.map((asset) => asset.name),
    },
    {
      id: 'flexibility-confidence',
      severity: lowConfidence.length === 0 ? 'pass' : 'watch',
      label: 'Flexibility confidence',
      detail:
        lowConfidence.length === 0
          ? 'Flexibility envelopes clear the confidence floor.'
          : `${lowConfidence.length} envelopes are below the confidence floor.`,
      affectedRecords: lowConfidence.map((envelope) => assetName(assets, envelope.assetId)),
    },
  ]
}

export const validateMarketSignals = (signals: MarketSignal[]): ValidationFinding[] => {
  const lowConfidence = signals.filter((signal) => signal.confidence < 70)
  const highRisk = signals.filter((signal) => signal.risk === 'high')

  return [
    {
      id: 'market-confidence',
      severity: lowConfidence.length === 0 ? 'pass' : 'watch',
      label: 'Market confidence',
      detail:
        lowConfidence.length === 0
          ? 'Market signals clear the confidence floor.'
          : `${lowConfidence.length} market signals are below the confidence floor.`,
      affectedRecords: lowConfidence.map((signal) => `${signal.product} ${signal.region}`),
    },
    {
      id: 'market-tail-risk',
      severity: highRisk.length === 0 ? 'pass' : 'watch',
      label: 'Market tail risk',
      detail:
        highRisk.length === 0
          ? 'No active market signal is marked high risk.'
          : `${highRisk.length} market signals require downside-risk review.`,
      affectedRecords: highRisk.map((signal) => `${signal.product} ${signal.interval}`),
    },
  ]
}

export const validateConstraintPolicies = (assets: Asset[], policies: ConstraintPolicy[]): ValidationFinding[] => {
  const assetIds = new Set(assets.map((asset) => asset.id))
  const orphaned = policies.filter((policy) => !assetIds.has(policy.assetId))
  const approvals = policies.filter((policy) => policy.operatorApprovalRequired)

  return [
    {
      id: 'constraint-integrity',
      severity: orphaned.length === 0 ? 'pass' : 'fail',
      label: 'Constraint integrity',
      detail:
        orphaned.length === 0
          ? 'Constraint policies map to known canonical assets.'
          : `${orphaned.length} policies reference unknown assets.`,
      affectedRecords: orphaned.map((policy) => policy.id),
    },
    {
      id: 'approval-surface',
      severity: approvals.length === 0 ? 'pass' : 'watch',
      label: 'Operator approval surface',
      detail:
        approvals.length === 0
          ? 'No active constraints require pre-dispatch approval.'
          : `${approvals.length} active constraints require operator approval.`,
      affectedRecords: approvals.map((policy) => assetName(assets, policy.assetId)),
    },
  ]
}

export const validateMarketEnrollments = (
  assets: Asset[],
  signals: MarketSignal[],
  enrollments: MarketEnrollment[],
): ValidationFinding[] => {
  const assetIds = new Set(assets.map((asset) => asset.id))
  const orphaned = enrollments.filter((enrollment) => !assetIds.has(enrollment.assetId))
  const suspended = enrollments.filter((enrollment) => enrollment.status === 'suspended')
  const uncoveredSignals = signals.filter(
    (signal) =>
      !enrollments.some(
        (enrollment) =>
          enrollment.product === signal.product &&
          enrollment.region === signal.region &&
          enrollment.status === 'active',
      ),
  )
  const tightTelemetry = enrollments.filter(
    (enrollment) => enrollment.status === 'active' && enrollment.telemetryRequirementSeconds <= 10,
  )

  return [
    {
      id: 'market-enrollment-coverage',
      severity: uncoveredSignals.length === 0 ? 'pass' : uncoveredSignals.length > 1 ? 'fail' : 'watch',
      label: 'Market enrollment coverage',
      detail:
        uncoveredSignals.length === 0
          ? 'Active market signals have at least one active enrolled asset.'
          : `${uncoveredSignals.length} market signals lack active enrollment coverage.`,
      affectedRecords: uncoveredSignals.map((signal) => `${signal.product} ${signal.region}`),
    },
    {
      id: 'market-enrollment-integrity',
      severity: orphaned.length === 0 && suspended.length === 0 ? 'pass' : orphaned.length > 0 ? 'fail' : 'watch',
      label: 'Enrollment integrity',
      detail:
        orphaned.length === 0 && suspended.length === 0
          ? 'Market enrollment records map cleanly to modeled assets.'
          : `${orphaned.length} orphaned and ${suspended.length} suspended enrollment records need review.`,
      affectedRecords: [...orphaned.map((enrollment) => enrollment.id), ...suspended.map((enrollment) => enrollment.id)],
    },
    {
      id: 'enrollment-telemetry-requirements',
      severity: tightTelemetry.length === 0 ? 'pass' : 'watch',
      label: 'Enrollment telemetry requirements',
      detail:
        tightTelemetry.length === 0
          ? 'Active enrollment telemetry requirements are compatible with modeled control loops.'
          : `${tightTelemetry.length} active enrollments require sub-10-second telemetry.`,
      affectedRecords: tightTelemetry.map((enrollment) => assetName(assets, enrollment.assetId)),
    },
  ]
}

export const validateAdapterResults = (results: AdapterNormalizationResult[]): ValidationFinding[] => {
  const warningResults = results.filter((result) => result.warnings.length > 0)
  const lowConfidence = results.filter((result) => result.confidence < 70)

  return [
    {
      id: 'adapter-warnings',
      severity: warningResults.length === 0 ? 'pass' : 'watch',
      label: 'Adapter warnings',
      detail:
        warningResults.length === 0
          ? 'Adapter normalization completed without warnings.'
          : `${warningResults.length} adapter payloads emitted normalization warnings.`,
      affectedRecords: warningResults.map((result) => result.payloadId),
    },
    {
      id: 'adapter-confidence',
      severity: lowConfidence.length === 0 ? 'pass' : 'watch',
      label: 'Adapter confidence',
      detail:
        lowConfidence.length === 0
          ? 'Normalized adapter payloads clear the confidence floor.'
          : `${lowConfidence.length} normalized payloads are below confidence floor.`,
      affectedRecords: lowConfidence.map((result) => result.payloadId),
    },
  ]
}

export const buildReadinessFindings = ({
  assets,
  telemetry,
  envelopes,
  signals,
  policies,
  enrollments = [],
  adapterResults,
}: {
  assets: Asset[]
  telemetry: TelemetrySample[]
  envelopes: FlexibilityEnvelope[]
  signals: MarketSignal[]
  policies: ConstraintPolicy[]
  enrollments?: MarketEnrollment[]
  adapterResults: AdapterNormalizationResult[]
}) => [
  ...validateTelemetryCoverage(assets, telemetry),
  ...validateFlexibilityCoverage(assets, envelopes),
  ...validateMarketSignals(signals),
  ...validateConstraintPolicies(assets, policies),
  ...validateMarketEnrollments(assets, signals, enrollments),
  ...validateAdapterResults(adapterResults),
]

export const readinessScore = (findings: ValidationFinding[]) => {
  const penalty = findings.reduce((sum, finding) => {
    if (finding.severity === 'fail') return sum + 24
    if (finding.severity === 'watch') return sum + 9
    return sum
  }, 0)

  return Math.max(0, 100 - penalty)
}

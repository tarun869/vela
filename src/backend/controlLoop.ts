import type {
  ConstraintPolicy,
  ControlLoopCheck,
  FlexibilityEnvelope,
  MarketEnrollment,
  TelemetrySample,
} from './types'

const telemetryAgeSeconds = (quality: TelemetrySample['quality']) => {
  if (quality === 'valid') return 2
  if (quality === 'estimated') return 45
  if (quality === 'stale') return 900
  return 1800
}

export const buildControlLoopChecks = ({
  enrollments,
  envelopes,
  telemetry,
  policies,
}: {
  enrollments: MarketEnrollment[]
  envelopes: FlexibilityEnvelope[]
  telemetry: TelemetrySample[]
  policies: ConstraintPolicy[]
}): ControlLoopCheck[] =>
  enrollments.map((enrollment) => {
    const envelope = envelopes.find(
      (item) => item.assetId === enrollment.assetId && item.interval === enrollment.product,
    ) ?? envelopes.find((item) => item.assetId === enrollment.assetId)
    const sample = telemetry.find((item) => item.assetId === enrollment.assetId)
    const approvalRequired = policies.some((policy) => policy.assetId === enrollment.assetId && policy.operatorApprovalRequired)
    const observedLoopSeconds =
      (envelope?.controlLatencySeconds ?? 120) +
      (envelope?.telemetryLatencySeconds ?? 120) +
      telemetryAgeSeconds(sample?.quality ?? 'missing')
    const latencySlackSeconds = Math.round(enrollment.telemetryRequirementSeconds - observedLoopSeconds)
    const rampHeadroomMw = Math.round(((envelope?.rampRateMwPerMinute ?? 0) * 5 - enrollment.minOfferMw) * 10) / 10
    const status =
      enrollment.status !== 'active' || latencySlackSeconds < -120
        ? 'blocked'
        : latencySlackSeconds < 0 || approvalRequired || rampHeadroomMw < 0
          ? 'watch'
          : 'ready'

    return {
      assetId: enrollment.assetId,
      product: enrollment.product,
      interval: envelope?.interval ?? 'not modeled',
      telemetryRequirementSeconds: enrollment.telemetryRequirementSeconds,
      observedLoopSeconds: Math.round(observedLoopSeconds),
      latencySlackSeconds,
      rampHeadroomMw,
      approvalRequired,
      status,
      note:
        status === 'ready'
          ? 'Telemetry and control loop clear the program cadence.'
          : status === 'watch'
            ? 'Dispatch can be packaged, but latency, ramping, or approval needs review.'
            : 'Do not release this product until enrollment or control-loop blockers clear.',
    }
  })

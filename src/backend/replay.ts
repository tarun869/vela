import type { ModelRunInputRef, ModelRunInputRefType, ModelRunSnapshot, ReplayManifest } from './types'

const replayRequiredTypes: ModelRunInputRefType[] = [
  'adapter',
  'validation',
  'candidate',
  'dispatch',
  'settlement',
  'override',
  'coordination',
]

const shortFingerprint = (value: string) => {
  let hash = 2166136261

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }

  return `vela-${(hash >>> 0).toString(16).padStart(8, '0')}`
}

const refsByType = (refs: ModelRunInputRef[], recordType: ModelRunInputRefType) =>
  refs.filter((ref) => ref.recordType === recordType)

export const buildReplayManifest = (snapshot: ModelRunSnapshot): ReplayManifest => {
  const coverage = replayRequiredTypes.map((recordType) => {
    const refs = refsByType(snapshot.inputRefs, recordType)
    const confidence = refs.length
      ? Math.round(refs.reduce((sum, ref) => sum + ref.confidence, 0) / refs.length)
      : 0

    return {
      recordType,
      used: refs.filter((ref) => ref.status === 'used').length,
      warnings: refs.filter((ref) => ref.status === 'warning').length,
      blocked: refs.filter((ref) => ref.status === 'blocked').length,
      confidence,
    }
  })
  const missing = coverage.filter((item) => item.used + item.warnings + item.blocked === 0)
  const blocked = snapshot.inputRefs.filter((ref) => ref.status === 'blocked')
  const warnings = snapshot.inputRefs.filter((ref) => ref.status === 'warning')
  const gaps = [
    ...missing.map((item) => ({
      id: `missing-${item.recordType}`,
      severity: 'blocked' as const,
      label: `Missing ${item.recordType} evidence`,
      detail: 'Replay package cannot reconstruct this step from persisted refs.',
    })),
    ...blocked.slice(0, 4).map((ref) => ({
      id: `blocked-${ref.recordType}-${ref.id}`,
      severity: 'blocked' as const,
      label: `${ref.source} is blocked`,
      detail: `${ref.recordType} evidence is present but blocks automatic dispatch.`,
    })),
    ...warnings.slice(0, 4).map((ref) => ({
      id: `warning-${ref.recordType}-${ref.id}`,
      severity: 'watch' as const,
      label: `${ref.source} needs review`,
      detail: `${ref.recordType} evidence is available with ${ref.confidence}% confidence.`,
    })),
  ]
  const fingerprintSource = [
    snapshot.id,
    snapshot.modelVersion,
    snapshot.topCandidateId,
    ...snapshot.inputRefs.map((ref) => `${ref.recordType}:${ref.id}:${ref.status}:${ref.confidence}`),
    ...snapshot.rankedDecisions.map((decision) => `${decision.candidateId}:${decision.score}:${decision.feasibility}`),
  ].join('|')

  return {
    runId: snapshot.id,
    fingerprint: shortFingerprint(fingerprintSource),
    replayReady: missing.length === 0 && blocked.length === 0,
    coverage,
    gaps,
    generatedAt: '2026-06-05T19:05:00Z',
  }
}

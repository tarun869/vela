import { describe, expect, it } from 'vitest'
import { buildReplayManifest } from './replay'
import type { ModelRunSnapshot } from './types'

const snapshot: ModelRunSnapshot = {
  id: 'run-test',
  createdAt: '2026-06-05T19:05:00Z',
  modelVersion: 'test-model',
  topCandidateId: 'candidate-1',
  readinessScore: 82,
  evidenceConfidence: 78,
  inputRefs: [
    { id: 'raw-1', source: 'BMS', recordType: 'adapter', confidence: 94, status: 'used' },
    { id: 'validation-1', source: 'Validation', recordType: 'validation', confidence: 72, status: 'warning' },
    { id: 'candidate-1', source: 'Energy 14:00', recordType: 'candidate', confidence: 86, status: 'used' },
    { id: 'dispatch-1', source: 'Dispatch plan', recordType: 'dispatch', confidence: 83, status: 'used' },
    { id: 'settlement-1', source: 'Settlement', recordType: 'settlement', confidence: 81, status: 'used' },
    { id: 'override-1', source: 'Override', recordType: 'override', confidence: 68, status: 'warning' },
    { id: 'coord-1', source: 'Coordination', recordType: 'coordination', confidence: 38, status: 'blocked' },
  ],
  rankedDecisions: [
    {
      candidateId: 'candidate-1',
      action: 'sell',
      product: 'Energy arbitrage',
      interval: '14:00-16:00',
      score: 86,
      feasibility: 81,
      downsideRevenue: -1200,
      dominantRisk: 'Telemetry latency',
    },
  ],
  persistenceEvents: [],
  decisionSummary: '1 evidence ref blocks automatic dispatch.',
}

describe('buildReplayManifest', () => {
  it('builds coverage, gaps, and a stable fingerprint from a snapshot', () => {
    const manifest = buildReplayManifest(snapshot)
    const repeated = buildReplayManifest(snapshot)

    expect(manifest.fingerprint).toBe(repeated.fingerprint)
    expect(manifest.replayReady).toBe(false)
    expect(manifest.coverage).toHaveLength(7)
    expect(manifest.gaps.some((gap) => gap.id === 'blocked-coordination-coord-1')).toBe(true)
  })

  it('flags missing required evidence types', () => {
    const manifest = buildReplayManifest({
      ...snapshot,
      inputRefs: snapshot.inputRefs.filter((ref) => ref.recordType !== 'override'),
    })

    expect(manifest.gaps.some((gap) => gap.id === 'missing-override')).toBe(true)
    expect(manifest.replayReady).toBe(false)
  })
})

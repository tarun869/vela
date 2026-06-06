import { describe, expect, it } from 'vitest'
import { buildCoordinationReadiness } from './coordination'
import type { CoordinationCheckpoint } from './types'

const checkpoints: CoordinationCheckpoint[] = [
  {
    id: 'ready-low',
    label: 'Ready gate',
    owner: 'Aggregator',
    requirement: 'Complete registration evidence.',
    evidence: 'Registration package is present.',
    status: 'ready',
    risk: 'low',
    dueBy: 'T-120 min',
  },
  {
    id: 'review-medium',
    label: 'Review gate',
    owner: 'Distribution utility',
    requirement: 'Distribution review evidence.',
    evidence: 'Feeder model is not linked.',
    status: 'review',
    risk: 'medium',
    dueBy: 'T-60 min',
  },
  {
    id: 'blocked-high',
    label: 'Blocked gate',
    owner: 'Customer',
    requirement: 'Customer approval evidence.',
    evidence: 'Approval is missing.',
    status: 'blocked',
    risk: 'high',
    dueBy: 'Before approval',
  },
]

describe('buildCoordinationReadiness', () => {
  it('counts checkpoint states and risk-adjusts the readiness score', () => {
    const readiness = buildCoordinationReadiness(checkpoints)

    expect(readiness.readyCount).toBe(1)
    expect(readiness.reviewCount).toBe(1)
    expect(readiness.blockedCount).toBe(1)
    expect(readiness.score).toBe(52)
  })

  it('returns an empty score for no checkpoints', () => {
    expect(buildCoordinationReadiness([])).toMatchObject({
      score: 0,
      readyCount: 0,
      reviewCount: 0,
      blockedCount: 0,
      checkpoints: [],
    })
  })
})

import type { CoordinationCheckpoint, CoordinationReadiness } from './types'

const statusScore: Record<CoordinationCheckpoint['status'], number> = {
  ready: 100,
  review: 64,
  blocked: 18,
}

const riskPenalty: Record<CoordinationCheckpoint['risk'], number> = {
  low: 0,
  medium: 8,
  high: 18,
}

export const buildCoordinationReadiness = (
  checkpoints: CoordinationCheckpoint[],
): CoordinationReadiness => {
  const readyCount = checkpoints.filter((item) => item.status === 'ready').length
  const reviewCount = checkpoints.filter((item) => item.status === 'review').length
  const blockedCount = checkpoints.filter((item) => item.status === 'blocked').length
  const weightedScore = checkpoints.length
    ? checkpoints.reduce((sum, item) => sum + statusScore[item.status] - riskPenalty[item.risk], 0) / checkpoints.length
    : 0

  return {
    score: Math.max(0, Math.round(weightedScore)),
    readyCount,
    reviewCount,
    blockedCount,
    checkpoints,
  }
}

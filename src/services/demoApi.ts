import type {
  DemoAssetIn,
  ExtractionResult,
  ExtractionReview,
  FleetDispatchPlan,
  SettlementSummary,
  DispatchRecord,
  ObligationIn,
} from '../types/demo'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${init?.method ?? 'GET'} ${url} → ${res.status}: ${body}`)
  }
  return res.json() as Promise<T>
}

export function extractPortfolio(files: File[]): Promise<ExtractionReview> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return request('/api/v1/extraction/portfolio', { method: 'POST', body: form })
}

export function confirmExtraction(
  result: ExtractionResult,
): Promise<{ success: boolean; asset_ids: number[]; obligation_ids: number[] }> {
  return request('/api/v1/extraction/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(result),
  })
}

export function startDemoFleet(
  assets: DemoAssetIn[],
): Promise<{ status: string; assets: string[] }> {
  return request('/api/v1/fleet/demo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(assets),
  })
}

export function getFleetState(): Promise<Record<string, unknown>> {
  return request('/api/v1/fleet/state')
}

export function startDispatch(
  interval_seconds = 300,
  obligations: ObligationIn[] = [],
): Promise<{ status: string; obligations: number }> {
  return request('/api/v1/dispatch/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval_seconds, obligations }),
  })
}

export function overrideDispatch(body: {
  asset_id: string
  mw: number
  reason: string
}): Promise<{ status: string; asset_id: string }> {
  return request('/api/v1/dispatch/override', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getCurrentPlan(): Promise<FleetDispatchPlan | null> {
  return request('/api/v1/dispatch/current')
}

export function getSettlementSummary(): Promise<SettlementSummary> {
  return request('/api/v1/settlement/summary')
}

export function getSettlementRecords(): Promise<DispatchRecord[]> {
  return request('/api/v1/settlement/records')
}

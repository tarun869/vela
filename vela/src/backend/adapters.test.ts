import { describe, expect, it } from 'vitest'
import { adapterCoverage, normalizeAdapterPayload, normalizeAdapterPayloads } from './adapters'
import type { RawAdapterPayload } from './types'

describe('normalizeAdapterPayload', () => {
  it('marks stale telemetry and removes absent state of charge', () => {
    const result = normalizeAdapterPayload({
      id: 'raw-stale',
      adapter: 'SCADA',
      vendor: 'Site EMS',
      receivedAt: '2026-06-05T18:55:02Z',
      schemaVersion: 'vendor.scada.v1',
      payload: {
        assetId: 'asset-1',
        timestamp: '2026-06-05T18:42:00Z',
        secondsOld: 500,
        mw: 12.4,
      },
    })

    expect(result.confidence).toBe(64)
    expect(result.warnings).toContain('Telemetry freshness exceeds dispatch-quality threshold.')
    expect(result.records[0]).toMatchObject({
      kind: 'telemetry',
      record: {
        assetId: 'asset-1',
        realPowerMw: 12.4,
        quality: 'stale',
      },
    })
    expect('stateOfCharge' in result.records[0].record).toBe(false)
  })

  it('normalizes low-confidence market payloads with a warning', () => {
    const result = normalizeAdapterPayload({
      id: 'raw-market',
      adapter: 'ISO market',
      vendor: 'ISO feed',
      receivedAt: '2026-06-05T18:55:02Z',
      schemaVersion: 'iso.rtm.v1',
      payload: {
        product: 'Reserve',
        region: 'CAISO NP15',
        price: 75,
        confidence: 65,
        obligationMw: 20,
        interval: '15:00-16:00',
        gridCondition: 'normal',
      },
    })

    expect(result.records[0]).toMatchObject({
      kind: 'market',
      record: {
        product: 'Reserve',
        risk: 'low',
        confidence: 65,
      },
    })
    expect(result.warnings).toContain('Market confidence below automatic-bid threshold.')
  })
})

describe('adapterCoverage', () => {
  it('counts normalized record kinds and warnings', () => {
    const payloads: RawAdapterPayload[] = [
      {
        id: 'raw-flex',
        adapter: 'BMS gateway',
        vendor: 'Building controls',
        receivedAt: '2026-06-05T18:55:02Z',
        schemaVersion: 'flex.v1',
        payload: {
          assetId: 'asset-2',
          maxExportMw: 0,
          maxImportMw: 0,
        },
      },
      {
        id: 'raw-rule',
        adapter: 'Rules engine',
        vendor: 'Customer rules',
        receivedAt: '2026-06-05T18:55:02Z',
        schemaVersion: 'rules.v1',
        payload: {
          assetId: 'asset-2',
          ruleId: 'rule-1',
          rule: 'Approval required.',
          severity: 'binding',
        },
      },
    ]
    const coverage = adapterCoverage(normalizeAdapterPayloads(payloads))

    expect(coverage.recordCounts.flexibility).toBe(1)
    expect(coverage.recordCounts.constraint).toBe(1)
    expect(coverage.warningCount).toBe(2)
    expect(coverage.adaptersOnline).toBe(2)
  })
})

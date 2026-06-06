import type {
  AdapterNormalizationResult,
  ConstraintPolicy,
  FlexibilityEnvelope,
  GridCondition,
  MarketSignal,
  MarketProduct,
  NormalizedRecord,
  RawAdapterPayload,
  TelemetrySample,
} from './types'

const numberField = (payload: RawAdapterPayload, key: string, fallback = 0) => {
  const value = payload.payload[key]
  return typeof value === 'number' ? value : fallback
}

const stringField = (payload: RawAdapterPayload, key: string, fallback = '') => {
  const value = payload.payload[key]
  return typeof value === 'string' ? value : fallback
}

const booleanField = (payload: RawAdapterPayload, key: string, fallback = false) => {
  const value = payload.payload[key]
  return typeof value === 'boolean' ? value : fallback
}

const marketProducts: MarketProduct[] = [
  'Energy arbitrage',
  'Frequency regulation',
  'Capacity event',
  'Demand response',
  'Reserve',
]

const gridConditions: GridCondition[] = ['normal', 'scarcity', 'congested', 'oversupply']
const severities: ConstraintPolicy['severity'][] = ['binding', 'advisory', 'monitor']

const marketProductField = (payload: RawAdapterPayload, key: string): MarketProduct => {
  const value = stringField(payload, key)
  return marketProducts.includes(value as MarketProduct) ? (value as MarketProduct) : 'Energy arbitrage'
}

const gridConditionField = (payload: RawAdapterPayload, key: string): GridCondition => {
  const value = stringField(payload, key)
  return gridConditions.includes(value as GridCondition) ? (value as GridCondition) : 'normal'
}

const severityField = (payload: RawAdapterPayload, key: string): ConstraintPolicy['severity'] => {
  const value = stringField(payload, key)
  return severities.includes(value as ConstraintPolicy['severity']) ? (value as ConstraintPolicy['severity']) : 'advisory'
}

const qualityFromFreshness = (secondsOld: number): TelemetrySample['quality'] => {
  if (secondsOld <= 10) return 'valid'
  if (secondsOld <= 120) return 'estimated'
  if (secondsOld <= 900) return 'stale'
  return 'missing'
}

const confidenceFromFreshness = (secondsOld: number, baseConfidence: number) => {
  if (secondsOld <= 10) return baseConfidence
  if (secondsOld <= 120) return Math.round(baseConfidence * 0.88)
  if (secondsOld <= 900) return Math.round(baseConfidence * 0.68)
  return Math.round(baseConfidence * 0.34)
}

const normalizeTelemetry = (payload: RawAdapterPayload): AdapterNormalizationResult => {
  const secondsOld = numberField(payload, 'secondsOld', 0)
  const assetId = stringField(payload, 'assetId')
  const telemetry: TelemetrySample = {
    assetId,
    source: `${payload.vendor} ${payload.adapter}`,
    timestamp: stringField(payload, 'timestamp', payload.receivedAt),
    realPowerMw: numberField(payload, 'mw'),
    reactivePowerMvar: numberField(payload, 'mvar'),
    stateOfCharge: numberField(payload, 'soc', Number.NaN),
    breakerClosed: booleanField(payload, 'breakerClosed', true),
    quality: qualityFromFreshness(secondsOld),
  }

  if (Number.isNaN(telemetry.stateOfCharge)) {
    delete telemetry.stateOfCharge
  }

  const warnings = [
    !assetId ? 'Payload missing canonical asset id.' : '',
    secondsOld > 120 ? 'Telemetry freshness exceeds dispatch-quality threshold.' : '',
  ].filter(Boolean)

  return {
    payloadId: payload.id,
    adapter: payload.adapter,
    vendor: payload.vendor,
    receivedAt: payload.receivedAt,
    confidence: confidenceFromFreshness(secondsOld, 94),
    records: [{ kind: 'telemetry', record: telemetry }],
    warnings,
  }
}

const normalizeFlexibility = (payload: RawAdapterPayload): AdapterNormalizationResult => {
  const confidence = numberField(payload, 'confidence', 78)
  const record: FlexibilityEnvelope = {
    assetId: stringField(payload, 'assetId'),
    interval: stringField(payload, 'interval', 'current'),
    maxExportMw: numberField(payload, 'maxExportMw'),
    maxImportMw: numberField(payload, 'maxImportMw'),
    sustainedDurationMinutes: numberField(payload, 'durationMinutes', 60),
    rampRateMwPerMinute: numberField(payload, 'rampRateMwPerMinute', 1),
    controlLatencySeconds: numberField(payload, 'controlLatencySeconds', 30),
    telemetryLatencySeconds: numberField(payload, 'telemetryLatencySeconds', 30),
    confidence,
  }

  return {
    payloadId: payload.id,
    adapter: payload.adapter,
    vendor: payload.vendor,
    receivedAt: payload.receivedAt,
    confidence,
    records: [{ kind: 'flexibility', record }],
    warnings: record.maxExportMw <= 0 && record.maxImportMw <= 0 ? ['Flexibility envelope has no import or export range.'] : [],
  }
}

const normalizeMarket = (payload: RawAdapterPayload): AdapterNormalizationResult => {
  const price = numberField(payload, 'price')
  const confidence = numberField(payload, 'confidence', 80)
  const risk = price > 180 ? 'high' : price > 95 ? 'medium' : 'low'
  const market: MarketSignal = {
    product: marketProductField(payload, 'product'),
    region: stringField(payload, 'region', 'Unknown'),
    price,
    confidence,
    obligationMw: numberField(payload, 'obligationMw'),
    interval: stringField(payload, 'interval', 'current'),
    weatherSignal: stringField(payload, 'weatherSignal', 'Unspecified'),
    gridCondition: gridConditionField(payload, 'gridCondition'),
    risk,
  }

  return {
    payloadId: payload.id,
    adapter: payload.adapter,
    vendor: payload.vendor,
    receivedAt: payload.receivedAt,
    confidence,
    records: [{ kind: 'market', record: market }],
    warnings: market.confidence < 70 ? ['Market confidence below automatic-bid threshold.'] : [],
  }
}

const normalizeConstraint = (payload: RawAdapterPayload): AdapterNormalizationResult => {
  const severity = severityField(payload, 'severity')
  const rule: ConstraintPolicy = {
    id: stringField(payload, 'ruleId', payload.id),
    assetId: stringField(payload, 'assetId'),
    source: `${payload.vendor} ${payload.adapter}`,
    rule: stringField(payload, 'rule'),
    severity,
    operatorApprovalRequired: booleanField(payload, 'approvalRequired', severity === 'binding'),
  }

  return {
    payloadId: payload.id,
    adapter: payload.adapter,
    vendor: payload.vendor,
    receivedAt: payload.receivedAt,
    confidence: severity === 'binding' ? 92 : 78,
    records: [{ kind: 'constraint', record: rule }],
    warnings: rule.operatorApprovalRequired ? ['Operator approval required before dispatch using this resource.'] : [],
  }
}

export const normalizeAdapterPayload = (payload: RawAdapterPayload): AdapterNormalizationResult => {
  if (payload.adapter === 'ISO market' || payload.adapter === 'Weather') return normalizeMarket(payload)
  if (payload.adapter === 'Rules engine') return normalizeConstraint(payload)
  if ('maxExportMw' in payload.payload || 'maxImportMw' in payload.payload) return normalizeFlexibility(payload)
  return normalizeTelemetry(payload)
}

export const normalizeAdapterPayloads = (payloads: RawAdapterPayload[]) => payloads.map(normalizeAdapterPayload)

export const adapterCoverage = (results: AdapterNormalizationResult[]) => {
  const recordCounts = results.reduce<Record<NormalizedRecord['kind'], number>>(
    (counts, result) => {
      result.records.forEach((record) => {
        counts[record.kind] += 1
      })
      return counts
    },
    { telemetry: 0, flexibility: 0, market: 0, constraint: 0 },
  )
  const confidence = results.length
    ? Math.round(results.reduce((sum, result) => sum + result.confidence, 0) / results.length)
    : 0
  const warningCount = results.reduce((sum, result) => sum + result.warnings.length, 0)

  return {
    recordCounts,
    confidence,
    warningCount,
    adaptersOnline: results.length,
  }
}

export const rawAdapterPayloads: RawAdapterPayload[] = [
  {
    id: 'raw-bms-sutter-001',
    adapter: 'BMS',
    vendor: 'Storage controller',
    receivedAt: '2026-06-05T18:55:02Z',
    schemaVersion: 'vendor.bms.v2',
    payload: {
      assetId: 'bess-sutter',
      timestamp: '2026-06-05T18:54:58Z',
      secondsOld: 4,
      mw: 6.2,
      mvar: 1.1,
      soc: 61,
      breakerClosed: true,
    },
  },
  {
    id: 'raw-evse-bay-016',
    adapter: 'EVSE',
    vendor: 'Fleet charging network',
    receivedAt: '2026-06-05T18:55:02Z',
    schemaVersion: 'vendor.evse.sessions.v1',
    payload: {
      assetId: 'ev-bay',
      timestamp: '2026-06-05T18:49:22Z',
      secondsOld: 340,
      mw: -8.7,
      soc: 72,
      breakerClosed: true,
    },
  },
  {
    id: 'raw-bms-gateway-east-044',
    adapter: 'BMS gateway',
    vendor: 'Building controls',
    receivedAt: '2026-06-05T18:55:02Z',
    schemaVersion: 'vendor.bms.loadflex.v3',
    payload: {
      assetId: 'hvac-east',
      interval: '17:00-20:00',
      maxExportMw: 34,
      maxImportMw: 0,
      durationMinutes: 88,
      rampRateMwPerMinute: 3,
      controlLatencySeconds: 95,
      telemetryLatencySeconds: 47,
      confidence: 68,
    },
  },
  {
    id: 'raw-iso-np15-rtm-223',
    adapter: 'ISO market',
    vendor: 'CAISO feed',
    receivedAt: '2026-06-05T18:55:02Z',
    schemaVersion: 'iso.market.v1',
    payload: {
      product: 'Energy arbitrage',
      region: 'CAISO NP15',
      price: 184,
      confidence: 82,
      obligationMw: 74,
      interval: '14:00-16:00',
      weatherSignal: 'Warm evening ramp',
      gridCondition: 'scarcity',
    },
  },
  {
    id: 'raw-rules-ev-bay-002',
    adapter: 'Rules engine',
    vendor: 'Customer program CRM',
    receivedAt: '2026-06-05T18:55:02Z',
    schemaVersion: 'rules.constraints.v1',
    payload: {
      ruleId: 'ev-departure-window',
      assetId: 'ev-bay',
      rule: 'Do not compromise committed vehicle departure energy after 16:30.',
      severity: 'binding',
      approvalRequired: true,
    },
  },
]

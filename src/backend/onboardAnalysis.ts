// Deterministic VPP revenue & readiness assessment engine.
//
// Takes a parsed DER portfolio and produces a full "what could this fleet earn
// under Vela" report: a stacked revenue projection across market products, a
// status-quo comparison, readiness scoring, a 12-month enrollment ramp, risk
// flags, and prioritized recommendations.
//
// Everything here is pure and deterministic (seeded off asset ids) so the demo
// renders identical, realistic numbers every time with no backend dependency.

import type { Chemistry, DemoAssetType } from '../types/demo'

// ── Inputs ────────────────────────────────────────────────────────────────────

export type ParsedAsset = {
  asset_id: string
  asset_type: DemoAssetType
  rated_mw: number
  rated_mwh: number | null
  chemistry: Chemistry | null
  region: string
  commissioned_year: number | null
  /** 0..1 confidence the importer had in this row. */
  confidence: number
}

// ── Output shapes ───────────────────────────────────────────────────────────────

export type StreamCategory = 'capacity' | 'energy' | 'ancillary' | 'flexibility'

export type RevenueStream = {
  id: string
  product: string
  category: StreamCategory
  /** p50 annual gross revenue, USD. */
  annualUsd: number
  p10Usd: number
  p90Usd: number
  perMwYr: number
  eligibleMw: number
  basis: string
  /** Fraction (0..1) of this stream a typical operator already captures today. */
  statusQuoCapture: number
  confidence: number
}

export type AssetAssessment = {
  asset: ParsedAsset
  streams: RevenueStream[]
  annualUsd: number
  degradationUsd: number
  netAnnualUsd: number
  statusQuoUsd: number
  capacityFactor: number | null
  cyclesPerYear: number | null
  durationHours: number | null
  readiness: number
  flags: string[]
}

export type ReadinessFinding = {
  id: string
  label: string
  detail: string
  status: 'pass' | 'warn' | 'fail'
  weight: number
}

export type MarketProductSummary = {
  product: string
  category: StreamCategory
  annualUsd: number
  untappedUsd: number
  eligibleAssets: number
  eligibleMw: number
}

export type MonthlyProjection = {
  month: string
  vela: number
  statusQuo: number
  cumulativeVela: number
  cumulativeStatusQuo: number
}

export type Recommendation = {
  id: string
  title: string
  detail: string
  impactUsd: number
  priority: 'high' | 'medium' | 'low'
}

export type RiskFlag = {
  id: string
  label: string
  detail: string
  severity: 'high' | 'medium' | 'low'
}

export type PortfolioReport = {
  generatedAt: string
  assetCount: number
  totalMw: number
  totalMwh: number
  regions: string[]
  isos: string[]
  assessments: AssetAssessment[]
  productSummary: MarketProductSummary[]
  annualGrossUsd: number
  annualDegradationUsd: number
  annualNetUsd: number
  annualStatusQuoUsd: number
  upliftUsd: number
  upliftPct: number
  p10Usd: number
  p90Usd: number
  perMwYr: number
  readinessScore: number
  findings: ReadinessFinding[]
  monthly: MonthlyProjection[]
  recommendations: Recommendation[]
  riskFlags: RiskFlag[]
  enrollmentTimelineWeeks: number
  confidence: number
}

// ── Seeded helpers ─────────────────────────────────────────────────────────────

function hash(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Deterministic value in [lo, hi) seeded by `seed`. */
function jitter(seed: string, lo: number, hi: number): number {
  const r = (hash(seed) % 10000) / 10000
  return lo + r * (hi - lo)
}

const round = (n: number) => Math.round(n)

// ── Market assumptions (plausible CAISO/ERCOT/PJM-class numbers) ────────────────

/** Resource-adequacy / capacity value, $/MW-yr, by asset type. */
const RA_PER_MW_YR: Record<DemoAssetType, number> = {
  BESS: 72_000,
  Solar: 26_000, // ELCC-derated
  Wind: 19_000, // ELCC-derated
  EV_Fleet: 38_000,
  Flex_Load: 44_000,
}

/** Frequency-regulation value, $/MW-yr (fast-response assets only). */
const REG_PER_MW_YR: Record<DemoAssetType, number> = {
  BESS: 92_000,
  EV_Fleet: 41_000,
  Solar: 0,
  Wind: 0,
  Flex_Load: 0,
}

/** Spinning / non-spin reserve value, $/MW-yr. */
const RESERVE_PER_MW_YR: Record<DemoAssetType, number> = {
  BESS: 31_000,
  EV_Fleet: 17_000,
  Flex_Load: 22_000,
  Solar: 0,
  Wind: 0,
}

/** Demand-response enrollment + event value, $/MW-yr on flexible MW. */
const DR_PER_MW_YR: Record<DemoAssetType, number> = {
  Flex_Load: 58_000,
  EV_Fleet: 34_000,
  BESS: 0,
  Solar: 0,
  Wind: 0,
}

/** Annual energy capacity factor for generation assets. */
const CAPACITY_FACTOR: Record<DemoAssetType, number> = {
  Solar: 0.265,
  Wind: 0.375,
  BESS: 0,
  EV_Fleet: 0,
  Flex_Load: 0,
}

const AVG_LMP = 44 // $/MWh wholesale energy reference
const ARB_SPREAD = 42 // $/MWh peak-trough capture for storage
const ARB_CYCLES = 330 // equivalent full cycles per year
const ROUNDTRIP_EFF = 0.87
const DEGRADATION_PER_MWH = 4.6 // $/MWh throughput (battery wear)

const STORAGE_TYPES: DemoAssetType[] = ['BESS', 'EV_Fleet']

// ── Per-asset revenue stacking ──────────────────────────────────────────────────

function band(seed: string, p50: number): { p10: number; p90: number } {
  // Wider downside than upside — markets disappoint more often than they surprise.
  const down = jitter(seed + ':d', 0.18, 0.3)
  const up = jitter(seed + ':u', 0.14, 0.24)
  return { p10: round(p50 * (1 - down)), p90: round(p50 * (1 + up)) }
}

function buildStreams(asset: ParsedAsset): RevenueStream[] {
  const streams: RevenueStream[] = []
  const { asset_type: t, rated_mw: mw, rated_mwh: mwh, asset_id: id } = asset
  const durationH = mwh && mw ? mwh / mw : null

  const push = (
    product: string,
    category: StreamCategory,
    perMwYr: number,
    eligibleMw: number,
    basis: string,
    statusQuoCapture: number,
    confidence: number,
  ) => {
    if (perMwYr <= 0 || eligibleMw <= 0) return
    const noise = jitter(id + product, 0.92, 1.08)
    const annual = round(perMwYr * eligibleMw * noise)
    const { p10, p90 } = band(id + product, annual)
    streams.push({
      id: `${id}-${product}`.replace(/\s+/g, '-').toLowerCase(),
      product,
      category,
      annualUsd: annual,
      p10Usd: p10,
      p90Usd: p90,
      perMwYr: round(annual / eligibleMw),
      eligibleMw: +eligibleMw.toFixed(1),
      basis,
      statusQuoCapture,
      confidence,
    })
  }

  // Capacity / Resource Adequacy — every asset class qualifies at some accreditation.
  const elcc =
    t === 'Solar' ? 0.55 : t === 'Wind' ? 0.45 : t === 'BESS' && durationH && durationH < 4 ? 0.7 : 1
  push(
    'Resource Adequacy',
    'capacity',
    RA_PER_MW_YR[t],
    +(mw * elcc).toFixed(1),
    t === 'Solar' || t === 'Wind'
      ? `${Math.round(elcc * 100)}% ELCC accreditation on ${mw} MW nameplate`
      : durationH && durationH < 4
        ? `${Math.round(elcc * 100)}% accreditation — ${durationH.toFixed(1)}h duration below 4h RA threshold`
        : `Full ${mw} MW capacity offer`,
    0.5,
    asset.confidence,
  )

  // Frequency regulation — fast, symmetric assets.
  if (REG_PER_MW_YR[t] > 0) {
    const regMw = t === 'EV_Fleet' ? mw * 0.6 : mw
    push(
      'Frequency Regulation',
      'ancillary',
      REG_PER_MW_YR[t],
      +regMw.toFixed(1),
      `Sub-4s response on ${regMw.toFixed(0)} MW — highest $/MW ancillary product`,
      0.0,
      asset.confidence * 0.96,
    )
  }

  // Spinning / non-spin reserve.
  if (RESERVE_PER_MW_YR[t] > 0) {
    push(
      'Spinning Reserve',
      'ancillary',
      RESERVE_PER_MW_YR[t],
      +(mw * 0.8).toFixed(1),
      `${(mw * 0.8).toFixed(0)} MW held as 10-minute contingency reserve`,
      0.1,
      asset.confidence * 0.94,
    )
  }

  // Energy arbitrage — storage only, sized on energy not power.
  if (STORAGE_TYPES.includes(t) && mwh) {
    const cycles = t === 'EV_Fleet' ? ARB_CYCLES * 0.45 : ARB_CYCLES
    const annual = round(ARB_SPREAD * cycles * mwh * ROUNDTRIP_EFF)
    const { p10, p90 } = band(id + 'arb', annual)
    streams.push({
      id: `${id}-arb`.replace(/\s+/g, '-').toLowerCase(),
      product: 'Energy Arbitrage',
      category: 'energy',
      annualUsd: annual,
      p10Usd: p10,
      p90Usd: p90,
      perMwYr: round(annual / mw),
      eligibleMw: mw,
      basis: `~$${ARB_SPREAD}/MWh spread × ${Math.round(cycles)} cycles × ${mwh} MWh @ ${Math.round(
        ROUNDTRIP_EFF * 100,
      )}% RTE`,
      statusQuoCapture: 0.25,
      confidence: asset.confidence,
    })
  }

  // Wholesale energy / PPA shaping — generation assets.
  if (CAPACITY_FACTOR[t] > 0) {
    const cf = CAPACITY_FACTOR[t] * jitter(id + 'cf', 0.92, 1.08)
    const mwhYr = cf * mw * 8760
    const annual = round(mwhYr * AVG_LMP)
    const { p10, p90 } = band(id + 'eng', annual)
    streams.push({
      id: `${id}-energy`.replace(/\s+/g, '-').toLowerCase(),
      product: 'Energy / PPA Shaping',
      category: 'energy',
      annualUsd: annual,
      p10Usd: p10,
      p90Usd: p90,
      perMwYr: round(annual / mw),
      eligibleMw: mw,
      basis: `${Math.round(cf * 100)}% CF × ${mw} MW × 8760h @ $${AVG_LMP}/MWh — Vela shapes & avoids curtailment`,
      statusQuoCapture: 0.9, // they already sell the energy; Vela adds shaping uplift
      confidence: asset.confidence,
    })
  }

  // Demand response — flexible load.
  if (DR_PER_MW_YR[t] > 0) {
    const flexMw = t === 'EV_Fleet' ? mw * 0.7 : mw
    push(
      'Demand Response',
      'flexibility',
      DR_PER_MW_YR[t],
      +flexMw.toFixed(1),
      `${flexMw.toFixed(0)} MW curtailable across capacity & emergency DR programs`,
      0.3,
      asset.confidence * 0.95,
    )
  }

  return streams.sort((a, b) => b.annualUsd - a.annualUsd)
}

function degradationCost(asset: ParsedAsset): number {
  if (!STORAGE_TYPES.includes(asset.asset_type) || !asset.rated_mwh) return 0
  const cycles = asset.asset_type === 'EV_Fleet' ? ARB_CYCLES * 0.45 : ARB_CYCLES
  const throughput = cycles * asset.rated_mwh
  const chemMult = asset.chemistry === 'LFP' ? 0.8 : asset.chemistry === 'NCA' ? 1.15 : 1
  return round(throughput * DEGRADATION_PER_MWH * chemMult)
}

function assessAsset(asset: ParsedAsset): AssetAssessment {
  const streams = buildStreams(asset)
  const annualUsd = streams.reduce((s, x) => s + x.annualUsd, 0)
  const statusQuoUsd = round(streams.reduce((s, x) => s + x.annualUsd * x.statusQuoCapture, 0))
  const degradationUsd = degradationCost(asset)
  const durationHours = asset.rated_mwh && asset.rated_mw ? asset.rated_mwh / asset.rated_mw : null

  const flags: string[] = []
  if (STORAGE_TYPES.includes(asset.asset_type) && !asset.rated_mwh)
    flags.push('Missing energy rating (MWh) — arbitrage estimate suppressed')
  if (durationHours && durationHours < 2) flags.push('Short duration limits capacity accreditation')
  if (asset.confidence < 0.75) flags.push('Low import confidence — verify nameplate before enrollment')
  if (asset.commissioned_year && asset.commissioned_year < 2016)
    flags.push('Older vintage — confirm telemetry & inverter capability')

  // Readiness blends parse confidence, metadata completeness, and asset class.
  let readiness = 60 + asset.confidence * 30
  if (asset.rated_mwh || CAPACITY_FACTOR[asset.asset_type] > 0) readiness += 4
  if (asset.chemistry || asset.asset_type !== 'BESS') readiness += 3
  if (asset.commissioned_year) readiness += 3
  readiness -= flags.length * 4
  readiness = Math.max(35, Math.min(98, round(readiness)))

  return {
    asset,
    streams,
    annualUsd,
    degradationUsd,
    netAnnualUsd: annualUsd - degradationUsd,
    statusQuoUsd,
    capacityFactor: CAPACITY_FACTOR[asset.asset_type] || null,
    cyclesPerYear: STORAGE_TYPES.includes(asset.asset_type) && asset.rated_mwh ? ARB_CYCLES : null,
    durationHours,
    readiness,
    flags,
  }
}

// ── Portfolio-level rollups ─────────────────────────────────────────────────────

function isoOf(region: string): string {
  const r = region.toUpperCase()
  if (r.includes('CAISO') || r.includes('SP15') || r.includes('NP15')) return 'CAISO'
  if (r.includes('ERCOT')) return 'ERCOT'
  if (r.includes('PJM')) return 'PJM'
  if (r.includes('MISO')) return 'MISO'
  if (r.includes('ISO-NE') || r.includes('ISONE')) return 'ISO-NE'
  if (r.includes('NYISO')) return 'NYISO'
  return 'Other'
}

function buildFindings(
  assessments: AssetAssessment[],
  avgConfidence: number,
): ReadinessFinding[] {
  const types = new Set(assessments.map((a) => a.asset.asset_type))
  const hasStorage = assessments.some((a) => STORAGE_TYPES.includes(a.asset.asset_type))
  const hasGen = assessments.some((a) => CAPACITY_FACTOR[a.asset.asset_type] > 0)
  const isoCount = new Set(assessments.map((a) => isoOf(a.asset.region))).size
  const meteredFraction = assessments.filter((a) => a.readiness >= 80).length / Math.max(1, assessments.length)

  const findings: ReadinessFinding[] = [
    {
      id: 'metering',
      label: 'Revenue-grade telemetry',
      detail: hasStorage
        ? '4-second SCADA telemetry available on storage — meets ancillary-services certification.'
        : 'Generation assets reporting on 1-minute cadence — sufficient for energy & capacity.',
      status: hasStorage ? 'pass' : 'warn',
      weight: 20,
    },
    {
      id: 'interconnection',
      label: 'Interconnection agreements',
      detail:
        avgConfidence > 0.82
          ? 'Nameplate and POI data parsed cleanly across the portfolio.'
          : 'Some interconnection figures were inferred — confirm POI limits before bidding.',
      status: avgConfidence > 0.82 ? 'pass' : 'warn',
      weight: 18,
    },
    {
      id: 'accreditation',
      label: 'Capacity accreditation (ELCC)',
      detail: hasGen
        ? 'Solar/wind derated to ELCC — capacity offers reflect effective accredited MW.'
        : 'Storage-heavy portfolio accredits near nameplate at current durations.',
      status: hasGen ? 'warn' : 'pass',
      weight: 16,
    },
    {
      id: 'registration',
      label: 'Market registration / QSE',
      detail:
        isoCount <= 1
          ? 'Single-ISO portfolio — one scheduling-entity registration covers the fleet.'
          : `${isoCount} ISOs detected — requires a registered entity per market.`,
      status: isoCount <= 1 ? 'pass' : 'warn',
      weight: 14,
    },
    {
      id: 'aggregation',
      label: 'Aggregation eligibility (Order 2222)',
      detail:
        assessments.length >= 2
          ? 'Multiple resources can be aggregated to clear minimum offer sizes.'
          : 'Single resource — confirm it meets the market minimum offer (typically ≥0.1 MW).',
      status: assessments.length >= 2 ? 'pass' : 'warn',
      weight: 12,
    },
    {
      id: 'dataquality',
      label: 'Portfolio data completeness',
      detail: `${Math.round(meteredFraction * 100)}% of assets passed completeness checks at import.`,
      status: meteredFraction >= 0.8 ? 'pass' : meteredFraction >= 0.5 ? 'warn' : 'fail',
      weight: 10,
    },
    {
      id: 'diversity',
      label: 'Resource diversity',
      detail:
        types.size >= 3
          ? `${types.size} asset classes — strong revenue-stacking and correlation hedging.`
          : 'Concentrated asset mix — revenue is correlated across the fleet.',
      status: types.size >= 3 ? 'pass' : 'warn',
      weight: 10,
    },
  ]
  return findings
}

function readinessFromFindings(findings: ReadinessFinding[], assessments: AssetAssessment[]): number {
  const totalW = findings.reduce((s, f) => s + f.weight, 0)
  const got = findings.reduce(
    (s, f) => s + f.weight * (f.status === 'pass' ? 1 : f.status === 'warn' ? 0.6 : 0.2),
    0,
  )
  const assetAvg =
    assessments.reduce((s, a) => s + a.readiness, 0) / Math.max(1, assessments.length) / 100
  return round(((got / totalW) * 0.65 + assetAvg * 0.35) * 100)
}

function buildMonthly(annualNet: number, annualStatusQuo: number): MonthlyProjection[] {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  // Enrollment ramp: start near status-quo capture, reach full stack by ~month 6.
  const ramp = (m: number) => Math.min(1, 0.42 + 0.58 * (1 - Math.exp(-m / 2.4)))
  const seasonal = (m: number) => 1 + 0.12 * Math.sin((2 * Math.PI * (m - 5)) / 12) // summer-peaked
  let cumV = 0
  let cumS = 0
  return months.map((label, i) => {
    const s = seasonal(i)
    const velaMonthly = round((annualNet / 12) * ramp(i) * s)
    const sqMonthly = round((annualStatusQuo / 12) * s)
    cumV += velaMonthly
    cumS += sqMonthly
    return {
      month: label,
      vela: velaMonthly,
      statusQuo: sqMonthly,
      cumulativeVela: cumV,
      cumulativeStatusQuo: cumS,
    }
  })
}

function buildRecommendations(
  productSummary: MarketProductSummary[],
  assessments: AssetAssessment[],
  readinessScore: number,
): Recommendation[] {
  const recs: Recommendation[] = []

  const topUntapped = [...productSummary].sort((a, b) => b.untappedUsd - a.untappedUsd)
  for (const p of topUntapped.slice(0, 2)) {
    if (p.untappedUsd < 1000) continue
    recs.push({
      id: `enroll-${p.product}`.toLowerCase().replace(/\s+/g, '-'),
      title: `Enroll ${p.eligibleMw.toFixed(0)} MW in ${p.product}`,
      detail: `${p.eligibleAssets} asset${p.eligibleAssets === 1 ? '' : 's'} qualify but are under-monetized today. Stacking ${p.product} on top of existing commitments is the single largest uplift available.`,
      impactUsd: p.untappedUsd,
      priority: 'high',
    })
  }

  const missingMwh = assessments.filter(
    (a) => STORAGE_TYPES.includes(a.asset.asset_type) && !a.asset.rated_mwh,
  )
  if (missingMwh.length) {
    recs.push({
      id: 'capture-mwh',
      title: 'Supply energy ratings for storage assets',
      detail: `${missingMwh.length} storage asset${missingMwh.length === 1 ? '' : 's'} are missing MWh ratings, suppressing the arbitrage estimate. Adding duration unlocks the energy-shifting stream.`,
      impactUsd: round(missingMwh.reduce((s, a) => s + a.asset.rated_mw * 4 * ARB_SPREAD * ARB_CYCLES, 0)),
      priority: 'medium',
    })
  }

  if (readinessScore < 80) {
    recs.push({
      id: 'telemetry',
      title: 'Close telemetry & accreditation gaps',
      detail:
        'Bringing every asset to revenue-grade 4s telemetry and confirming ELCC accreditation raises the readiness score and unlocks the highest-value ancillary products.',
      impactUsd: 0,
      priority: 'medium',
    })
  }

  const single = new Set(assessments.map((a) => isoOf(a.asset.region))).size === 1
  if (single && assessments.length >= 3) {
    recs.push({
      id: 'hedge',
      title: 'Consider cross-ISO expansion',
      detail:
        'The fleet sits in a single ISO, so revenue is correlated with one price surface. A second market would diversify settlement risk.',
      impactUsd: 0,
      priority: 'low',
    })
  }

  return recs
}

function buildRiskFlags(assessments: AssetAssessment[], avgConfidence: number): RiskFlag[] {
  const flags: RiskFlag[] = []
  const lowConf = assessments.filter((a) => a.asset.confidence < 0.75)
  if (lowConf.length) {
    flags.push({
      id: 'parse-confidence',
      label: `${lowConf.length} asset${lowConf.length === 1 ? '' : 's'} imported at low confidence`,
      detail: `Verify nameplate, duration, and node for: ${lowConf.map((a) => a.asset.asset_id).slice(0, 4).join(', ')}${lowConf.length > 4 ? '…' : ''}.`,
      severity: avgConfidence < 0.7 ? 'high' : 'medium',
    })
  }
  const isoCount = new Set(assessments.map((a) => isoOf(a.asset.region))).size
  if (isoCount === 1 && assessments.length >= 3) {
    flags.push({
      id: 'concentration',
      label: 'Single-market concentration',
      detail: 'All revenue settles against one ISO price surface — a market disruption hits the whole fleet at once.',
      severity: 'medium',
    })
  }
  const heavyCycling = assessments.filter(
    (a) => STORAGE_TYPES.includes(a.asset.asset_type) && a.degradationUsd > a.annualUsd * 0.12,
  )
  if (heavyCycling.length) {
    flags.push({
      id: 'degradation',
      label: 'Degradation pressure on storage',
      detail: `Aggressive cycling on ${heavyCycling.length} asset${heavyCycling.length === 1 ? '' : 's'} pushes wear above 12% of gross revenue — Vela caps cycles against warranty limits.`,
      severity: 'low',
    })
  }
  const missingMwh = assessments.filter(
    (a) => STORAGE_TYPES.includes(a.asset.asset_type) && !a.asset.rated_mwh,
  )
  if (missingMwh.length) {
    flags.push({
      id: 'missing-duration',
      label: 'Incomplete duration data',
      detail: 'Storage without an MWh rating cannot be bid into energy markets until duration is confirmed.',
      severity: 'medium',
    })
  }
  return flags
}

// ── Public entry point ──────────────────────────────────────────────────────────

export function analyzePortfolio(assets: ParsedAsset[]): PortfolioReport {
  const assessments = assets.map(assessAsset)

  const totalMw = +assets.reduce((s, a) => s + a.rated_mw, 0).toFixed(1)
  const totalMwh = +assets.reduce((s, a) => s + (a.rated_mwh ?? 0), 0).toFixed(1)
  const regions = [...new Set(assets.map((a) => a.region))]
  const isos = [...new Set(assets.map((a) => isoOf(a.region)))]
  const avgConfidence = assets.reduce((s, a) => s + a.confidence, 0) / Math.max(1, assets.length)

  // Aggregate every stream across the fleet into a per-product summary.
  const byProduct = new Map<string, MarketProductSummary>()
  for (const ass of assessments) {
    for (const st of ass.streams) {
      const cur =
        byProduct.get(st.product) ??
        ({
          product: st.product,
          category: st.category,
          annualUsd: 0,
          untappedUsd: 0,
          eligibleAssets: 0,
          eligibleMw: 0,
        } satisfies MarketProductSummary)
      cur.annualUsd += st.annualUsd
      cur.untappedUsd += round(st.annualUsd * (1 - st.statusQuoCapture))
      cur.eligibleAssets += 1
      cur.eligibleMw = +(cur.eligibleMw + st.eligibleMw).toFixed(1)
      byProduct.set(st.product, cur)
    }
  }
  const productSummary = [...byProduct.values()].sort((a, b) => b.annualUsd - a.annualUsd)

  const annualGrossUsd = round(assessments.reduce((s, a) => s + a.annualUsd, 0))
  const annualDegradationUsd = round(assessments.reduce((s, a) => s + a.degradationUsd, 0))
  const annualNetUsd = annualGrossUsd - annualDegradationUsd
  const annualStatusQuoUsd = round(assessments.reduce((s, a) => s + a.statusQuoUsd, 0))
  const upliftUsd = annualNetUsd - annualStatusQuoUsd
  const upliftPct = annualStatusQuoUsd > 0 ? round((upliftUsd / annualStatusQuoUsd) * 100) : 0

  const p10Usd = round(assessments.reduce((s, a) => s + a.streams.reduce((q, x) => q + x.p10Usd, 0), 0) - annualDegradationUsd)
  const p90Usd = round(assessments.reduce((s, a) => s + a.streams.reduce((q, x) => q + x.p90Usd, 0), 0) - annualDegradationUsd)

  const findings = buildFindings(assessments, avgConfidence)
  const readinessScore = readinessFromFindings(findings, assessments)
  const monthly = buildMonthly(annualNetUsd, annualStatusQuoUsd)
  const recommendations = buildRecommendations(productSummary, assessments, readinessScore)
  const riskFlags = buildRiskFlags(assessments, avgConfidence)

  // Registration timeline scales with ISO count + readiness gaps.
  const enrollmentTimelineWeeks = round(4 + isos.length * 2 + (100 - readinessScore) / 12)

  return {
    generatedAt: new Date().toISOString(),
    assetCount: assets.length,
    totalMw,
    totalMwh,
    regions,
    isos,
    assessments,
    productSummary,
    annualGrossUsd,
    annualDegradationUsd,
    annualNetUsd,
    annualStatusQuoUsd,
    upliftUsd,
    upliftPct,
    p10Usd,
    p90Usd,
    perMwYr: totalMw > 0 ? round(annualNetUsd / totalMw) : 0,
    readinessScore,
    findings,
    monthly,
    recommendations,
    riskFlags,
    enrollmentTimelineWeeks,
    confidence: avgConfidence,
  }
}

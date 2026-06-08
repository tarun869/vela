import { useMemo, useState, useRef, useEffect } from 'react'
import {
  AlertTriangle,
  BarChart2,
  BatteryCharging,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  ClipboardCheck,
  CloudSun,
  DatabaseZap,
  Download,
  FileText,
  Gauge,
  LayoutGrid,
  LineChart,
  List,
  Network,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  SunMedium,
  X,
  Zap,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { generateDispatchSeries, generatePriceFan } from './backend/chartData'
import type { DispatchPoint, PriceFanPoint } from './backend/chartData'
import './App.css'
import { adapterCoverage, normalizeAdapterPayloads, rawAdapterPayloads } from './backend/adapters'
import { buildCoordinationReadiness } from './backend/coordination'
import { buildControlLoopChecks } from './backend/controlLoop'
import {
  assets,
  coordinationCheckpoints,
  constraintPolicies,
  dataQualitySignals,
  flexibilityEnvelopes,
  integrationStandards,
  integrationSources,
  marketEnrollments,
  marketSignals,
  objectiveWeights,
  telemetrySamples,
  vppConnectors,
} from './backend/mockData'
import { buildDecisionCandidates, portfolioStats } from './backend/decisionModel'
import { buildDispatchPlan } from './backend/dispatchPlan'
import { buildModelRunSnapshot } from './backend/modelRun'
import { buildOverrideImpacts, operatorOverrides } from './backend/overrides'
import { buildReplayManifest } from './backend/replay'
import { buildSensitivityCases } from './backend/sensitivity'
import { buildSettlementProjection } from './backend/settlement'
import { buildReadinessFindings, readinessScore } from './backend/validation'
import type { ActionType, Asset, AssetType, DecisionCandidate } from './backend/types'

type PageId = 'command' | 'portfolio' | 'markets' | 'coordination' | 'model' | 'integrations' | 'runlog'

const primaryItems: Array<{ id: PageId; label: string; icon: typeof Network }> = [
  { id: 'command', label: 'Command', icon: Network },
  { id: 'integrations', label: 'Integrations', icon: ShieldCheck },
  { id: 'portfolio', label: 'Portfolio', icon: DatabaseZap },
  { id: 'markets', label: 'Markets', icon: LineChart },
]

const secondaryItems: Array<{ id: PageId; label: string; icon: typeof Network }> = [
  { id: 'coordination', label: 'Coordination', icon: ClipboardCheck },
  { id: 'model', label: 'Model', icon: SlidersHorizontal },
  { id: 'runlog', label: 'Run log', icon: FileText },
]

const pageItems = [...primaryItems, ...secondaryItems]

const assetIcons: Record<AssetType, typeof BatteryCharging> = {
  Battery: BatteryCharging,
  'EV charger': Zap,
  Solar: SunMedium,
  'Building load': Building2,
  Generator: Gauge,
}

const actionLabels: Record<ActionType, string> = {
  sell: 'Sell',
  store: 'Store',
  shift: 'Shift',
  reserve: 'Reserve',
  curtail: 'Curtail',
}

const adapterResults = normalizeAdapterPayloads(rawAdapterPayloads)
const coverage = adapterCoverage(adapterResults)
const readinessFindings = buildReadinessFindings({
  assets,
  telemetry: telemetrySamples,
  envelopes: flexibilityEnvelopes,
  signals: marketSignals,
  policies: constraintPolicies,
  enrollments: marketEnrollments,
  adapterResults,
})
const integrationReadiness = readinessScore(readinessFindings)
const stats = portfolioStats(assets)
const decisionCandidates = buildDecisionCandidates(
  assets,
  marketSignals,
  objectiveWeights,
  flexibilityEnvelopes,
  constraintPolicies,
  marketEnrollments,
)
const topDecision = decisionCandidates[0]
const dispatchPlan = buildDispatchPlan(topDecision, flexibilityEnvelopes, constraintPolicies)
const overrideImpacts = buildOverrideImpacts(topDecision, dispatchPlan, operatorOverrides)
const sensitivityCases = buildSensitivityCases(topDecision, objectiveWeights, flexibilityEnvelopes, constraintPolicies)
const settlementProjection = buildSettlementProjection(topDecision, dispatchPlan)
const coordinationReadiness = buildCoordinationReadiness(coordinationCheckpoints)
const controlLoopChecks = buildControlLoopChecks({
  enrollments: marketEnrollments,
  envelopes: flexibilityEnvelopes,
  telemetry: telemetrySamples,
  policies: constraintPolicies,
})
const modelRunSnapshot = buildModelRunSnapshot({
  candidates: decisionCandidates,
  adapterResults,
  findings: readinessFindings,
  dispatchPlan,
  overrideImpacts,
  settlementProjection,
  coordinationReadiness,
  readinessScore: integrationReadiness,
})
const replayManifest = buildReplayManifest(modelRunSnapshot)
const forecastRevenue = Math.round(topDecision.targetMw * topDecision.market.price * 1.7)
const dispatchSeries: DispatchPoint[] = generateDispatchSeries()
const priceFanSeries: PriceFanPoint[] = generatePriceFan()

// ---- Chart data (deterministic, derived from mock signals) ----

const _baseLmp = marketSignals[0]?.price ?? 48
const lmpSeries = Array.from({ length: 24 }, (_, h) => {
  // CAISO duck-curve shape: solar noon dip + evening ramp
  const ev = Math.max(0, Math.sin(Math.PI * (h - 15) / 8))
  const solar = Math.max(0, Math.sin(Math.PI * (h - 6) / 10))
  const profile = 0.70 + 0.60 * ev - 0.22 * solar * (1 - ev * 1.4)
  const da = Math.round(_baseLmp * Math.max(0.38, profile))
  const rt = Math.round(da + (h % 2 === 0 ? 6 : -4) + Math.sin(h * 1.8) * 5)
  return { hour: `${String(h).padStart(2, '0')}:00`, da, rt }
})

const capacityBarData = assets.map((a) => ({
  name: a.name.split(' ').slice(0, 2).join(' '),
  available: a.availableMw,
  constrained: +(a.capacityMw - a.availableMw).toFixed(1),
}))

const tornadoSeries = [...sensitivityCases]
  .sort((a, b) => Math.abs(b.scoreDelta) - Math.abs(a.scoreDelta))
  .slice(0, 6)
  .map((s) => ({ label: s.label.slice(0, 22), delta: s.scoreDelta }))

const candidateScoreSeries = decisionCandidates.map((d) => ({
  name: `${actionLabels[d.action]} ${d.targetMw}MW`,
  score: d.score,
}))

const assetById = assets.reduce<Record<string, Asset>>((index, asset) => {
  index[asset.id] = asset
  return index
}, {})

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

const formatUsd = (value: number) =>
  new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 0,
    style: 'currency',
    currency: 'USD',
  }).format(value)

const formatSignedUsd = (value: number) => `${value < 0 ? '-' : ''}${formatUsd(Math.abs(value))}`

// ---- Metric registry for swappable KPI cards ----
type MetricId = 'capacity' | 'available' | 'forecast' | 'readiness' | 'utilization' | 'constrained' | 'adapters' | 'candidates'
const metricRegistry: Record<MetricId, { label: string; value: string; detail: string; icon: typeof Network }> = {
  capacity:    { label: 'Portfolio MW',    value: `${stats.capacity} MW`,        detail: 'Registered capacity across five resource classes',               icon: Network },
  available:   { label: 'Available',       value: `${stats.available} MW`,       detail: `${stats.utilization}% dispatchable this interval`,               icon: Gauge },
  forecast:    { label: 'Forecast net',    value: formatUsd(forecastRevenue),    detail: 'Current recommended dispatch window',                            icon: CircleDollarSign },
  readiness:   { label: 'Readiness',       value: `${integrationReadiness}%`,    detail: `${coverage.adaptersOnline} adapters online, ${coverage.warningCount} warnings`, icon: AlertTriangle },
  utilization: { label: 'Utilization',     value: `${stats.utilization}%`,       detail: `${stats.available} of ${stats.capacity} MW online`,              icon: Gauge },
  constrained: { label: 'Constrained',     value: `${stats.constrained}`,        detail: 'Sources with active constraint policies',                        icon: AlertTriangle },
  adapters:    { label: 'Adapters online', value: `${coverage.adaptersOnline}`,  detail: `${coverage.confidence}% data confidence`,                        icon: DatabaseZap },
  candidates:  { label: 'Candidates',      value: `${decisionCandidates.length}`,detail: `Top score: ${topDecision.score} · ${topDecision.market.product}`, icon: CircleDollarSign },
}
const allMetricIds = Object.keys(metricRegistry) as MetricId[]

// ---- Chart style constants ----
const AX = { fontSize: 10, fill: '#68736f' } as const
const GRID = { stroke: '#dbe2de' }
const TIP_STYLE = { fontSize: 12, borderRadius: 6, border: '1px solid #dbe2de', background: '#fff' }

function FleetDispatchChart() {
  const [on, setOn] = useState({ bess: true, solar: true, ev: true, hvac: true, lmp: true })
  const [collapsed, setCollapsed] = useState(false)
  const toggle = (k: keyof typeof on) => setOn(s => ({ ...s, [k]: !s[k] }))

  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <div>
          <p className="label">Fleet dispatch timeline</p>
          <h2>24-hour asset schedule · LMP overlay</h2>
        </div>
        <div className="panel-actions">
          <span className="live-indicator">96 intervals</span>
          <button className="icon-btn" title={collapsed ? 'Expand' : 'Collapse'} onClick={() => setCollapsed(c => !c)}>
            <ChevronDown size={13} style={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform .2s' }} />
          </button>
        </div>
      </div>
      {!collapsed && (
        <>
          <div className="opt-bar">
            <span className="opt-label">Toggle series</span>
            {(['bess','solar','ev','hvac','lmp'] as const).map(k => (
              <button key={k} className={`opt-pill${on[k] ? ' active' : ' off'}`} onClick={() => toggle(k)}>
                {{ bess:'BESS', solar:'Solar', ev:'EV', hvac:'HVAC', lmp:'LMP' }[k]}
              </button>
            ))}
          </div>
          <div className="chart-area">
            <div className="chart-legend">
              {on.bess  && <span className={`legend-item legend-bess${on.bess?'':' off'}`}   onClick={() => toggle('bess')}>BESS fleet</span>}
              {on.solar && <span className={`legend-item legend-solar${on.solar?'':' off'}`}  onClick={() => toggle('solar')}>Solar</span>}
              {on.ev    && <span className={`legend-item legend-ev${on.ev?'':' off'}`}        onClick={() => toggle('ev')}>EV load</span>}
              {on.hvac  && <span className={`legend-item legend-hvac${on.hvac?'':' off'}`}   onClick={() => toggle('hvac')}>HVAC flex</span>}
              {on.lmp   && <span className={`legend-item legend-lmp${on.lmp?'':' off'}`}     onClick={() => toggle('lmp')}>LMP $/MWh</span>}
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={dispatchSeries} margin={{ top: 4, right: 52, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="gBess" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#1A74D8" stopOpacity={0.7} />
                    <stop offset="95%" stopColor="#1A74D8" stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="gSolar" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#d97706" stopOpacity={0.65} />
                    <stop offset="95%" stopColor="#d97706" stopOpacity={0.04} />
                  </linearGradient>
                  <linearGradient id="gEv" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#a23b35" stopOpacity={0.5} />
                    <stop offset="95%" stopColor="#a23b35" stopOpacity={0.04} />
                  </linearGradient>
                  <linearGradient id="gHvac" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#235a91" stopOpacity={0.55} />
                    <stop offset="95%" stopColor="#235a91" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
                <XAxis dataKey="time" tick={AX} tickLine={false} axisLine={false} interval={7} />
                <YAxis yAxisId="kw" tick={AX} tickLine={false} axisLine={false} tickFormatter={v => `${((v as number) / 1000).toFixed(0)}MW`} domain={[-18000, 20000]} width={42} />
                <YAxis yAxisId="lmp" orientation="right" tick={AX} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} domain={[0, 140]} width={42} />
                <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown, name?: string | number) => {
                  if (name === 'lmp') return [`$${v as number}/MWh`, 'LMP'] as [string, string]
                  const labels: Record<string, string> = { bess: 'BESS Fleet', solar: 'Solar', ev: 'EV Load', hvac: 'HVAC Flex' }
                  return [`${((v as number) / 1000).toFixed(2)} MW`, labels[name as string] ?? String(name)] as [string, string]
                }} />
                <ReferenceLine yAxisId="kw" y={0} stroke="#c5d0cb" strokeWidth={1.5} />
                {on.bess  && <Area yAxisId="kw" type="monotone" dataKey="bess"  fill="url(#gBess)"  stroke="#1A74D8" strokeWidth={1.5} />}
                {on.solar && <Area yAxisId="kw" type="monotone" dataKey="solar" fill="url(#gSolar)" stroke="#d97706" strokeWidth={1.5} />}
                {on.hvac  && <Area yAxisId="kw" type="monotone" dataKey="hvac"  fill="url(#gHvac)"  stroke="#235a91" strokeWidth={1.5} />}
                {on.ev    && <Area yAxisId="kw" type="monotone" dataKey="ev"    fill="url(#gEv)"    stroke="#a23b35" strokeWidth={1.5} />}
                {on.lmp   && <Line yAxisId="lmp" type="monotone" dataKey="lmp" stroke="#333d38" strokeWidth={1.8} dot={false} strokeDasharray="5 3" />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </section>
  )
}

function PriceFanChart() {
  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <div>
          <p className="label">Price forecast</p>
          <h2>LMP quantile fan — CAISO SP15</h2>
        </div>
        <span className="live-indicator">p10 · p50 · p90</span>
      </div>
      <div className="chart-area">
        <div className="chart-legend">
          <span className="legend-item legend-band">p10–p90 band</span>
          <span className="legend-item legend-median">p50 median</span>
          <span className="legend-item legend-actual">Actual (ex-post)</span>
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={priceFanSeries} margin={{ top: 4, right: 16, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="gBand" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#235a91" stopOpacity={0.22} />
                <stop offset="95%" stopColor="#235a91" stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
            <XAxis dataKey="time" tick={AX} tickLine={false} axisLine={false} interval={7} />
            <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} width={38} />
            <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown, name?: string | number) => {
              const labels: Record<string, string> = { p10: 'p10', p25: 'p25', p50: 'Median', p75: 'p75', p90: 'p90', actual: 'Actual' }
              return [`$${(v as number).toFixed(1)}/MWh`, labels[name as string] ?? String(name)] as [string, string]
            }} />
            <Area type="monotone" dataKey="p90"    fill="url(#gBand)" stroke="#b0c4bc" strokeWidth={1} />
            <Area type="monotone" dataKey="p50"    fill="none"         stroke="#235a91" strokeWidth={2} />
            <Area type="monotone" dataKey="p10"    fill="white"        stroke="#b0c4bc" strokeWidth={1} />
            <Area type="monotone" dataKey="actual" fill="none"         stroke="#333d38" strokeWidth={1.5} strokeDasharray="4 2" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function LmpChartPanel() {
  const [chartType, setChartType] = useState<'area' | 'line'>('area')
  const [on, setOn] = useState({ da: true, rt: true })
  const [collapsed, setCollapsed] = useState(false)
  const toggle = (k: 'da' | 'rt') => setOn(s => ({ ...s, [k]: !s[k] }))

  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <div>
          <p className="label">LMP price curve</p>
          <h2>Day-ahead vs real-time — 24-hour window</h2>
        </div>
        <div className="panel-actions">
          <span className="live-indicator">${_baseLmp}/MWh base</span>
          <button className="icon-btn" title={collapsed ? 'Expand' : 'Collapse'} onClick={() => setCollapsed(c => !c)}>
            <ChevronDown size={13} style={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform .2s' }} />
          </button>
        </div>
      </div>
      {!collapsed && (
        <>
          <div className="opt-bar">
            <span className="opt-label">Chart</span>
            <button className={`opt-pill${chartType === 'area' ? ' active' : ''}`} onClick={() => setChartType('area')}><BarChart2 size={11} />Area</button>
            <button className={`opt-pill${chartType === 'line' ? ' active' : ''}`} onClick={() => setChartType('line')}><LineChart size={11} />Line</button>
            <div className="opt-sep" />
            <span className="opt-label">Series</span>
            <button className={`opt-pill${on.da ? ' active' : ' off'}`} onClick={() => toggle('da')}>Day-ahead</button>
            <button className={`opt-pill${on.rt ? ' active' : ' off'}`} onClick={() => toggle('rt')}>Real-time</button>
          </div>
          <div className="chart-area">
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={lmpSeries} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="daGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#235a91" stopOpacity={chartType === 'area' ? 0.13 : 0} />
                    <stop offset="95%" stopColor="#235a91" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
                <XAxis dataKey="hour" tick={AX} tickLine={false} axisLine={GRID} interval={3} />
                <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} width={38} />
                <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown, n?: string | number) => [`$${v as number}/MWh`, n === 'da' ? 'DA price' : 'RT price'] as [string, string]} />
                {on.da && <Area type="monotone" dataKey="da" stroke="#235a91" strokeWidth={2} fill={chartType === 'area' ? 'url(#daGrad)' : 'none'} name="da" />}
                {on.rt && <Area type="monotone" dataKey="rt" stroke="#9b6515" strokeWidth={1.5} strokeDasharray="5 3" fill="none" name="rt" />}
              </AreaChart>
            </ResponsiveContainer>
            <div className="chart-legend">
              <span className={`legend-item legend-da${on.da ? '' : ' off'}`} onClick={() => toggle('da')}>Day-ahead</span>
              <span className={`legend-item legend-rt${on.rt ? '' : ' off'}`} onClick={() => toggle('rt')}>Real-time</span>
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function CapacityChartPanel() {
  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <div>
          <p className="label">Fleet capacity</p>
          <h2>Available vs constrained MW per asset</h2>
        </div>
      </div>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height={170}>
          <BarChart data={capacityBarData} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" {...GRID} horizontal={false} />
            <XAxis type="number" tick={AX} tickLine={false} axisLine={GRID} tickFormatter={(v) => `${v}MW`} />
            <YAxis type="category" dataKey="name" tick={AX} tickLine={false} axisLine={false} width={74} />
            <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown, name?: string | number) => [`${v as number} MW`, name === 'available' ? 'Available' : 'Constrained'] as [string, string]} />
            <Bar dataKey="available" stackId="cap" fill="#1A74D8" name="available" />
            <Bar dataKey="constrained" stackId="cap" fill="#dbe2de" name="constrained" radius={[0, 3, 3, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function WaterfallChartPanel({ lines, netMargin }: { lines: Array<{ label: string; amount: number }>; netMargin: number }) {
  const data = lines.map((l) => ({
    name: l.label.replace('Day-ahead ', 'DA ').replace('Real-time ', 'RT ').replace(' Reserve', ' Rsv').replace('Ancillary ', ''),
    amount: l.amount,
  }))
  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <div>
          <p className="label">Settlement waterfall</p>
          <h2>Revenue and cost by product line</h2>
        </div>
        <span className="live-indicator">{netMargin >= 0 ? '+' : ''}${Math.round(netMargin).toLocaleString()} net</span>
      </div>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 36, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
            <XAxis dataKey="name" tick={{ ...AX, fontSize: 9 }} tickLine={false} axisLine={GRID} angle={-28} textAnchor="end" interval={0} />
            <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={(v) => `$${Math.round((v as number) / 1000)}k`} width={42} />
            <ReferenceLine y={0} stroke="#c5d0cb" strokeWidth={1.5} />
            <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown) => [`$${Math.round(v as number).toLocaleString()}`, 'Amount'] as [string, string]} />
            <Bar dataKey="amount" radius={[3, 3, 0, 0]}>
              {data.map((entry, i) => (
                <Cell key={i} fill={entry.amount >= 0 ? '#1A74D8' : '#a23b35'} fillOpacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}

function ScenarioChartPanel({ outcomes }: { outcomes: Array<{ label: string; netRevenue: number; probability: number }> }) {
  const data = outcomes.map((o) => ({
    name: o.label.replace('Price ', 'P').replace('Demand ', 'D').replace(' scenario', '').slice(0, 14),
    revenue: o.netRevenue,
    prob: Math.round(o.probability * 100),
  }))
  return (
    <div className="chart-area">
      <p className="label" style={{ marginBottom: 6 }}>Revenue by scenario</p>
      <ResponsiveContainer width="100%" height={170}>
        <BarChart data={data} margin={{ top: 4, right: 16, bottom: 28, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
          <XAxis dataKey="name" tick={{ ...AX, fontSize: 9 }} tickLine={false} axisLine={GRID} angle={-18} textAnchor="end" interval={0} />
          <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={(v) => `$${Math.round((v as number) / 1000)}k`} width={42} />
          <ReferenceLine y={0} stroke="#c5d0cb" strokeWidth={1.5} />
          <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown, n?: string | number) => [(n === 'revenue' ? `$${Math.round(v as number).toLocaleString()}` : `${v as number}%`), (n === 'revenue' ? 'Net revenue' : 'Probability')] as [string, string]} />
          <Bar dataKey="revenue" radius={[3, 3, 0, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.revenue >= 0 ? '#1A74D8' : '#a23b35'} fillOpacity={0.82} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function TornadoChartPanel() {
  return (
    <div className="chart-area">
      <p className="label" style={{ marginBottom: 6 }}>Sensitivity tornado — score delta per assumption</p>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={tornadoSeries} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" {...GRID} horizontal={false} />
          <XAxis type="number" tick={AX} tickLine={false} axisLine={GRID} />
          <YAxis type="category" dataKey="label" tick={{ ...AX, fontSize: 9 }} tickLine={false} axisLine={false} width={150} />
          <ReferenceLine x={0} stroke="#c5d0cb" strokeWidth={1.5} />
          <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown) => [(v as number) > 0 ? `+${v as number}` : String(v as number), 'Score delta'] as [string, string]} />
          <Bar dataKey="delta" radius={[0, 3, 3, 0]}>
            {tornadoSeries.map((entry, i) => (
              <Cell key={i} fill={entry.delta >= 0 ? '#1A74D8' : '#a23b35'} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function CandidateScoreChartPanel() {
  return (
    <div className="chart-area">
      <p className="label" style={{ marginBottom: 6 }}>Candidate score comparison</p>
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={candidateScoreSeries} margin={{ top: 4, right: 16, bottom: 30, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
          <XAxis dataKey="name" tick={{ ...AX, fontSize: 9 }} tickLine={false} axisLine={GRID} angle={-18} textAnchor="end" interval={0} />
          <YAxis domain={[0, 100]} tick={AX} tickLine={false} axisLine={false} width={28} />
          <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown) => [String(v as number), 'Score'] as [string, string]} />
          <Bar dataKey="score" radius={[3, 3, 0, 0]}>
            {candidateScoreSeries.map((entry, i) => (
              <Cell key={i} fill={entry.score >= 80 ? '#1A74D8' : entry.score >= 65 ? '#9b6515' : '#a23b35'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function KpiCard({
  metricId,
  activeSlots,
  onSwap,
}: {
  metricId: MetricId
  activeSlots: MetricId[]
  onSwap: (next: MetricId) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLElement>(null)
  const { label, value, detail, icon: Icon } = metricRegistry[metricId]

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <section className="metric-card" ref={ref} onClick={() => setOpen(o => !o)} role="button" tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && setOpen(o => !o)}>
      <div className="metric-icon"><Icon size={18} /></div>
      <div>
        <p className="label">{label}</p>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
      {open && (
        <div className="metric-menu" onClick={e => e.stopPropagation()}>
          <div className="metric-menu-title">Swap metric</div>
          {allMetricIds.map(id => (
            <button
              key={id}
              className={id === metricId ? 'active' : activeSlots.includes(id) && id !== metricId ? '' : ''}
              style={activeSlots.includes(id) && id !== metricId ? { opacity: 0.45 } : {}}
              onClick={() => { onSwap(id); setOpen(false) }}
            >
              {metricRegistry[id].label}
              {id === metricId && <span style={{ marginLeft: 'auto', fontSize: 10 }}>✓</span>}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

function PageHeader({
  eyebrow,
  title,
  meta,
}: {
  eyebrow: string
  title: string
  meta: string
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      <div className="status-strip">
        <span>Mock interval 11:55 PDT</span>
        <b>{stats.readiness}% ready</b>
        <em>{meta}</em>
      </div>
    </header>
  )
}

function ScorePill({ score }: { score: number }) {
  return (
    <span className={score >= 80 ? 'score-pill strong' : score >= 65 ? 'score-pill watch' : 'score-pill risk'}>
      {score}
    </span>
  )
}

function CommandPage({
  selectedDecision,
  setSelectedDecisionId,
  goToPage,
}: {
  selectedDecision: DecisionCandidate
  setSelectedDecisionId: (id: string) => void
  goToPage: (page: PageId) => void
}) {
  const [kpiSlots, setKpiSlots] = useState<MetricId[]>(['capacity', 'available', 'forecast', 'readiness'])
  const [minScore, setMinScore] = useState(0)
  const [decisionSort, setDecisionSort] = useState<'score' | 'mw' | 'action'>('score')
  const [queueCollapsed, setQueueCollapsed] = useState(false)

  const swapKpi = (slotIdx: number, next: MetricId) =>
    setKpiSlots(slots => slots.map((s, i) => i === slotIdx ? next : s))

  const filteredDecisions = useMemo(() =>
    [...decisionCandidates]
      .filter(d => d.score >= minScore)
      .sort((a, b) =>
        decisionSort === 'score' ? b.score - a.score :
        decisionSort === 'mw' ? b.targetMw - a.targetMw :
        a.action.localeCompare(b.action)
      ),
    [minScore, decisionSort]
  )

  return (
    <>
      <PageHeader eyebrow="CAISO aggregate portfolio" title="Command" meta={`${stats.constrained} constrained sources`} />

      <section className="metrics-grid">
        {kpiSlots.map((id, i) => (
          <KpiCard key={`${id}-${i}`} metricId={id} activeSlots={kpiSlots} onSwap={next => swapKpi(i, next)} />
        ))}
      </section>

      <LmpChartPanel />
      <FleetDispatchChart />

      <section className="decision-layout">
        <article className="decision-hero">
          <div className="decision-kicker">
            <span>Recommended action</span>
            <b>{selectedDecision.market.interval}</b>
          </div>
          <div className="decision-main">
            <div>
              <p className="label">{selectedDecision.market.product}</p>
              <h2>
                {actionLabels[selectedDecision.action]} {selectedDecision.targetMw} MW
              </h2>
              <p>{selectedDecision.explanation}</p>
            </div>
            <div className="confidence-dial" style={{
              background: `radial-gradient(circle at center, #fff 54%, transparent 55%), conic-gradient(var(--green) 0 ${selectedDecision.score}%, var(--surface-2) ${selectedDecision.score}% 100%)`
            }}>
              <span>{selectedDecision.score}</span>
              <small>score</small>
            </div>
          </div>
          <div className="tradeoff-grid">
            <span><b>Revenue</b><em>{selectedDecision.revenue}/100</em></span>
            <span><b>Reliability</b><em>{selectedDecision.reliability}/100</em></span>
            <span><b>Obligation</b><em>{selectedDecision.obligationFit}%</em></span>
            <span><b>Enrollment</b><em>{selectedDecision.enrollmentFit}%</em></span>
            <span><b>Risk</b><em>{selectedDecision.riskPenalty}</em></span>
          </div>
          {selectedDecision.robustModel && (
            <div className="robust-summary">
              <span><b>{selectedDecision.robustModel.feasibility}%</b><em>Feasible</em></span>
              <span><b>{formatSignedUsd(selectedDecision.robustModel.expectedRevenue)}</b><em>Expected net</em></span>
              <span><b>{formatSignedUsd(selectedDecision.robustModel.downsideRevenue)}</b><em>Downside net</em></span>
              <span><b>{selectedDecision.robustModel.rampFeasibleMw} MW</b><em>Ramp feasible</em></span>
            </div>
          )}
          <div className="action-row">
            <button className="primary" type="button" onClick={() => goToPage('runlog')}>
              <CheckCircle2 size={17} /> Review package
            </button>
            <button type="button" onClick={() => goToPage('model')}>
              <SlidersHorizontal size={17} /> Inspect model
            </button>
          </div>
        </article>

        <aside className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Decision queue</p>
              <h2>Candidate ordering</h2>
            </div>
            <button className="icon-btn" title={queueCollapsed ? 'Expand' : 'Collapse'} onClick={() => setQueueCollapsed(c => !c)}>
              <ChevronDown size={13} style={{ transform: queueCollapsed ? 'rotate(-90deg)' : 'none', transition: 'transform .2s' }} />
            </button>
          </div>
          {!queueCollapsed && (
            <>
              <div className="opt-bar">
                <span className="opt-label">Sort</span>
                <button className={`opt-pill${decisionSort === 'score' ? ' active' : ''}`} onClick={() => setDecisionSort('score')}>Score</button>
                <button className={`opt-pill${decisionSort === 'mw' ? ' active' : ''}`} onClick={() => setDecisionSort('mw')}>MW</button>
                <button className={`opt-pill${decisionSort === 'action' ? ' active' : ''}`} onClick={() => setDecisionSort('action')}>Action</button>
                <div className="opt-sep" />
                <div className="score-filter">
                  <span>Min {minScore}</span>
                  <input type="range" min={0} max={80} step={5} value={minScore} onChange={e => setMinScore(+e.target.value)} />
                </div>
              </div>
              <div className="queue-list" style={{ marginTop: 10 }}>
                {filteredDecisions.map((decision) => (
                  <button
                    className={decision.id === selectedDecision.id ? 'queue-row active' : 'queue-row'}
                    key={decision.id}
                    type="button"
                    onClick={() => setSelectedDecisionId(decision.id)}
                  >
                    <div>
                      <strong>{actionLabels[decision.action]} {decision.targetMw} MW</strong>
                      <span>{decision.market.product} · {decision.market.interval}</span>
                    </div>
                    <ScorePill score={decision.score} />
                  </button>
                ))}
                {filteredDecisions.length === 0 && (
                  <p style={{ color: 'var(--muted)', fontSize: 12, padding: '8px 0' }}>No candidates above score {minScore}</p>
                )}
              </div>
            </>
          )}
        </aside>
      </section>

      <section className="two-up">
        <DispatchPlanPanel />
        <ApprovalPanel />
      </section>
    </>
  )
}

function DispatchPlanPanel() {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <p className="label">Advisory dispatch</p>
          <h2>Bid blocks and asset instructions</h2>
        </div>
        <span className="live-indicator">{dispatchPlan.mode}</span>
      </div>
      <div className="bid-block-grid">
        {dispatchPlan.bidBlocks.map((bid) => (
          <article className="bid-card" key={`${bid.product}-${bid.interval}`}>
            <div><strong>{bid.product}</strong><span>{bid.region} · {bid.interval}</span></div>
            <b>{bid.quantityMw} MW</b>
            <em>{formatUsd(bid.limitPrice)}/MWh</em>
            <small>{bid.confidence}% conf</small>
          </article>
        ))}
      </div>
      <div className="instruction-list">
        {dispatchPlan.instructions.map((instruction) => (
          <article className="instruction-row" key={`${instruction.assetId}-${instruction.targetMw}`}>
            <div><strong>{assetById[instruction.assetId]?.name}</strong><span>{instruction.reason}</span></div>
            <b>{instruction.targetMw} MW</b>
            <em>{instruction.rampRateMwPerMinute} MW/min</em>
            <small>{instruction.requiresApproval ? 'review' : 'clear'}</small>
          </article>
        ))}
      </div>
    </section>
  )
}

function ApprovalPanel() {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <p className="label">Approval gates</p>
          <h2>What must clear first</h2>
        </div>
      </div>
      <div className="gate-list">
        {dispatchPlan.approvalGates.map((gate) => (
          <article className={`gate-row ${gate.status}`} key={gate.id}>
            <div><strong>{gate.label}</strong><span>{gate.rationale}</span></div>
            <em>{gate.status}</em>
          </article>
        ))}
      </div>
    </section>
  )
}

function PortfolioPage({
  selectedAsset,
  setSelectedAssetId,
}: {
  selectedAsset: Asset
  setSelectedAssetId: (id: string) => void
}) {
  const [sortKey, setSortKey] = useState<'name' | 'mw' | 'readiness' | 'telemetry'>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [typeFilter, setTypeFilter] = useState<AssetType | 'all'>('all')
  const [showEnvelopes, setShowEnvelopes] = useState(true)
  const [showTelemetry, setShowTelemetry] = useState(true)
  const [showPolicies, setShowPolicies] = useState(true)

  const cycleSort = (key: typeof sortKey) => {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const sortArrow = (key: typeof sortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''

  const displayAssets = useMemo(() => {
    const filtered = typeFilter === 'all' ? assets : assets.filter(a => a.type === typeFilter)
    return [...filtered].sort((a, b) => {
      let cmp = 0
      if (sortKey === 'name') cmp = a.name.localeCompare(b.name)
      else if (sortKey === 'mw') cmp = a.availableMw - b.availableMw
      else if (sortKey === 'readiness') cmp = a.readiness - b.readiness
      else cmp = a.telemetry.localeCompare(b.telemetry)
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [sortKey, sortDir, typeFilter])

  const assetTelemetry = telemetrySamples.filter((sample) => sample.assetId === selectedAsset.id)
  const assetEnvelopes = flexibilityEnvelopes.filter((envelope) => envelope.assetId === selectedAsset.id)
  const assetPolicies = constraintPolicies.filter((policy) => policy.assetId === selectedAsset.id)
  const AssetIcon = assetIcons[selectedAsset.type]
  const assetTypes = [...new Set(assets.map(a => a.type))] as AssetType[]

  return (
    <>
      <PageHeader eyebrow="Resource operations" title="Portfolio" meta={`${assets.length} assets`} />
      <section className="portfolio-layout">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Asset roster</p>
              <h2>Click a resource to inspect it</h2>
            </div>
          </div>
          <div className="opt-bar">
            <span className="opt-label">Filter</span>
            <button className={`opt-pill${typeFilter === 'all' ? ' active' : ''}`} onClick={() => setTypeFilter('all')}>All</button>
            {assetTypes.map(t => (
              <button key={t} className={`opt-pill${typeFilter === t ? ' active' : ''}`} onClick={() => setTypeFilter(t)}>{t}</button>
            ))}
          </div>
          <div className="asset-table" style={{ marginTop: 10 }}>
            <div className="asset-table-head">
              <button className={`sort-head${sortKey === 'name' ? ' active' : ''}`} onClick={() => cycleSort('name')}>Asset{sortArrow('name')}</button>
              <span>Region</span>
              <button className={`sort-head${sortKey === 'mw' ? ' active' : ''}`} onClick={() => cycleSort('mw')}>MW{sortArrow('mw')}</button>
              <button className={`sort-head${sortKey === 'readiness' ? ' active' : ''}`} onClick={() => cycleSort('readiness')}>Ready{sortArrow('readiness')}</button>
              <button className={`sort-head${sortKey === 'telemetry' ? ' active' : ''}`} onClick={() => cycleSort('telemetry')}>Telemetry{sortArrow('telemetry')}</button>
            </div>
            {displayAssets.map((asset) => {
              const Icon = assetIcons[asset.type]
              return (
                <button
                  className={asset.id === selectedAsset.id ? 'asset-table-row selected' : 'asset-table-row'}
                  key={asset.id}
                  type="button"
                  onClick={() => setSelectedAssetId(asset.id)}
                >
                  <div className="asset-title"><Icon size={18} /><div><strong>{asset.name}</strong><span>{asset.type}</span></div></div>
                  <span>{asset.region}</span>
                  <b>{asset.availableMw}/{asset.capacityMw}</b>
                  <div className="bar-track"><span style={{ width: `${asset.readiness}%` }} /></div>
                  <em className={asset.telemetry}>{asset.telemetry}</em>
                </button>
              )
            })}
          </div>
        </section>

        <aside className="panel asset-detail">
          <div className="asset-detail-head">
            <div className="metric-icon"><AssetIcon size={19} /></div>
            <div>
              <p className="label">{selectedAsset.region}</p>
              <h2>{selectedAsset.name}</h2>
              <span>{selectedAsset.constraint}</span>
            </div>
          </div>
          <div className="detail-grid">
            <span><b>{selectedAsset.capacityMw} MW</b><em>Capacity</em></span>
            <span><b>{selectedAsset.availableMw} MW</b><em>Available</em></span>
            <span><b>{selectedAsset.readiness}%</b><em>Readiness</em></span>
            <span><b>{selectedAsset.stateOfCharge ?? 'n/a'}%</b><em>SOC</em></span>
          </div>
          <div className="opt-bar" style={{ marginBottom: 10 }}>
            <span className="opt-label">Show</span>
            <button className={`opt-pill${showEnvelopes ? ' active' : ' off'}`} onClick={() => setShowEnvelopes(v => !v)}>Envelopes</button>
            <button className={`opt-pill${showTelemetry ? ' active' : ' off'}`} onClick={() => setShowTelemetry(v => !v)}>Telemetry</button>
            <button className={`opt-pill${showPolicies ? ' active' : ' off'}`} onClick={() => setShowPolicies(v => !v)}>Policies</button>
          </div>
          <div className="compact-list">
            {showEnvelopes && assetEnvelopes.map((envelope) => (
              <div className="compact-row" key={`${envelope.assetId}-${envelope.interval}`}>
                <div><strong>{envelope.interval}</strong><span>{envelope.confidence}% envelope confidence</span></div>
                <b>{envelope.maxExportMw} MW</b>
                <em>{envelope.rampRateMwPerMinute} MW/min</em>
                <small>{envelope.controlLatencySeconds + envelope.telemetryLatencySeconds}s loop</small>
              </div>
            ))}
            {showTelemetry && assetTelemetry.map((sample) => (
              <div className="telemetry-chip wide" key={`${sample.assetId}-${sample.timestamp}`}>
                <strong>{sample.source}</strong>
                <span>{sample.timestamp.slice(11, 19)}Z</span>
                <b>{sample.realPowerMw} MW</b>
                <em className={sample.quality}>{sample.quality}</em>
              </div>
            ))}
            {showPolicies && assetPolicies.map((policy) => (
              <div className="policy-row" key={policy.id}>
                <div><strong>{policy.source}</strong><span>{policy.operatorApprovalRequired ? 'Approval required' : 'Automated gate'}</span></div>
                <p>{policy.rule}</p>
                <em className={policy.severity}>{policy.severity}</em>
              </div>
            ))}
          </div>
        </aside>
      </section>

      <CapacityChartPanel />
    </>
  )
}

function MarketsPage() {
  const [riskFilter, setRiskFilter] = useState<'all' | 'low' | 'medium' | 'high'>('all')
  const [sortKey, setSortKey] = useState<'price' | 'confidence' | 'obligation'>('price')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [view, setView] = useState<'list' | 'cards'>('list')
  const [settleCollapsed, setSettleCollapsed] = useState(false)

  const cycleSort = (k: typeof sortKey) => {
    if (sortKey === k) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('desc') }
  }

  const displaySignals = useMemo(() => {
    const filtered = riskFilter === 'all' ? marketSignals : marketSignals.filter(s => s.risk === riskFilter)
    return [...filtered].sort((a, b) => {
      const cmp = sortKey === 'price' ? a.price - b.price
        : sortKey === 'confidence' ? a.confidence - b.confidence
        : a.obligationMw - b.obligationMw
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [riskFilter, sortKey, sortDir])

  return (
    <>
      <PageHeader eyebrow="Market desk" title="Markets" meta={`${marketSignals.length} products`} />
      <section className="market-layout">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Signal board</p>
              <h2>Prices, obligations, grid state</h2>
            </div>
            <div className="panel-actions">
              <CloudSun size={19} />
              <div className="view-toggle">
                <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')} title="List"><List size={13} /></button>
                <button className={view === 'cards' ? 'active' : ''} onClick={() => setView('cards')} title="Cards"><LayoutGrid size={13} /></button>
              </div>
            </div>
          </div>
          <div className="opt-bar">
            <span className="opt-label">Risk</span>
            {(['all','low','medium','high'] as const).map(r => (
              <button key={r} className={`opt-pill${riskFilter === r ? ' active' : ''}`} onClick={() => setRiskFilter(r)}>{r === 'all' ? 'All' : r}</button>
            ))}
            <div className="opt-sep" />
            <span className="opt-label">Sort</span>
            <button className={`opt-pill${sortKey === 'price' ? ' active' : ''}`} onClick={() => cycleSort('price')}>Price {sortKey === 'price' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</button>
            <button className={`opt-pill${sortKey === 'confidence' ? ' active' : ''}`} onClick={() => cycleSort('confidence')}>Confidence {sortKey === 'confidence' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</button>
            <button className={`opt-pill${sortKey === 'obligation' ? ' active' : ''}`} onClick={() => cycleSort('obligation')}>Obligation {sortKey === 'obligation' ? (sortDir === 'desc' ? '↓' : '↑') : ''}</button>
          </div>
          {view === 'list' ? (
            <div className="market-table" style={{ marginTop: 10 }}>
              {displaySignals.map((signal) => (
                <article className="market-row" key={`${signal.product}-${signal.region}`}>
                  <div><strong>{signal.product}</strong><span>{signal.region}</span></div>
                  <div><strong>${signal.price}/MWh</strong><span>{signal.confidence}% confidence</span></div>
                  <div><strong>{signal.gridCondition}</strong><span>Grid</span></div>
                  <div><strong>{signal.weatherSignal}</strong><span>{signal.obligationMw} MW obligation</span></div>
                  <span className={`risk ${signal.risk}`}>{signal.risk}</span>
                </article>
              ))}
            </div>
          ) : (
            <div className="market-cards" style={{ marginTop: 10 }}>
              {displaySignals.map((signal) => (
                <div className="market-card" key={`${signal.product}-${signal.region}`}>
                  <strong>{signal.product}</strong>
                  <div className="market-card-price">${signal.price}<small style={{ fontSize: 12, fontWeight: 400, color: 'var(--muted)' }}>/MWh</small></div>
                  <div className="market-card-meta">
                    <span className={`risk ${signal.risk}`}>{signal.risk}</span>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>{signal.region}</span>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>{signal.confidence}% conf</span>
                  </div>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>{signal.obligationMw} MW · {signal.gridCondition}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel settlement-panel">
          <div className="panel-head">
            <div>
              <p className="label">Settlement view</p>
              <h2>Expected award and margin</h2>
            </div>
            <div className="panel-actions">
              <span className="live-indicator">{formatSignedUsd(settlementProjection.netMargin)}</span>
              <button className="icon-btn" onClick={() => setSettleCollapsed(c => !c)} title={settleCollapsed ? 'Expand' : 'Collapse'}>
                <ChevronDown size={13} style={{ transform: settleCollapsed ? 'rotate(-90deg)' : 'none', transition: 'transform .2s' }} />
              </button>
            </div>
          </div>
          {!settleCollapsed && (
            <>
              <div className="settlement-summary">
                <span><b>{settlementProjection.expectedAwardMw} MW</b><em>Award</em></span>
                <span><b>{settlementProjection.deliveredP50Mw} MW</b><em>P50</em></span>
                <span><b>{settlementProjection.deliveredP05Mw} MW</b><em>P05</em></span>
                <span><b>{formatSignedUsd(settlementProjection.marginPerMw)}</b><em>Per MW</em></span>
              </div>
              <div className="settlement-lines">
                {settlementProjection.lines.map((line) => (
                  <article className={`settlement-row ${line.category}`} key={line.id}>
                    <div><strong>{line.label}</strong><span>{line.quantityMw} MW · {formatUsd(line.price)}/MWh</span></div>
                    <b>{formatSignedUsd(line.amount)}</b>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </section>

      <PriceFanChart />
      <WaterfallChartPanel lines={settlementProjection.lines} netMargin={settlementProjection.netMargin} />

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Enrollment coverage</p>
            <h2>Program eligibility and offer limits</h2>
          </div>
          <span className="live-indicator">{marketEnrollments.filter((item) => item.status === 'active').length} active</span>
        </div>
        <div className="enrollment-grid">
          {marketEnrollments.map((enrollment) => (
            <article className={`enrollment-row ${enrollment.status}`} key={enrollment.id}>
              <div><strong>{assetById[enrollment.assetId]?.name}</strong><span>{enrollment.program}</span></div>
              <b>{enrollment.product}</b>
              <em>{enrollment.minOfferMw}-{enrollment.maxOfferMw} MW</em>
              <small>{enrollment.telemetryRequirementSeconds}s telemetry</small>
              <span className={`risk ${enrollment.settlementRisk}`}>{enrollment.settlementRisk}</span>
            </article>
          ))}
        </div>
      </section>
    </>
  )
}

function CoordinationPage() {
  const [statusFilter, setStatusFilter] = useState<'all' | 'ready' | 'review' | 'blocked'>('all')
  const [ownerFilter, setOwnerFilter] = useState('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const owners = ['all', 'RTO/ISO', 'Distribution utility', 'Aggregator', 'Customer', 'Internal']

  const filtered = useMemo(() =>
    coordinationReadiness.checkpoints.filter(cp =>
      (statusFilter === 'all' || cp.status === statusFilter) &&
      (ownerFilter === 'all' || cp.owner === ownerFilter)
    ), [statusFilter, ownerFilter])

  const exportReport = () => downloadJson(`coordination-${Date.now()}.json`, {
    generatedAt: new Date().toISOString(),
    score: coordinationReadiness.score,
    blockedCount: coordinationReadiness.blockedCount,
    checkpoints: coordinationReadiness.checkpoints,
  })

  return (
    <>
      <PageHeader eyebrow="Market participation" title="Coordination" meta={`${coordinationReadiness.score}% coordination ready`} />
      <section className="coordination-layout">
        <section className="panel coordination-score-panel">
          <div className="panel-head">
            <div>
              <p className="label">Order 2222 operating surface</p>
              <h2>What has to line up before dispatch</h2>
            </div>
            <span className="live-indicator">{coordinationReadiness.blockedCount} blocked</span>
          </div>
          <div className="coordination-score">
            <div className="confidence-dial coordination-dial">
              <span>{coordinationReadiness.score}</span>
              <small>ready</small>
            </div>
            <div className="coordination-counts">
              <span><b>{coordinationReadiness.readyCount}</b><em>Ready</em></span>
              <span><b>{coordinationReadiness.reviewCount}</b><em>Review</em></span>
              <span><b>{coordinationReadiness.blockedCount}</b><em>Blocked</em></span>
            </div>
          </div>
          <div className="coordination-note">
            <strong>Coordination posture</strong>
            <p>VELA can recommend a bid, but approval should stay gated until resource eligibility, telemetry, utility review, and customer constraints are all replayable.</p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Responsibility map</p>
              <h2>Owners and timing</h2>
            </div>
          </div>
          <div className="owner-grid">
            {['RTO/ISO', 'Distribution utility', 'Aggregator', 'Customer', 'Internal'].map((owner) => {
              const owned = coordinationReadiness.checkpoints.filter((item) => item.owner === owner)
              const blocked = owned.filter((item) => item.status === 'blocked').length
              return (
                <article
                  className={`owner-card${ownerFilter === owner ? ' selected' : ''}`}
                  key={owner}
                  onClick={() => setOwnerFilter(ownerFilter === owner ? 'all' : owner)}
                  style={{ cursor: 'pointer' }}
                >
                  <strong>{owner}</strong>
                  <span>{owned.length} checkpoints</span>
                  <em className={blocked > 0 ? 'text-warn' : ''}>{blocked > 0 ? `${blocked} blocked` : 'No blocks'}</em>
                </article>
              )
            })}
          </div>
        </section>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Coordination checklist</p>
            <h2>Registration, telemetry, utility review, customer rules</h2>
          </div>
          <div className="panel-actions">
            <span className="live-indicator">{filtered.length} shown</span>
            <button className="icon-btn" onClick={exportReport} title="Export coordination report">
              <Download size={13} />
            </button>
          </div>
        </div>
        <div className="opt-bar">
          <span className="opt-label">Status</span>
          {(['all', 'ready', 'review', 'blocked'] as const).map(s => (
            <button key={s} className={`opt-pill${statusFilter === s ? ' active' : ''}`}
              onClick={() => setStatusFilter(s)}>{s === 'all' ? 'All' : s}</button>
          ))}
          <div className="opt-sep" />
          <span className="opt-label">Owner</span>
          <select className="inline-select" value={ownerFilter} onChange={e => setOwnerFilter(e.target.value)}>
            {owners.map(o => <option key={o} value={o}>{o === 'all' ? 'All owners' : o}</option>)}
          </select>
        </div>
        <div className="coordination-list">
          {filtered.map((checkpoint) => (
            <article
              key={checkpoint.id}
              className={`coordination-row ${checkpoint.status}${expandedId === checkpoint.id ? ' expanded' : ''}`}
              onClick={() => setExpandedId(expandedId === checkpoint.id ? null : checkpoint.id)}
              style={{ cursor: 'pointer' }}
            >
              <div className="cp-main">
                <ChevronRight size={13} className={`cp-chevron${expandedId === checkpoint.id ? ' open' : ''}`} />
                <div>
                  <strong>{checkpoint.label}</strong>
                  <span>{checkpoint.requirement}</span>
                </div>
              </div>
              <b>{checkpoint.owner}</b>
              <em>{checkpoint.dueBy}</em>
              <small className={`risk ${checkpoint.risk}`}>{checkpoint.risk}</small>
              {expandedId === checkpoint.id && (
                <div className="cp-detail">
                  <div className="cp-detail-row"><span>Evidence</span><p>{checkpoint.evidence}</p></div>
                  <div className="cp-detail-row"><span>Requirement</span><p>{checkpoint.requirement}</p></div>
                  <div className="cp-detail-row"><span>Owner</span><p>{checkpoint.owner}</p></div>
                  <div className="cp-detail-row"><span>Due</span><p>{checkpoint.dueBy}</p></div>
                </div>
              )}
            </article>
          ))}
          {filtered.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: 12, padding: '12px 0' }}>No checkpoints match the current filter.</p>
          )}
        </div>
      </section>
    </>
  )
}

function ModelPage({ selectedDecision }: { selectedDecision: DecisionCandidate }) {
  const [weights, setWeights] = useState({ revenue: 60, reliability: 25, degradation: 15 })
  const [expandedSensId, setExpandedSensId] = useState<string | null>(null)

  const reranked = useMemo(() => {
    const total = weights.revenue + weights.reliability + weights.degradation || 1
    return [...decisionCandidates]
      .map(d => ({
        ...d,
        adjScore: Math.round(
          (d.revenue / 100) * (weights.revenue / total) * 100 +
          (d.reliability / 100) * (weights.reliability / total) * 100 +
          (100 - d.riskPenalty) / 100 * (weights.degradation / total) * 100
        ),
      }))
      .sort((a, b) => b.adjScore - a.adjScore)
  }, [weights])

  const exportModelRun = () => downloadJson(`model-run-${Date.now()}.json`, {
    generatedAt: new Date().toISOString(),
    modelVersion: modelRunSnapshot.modelVersion,
    objectiveWeights: weights,
    topDecision: { action: selectedDecision.action, targetMw: selectedDecision.targetMw, score: selectedDecision.score },
    candidates: decisionCandidates.map(d => ({ id: d.id, action: d.action, targetMw: d.targetMw, score: d.score })),
    sensitivityCases: sensitivityCases.map(s => ({ label: s.label, scoreDelta: s.scoreDelta })),
    robustModel: selectedDecision.robustModel,
  })

  return (
    <>
      <PageHeader eyebrow="Optimization workbench" title="Model" meta={selectedDecision.robustModel ? `${selectedDecision.robustModel.scenarios.length} scenarios` : 'No robust model'} />

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Objective weights</p>
            <h2>Adjust to see how rankings shift</h2>
          </div>
          <button className="icon-btn" onClick={exportModelRun} title="Export model run JSON">
            <Download size={13} />
          </button>
        </div>
        <div className="weight-editor">
          {(['revenue', 'reliability', 'degradation'] as const).map(key => (
            <div key={key} className="weight-row">
              <span className="weight-label">{key.charAt(0).toUpperCase() + key.slice(1)}</span>
              <input
                type="range" min={0} max={100} step={5}
                value={weights[key]}
                onChange={e => setWeights(w => ({ ...w, [key]: +e.target.value }))}
              />
              <span className="weight-val">{weights[key]}</span>
            </div>
          ))}
        </div>
        <div className="rerank-list">
          {reranked.slice(0, 5).map((d, i) => (
            <div key={d.id} className={`rerank-row${i === 0 ? ' top' : ''}`}>
              <span className="rerank-pos">#{i + 1}</span>
              <div><strong>{actionLabels[d.action]} {d.targetMw} MW</strong><span>{d.market.product}</span></div>
              <div className="rerank-scores">
                <span>adj <b>{d.adjScore}</b></span>
                <span className="rerank-orig">orig {d.score}</span>
              </div>
            </div>
          ))}
        </div>
      </section>
      {selectedDecision.robustModel && (
        <>
          <section className="model-overview">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Scenario outcomes</p>
                  <h2>Tail exposure by case</h2>
                </div>
              </div>
              <ScenarioChartPanel outcomes={selectedDecision.robustModel.scenarioOutcomes} />
              <div className="scenario-outcome-list">
                {selectedDecision.robustModel.scenarioOutcomes.map((outcome) => (
                  <article className="scenario-outcome-row" key={outcome.scenarioId}>
                    <div><strong>{outcome.label}</strong><span>{Math.round(outcome.probability * 100)}% probability</span></div>
                    <b>{outcome.deliveredMw} MW</b>
                    <em>{outcome.effectiveShortfallMw} MW shortfall</em>
                    <small>{formatSignedUsd(outcome.netRevenue)}</small>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Risk anatomy</p>
                  <h2>Dominant contributors</h2>
                </div>
              </div>
              <div className="risk-stack">
                {selectedDecision.robustModel.riskContributions.map((risk) => (
                  <article className={`risk-contribution ${risk.severity}`} key={risk.id}>
                    <div><strong>{risk.label}</strong><span>{risk.value} model units</span></div>
                    <b>{risk.share}%</b>
                    <div className="risk-bar"><span style={{ width: `${risk.share}%` }} /></div>
                  </article>
                ))}
              </div>
            </section>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <p className="label">Sensitivity analysis</p>
                <h2>Recommendation movement under stressed assumptions</h2>
              </div>
            </div>
            <TornadoChartPanel />
            <div className="sensitivity-grid">
              {sensitivityCases.map((item) => (
                <article
                  key={item.id}
                  className={`sensitivity-card ${item.scoreDelta < 0 ? 'negative' : 'positive'}${expandedSensId === item.id ? ' sens-expanded' : ''}`}
                  onClick={() => setExpandedSensId(expandedSensId === item.id ? null : item.id)}
                  style={{ cursor: 'pointer' }}
                >
                  <div className="sensitivity-head">
                    <div><strong>{item.label}</strong><span>{item.parameter} {item.direction === 'up' ? '+' : '-'}{item.deltaPercent}%</span></div>
                    <b>{item.scoreDelta > 0 ? '+' : ''}{item.scoreDelta}</b>
                  </div>
                  <div className="sensitivity-values">
                    <span><b>{formatSignedUsd(item.expectedRevenueDelta)}</b><em>Revenue</em></span>
                    <span><b>{item.feasibilityDelta > 0 ? '+' : ''}{item.feasibilityDelta}</b><em>Feasibility</em></span>
                  </div>
                  {expandedSensId === item.id
                    ? <p style={{ marginTop: 8, fontSize: 12, lineHeight: 1.6 }}>{item.interpretation}</p>
                    : <p className="sens-preview">{item.interpretation}</p>
                  }
                </article>
              ))}
            </div>
          </section>

          <section className="two-up">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Allocation</p>
                  <h2>Merit-order asset participation</h2>
                </div>
              </div>
              <div className="allocation-list">
                {selectedDecision.robustModel.allocations.map((allocation) => (
                  <div className="allocation-row" key={allocation.assetId}>
                    <div><strong>{assetById[allocation.assetId]?.name}</strong><span>{assetById[allocation.assetId]?.type}</span></div>
                    <b>{allocation.dispatchMw} MW</b>
                    <div className="bar-track"><span style={{ width: `${allocation.confidence}%` }} /></div>
                    <em>{allocation.rampFeasibleMw} MW ramp</em>
                    <small>{allocation.responseTimeSeconds}s response</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Constraints</p>
                  <h2>Slack and severity</h2>
                </div>
              </div>
              <div className="constraint-matrix">
                {selectedDecision.robustModel.constraints.map((constraint) => (
                  <div className={`constraint-row ${constraint.satisfied ? 'satisfied' : 'violated'}`} key={constraint.id}>
                    <div><strong>{constraint.label}</strong><span>{constraint.severity}</span></div>
                    <b>{constraint.lhs} {constraint.operator} {constraint.rhs}</b>
                    <em>{constraint.slack >= 0 ? '+' : ''}{constraint.slack} slack</em>
                  </div>
                ))}
              </div>
            </section>
          </section>
        </>
      )}
    </>
  )
}

function ConnectorLogo({ connector }: { connector: typeof vppConnectors[number] }) {
  return (
    <span
      className="connector-logo"
      style={{ background: connector.brand, color: connector.brandInk ?? '#ffffff' }}
      aria-hidden
    >
      {connector.mark}
    </span>
  )
}

function IntegrationsPage() {
  const [expandedAdapter, setExpandedAdapter] = useState<string | null>(null)
  const [healthFilter, setHealthFilter] = useState<'all' | 'healthy' | 'limited' | 'delayed'>('all')
  const [connectorFilter, setConnectorFilter] = useState<'all' | 'connected' | 'available' | 'beta'>('all')

  const filteredConnectors = useMemo(() =>
    connectorFilter === 'all' ? vppConnectors : vppConnectors.filter(c => c.status === connectorFilter),
    [connectorFilter])

  const connectedConnectors = useMemo(() => vppConnectors.filter(c => c.status === 'connected'), [])
  const linkedSites = useMemo(() => connectedConnectors.reduce((sum, c) => sum + c.sites, 0), [connectedConnectors])
  const orchestratedMw = useMemo(
    () => connectedConnectors.reduce((sum, c) => sum + c.capacityMw, 0),
    [connectedConnectors])

  const filteredSources = useMemo(() =>
    healthFilter === 'all' ? integrationSources : integrationSources.filter(s => s.health === healthFilter),
    [healthFilter])

  const exportCompliance = () => {
    const lines = [
      `Vela Compliance Report — ${new Date().toISOString()}`,
      `Adapter confidence: ${coverage.confidence}%`,
      `Integration readiness: ${integrationReadiness}%`,
      '',
      '=== Standards ===',
      ...integrationStandards.map(s => `[${s.implementation.toUpperCase()}] ${s.name}: ${s.requirement}`),
      '',
      '=== Readiness Findings ===',
      ...readinessFindings.map(f => `[${f.severity.toUpperCase()}] ${f.label}: ${f.detail}`),
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `compliance-${Date.now()}.txt`; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <PageHeader eyebrow="Data fabric" title="Integrations" meta={`${coverage.confidence}% adapter confidence`} />

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Connected DER & VPP platforms</p>
            <h2>Federating today's siloed vendor clouds into one fleet</h2>
          </div>
          <span className="live-indicator">
            {connectedConnectors.length} connected · {orchestratedMw.toFixed(1)} MW
          </span>
        </div>
        <div className="adapter-summary connector-summary">
          <span><b>{connectedConnectors.length}</b><em>Connected</em></span>
          <span><b>{linkedSites.toLocaleString()}</b><em>Linked sites</em></span>
          <span><b>{orchestratedMw.toFixed(1)}</b><em>MW orchestrated</em></span>
          <span><b>{vppConnectors.length}</b><em>Total connectors</em></span>
        </div>
        <div className="opt-bar">
          <span className="opt-label">Status</span>
          {(['all', 'connected', 'available', 'beta'] as const).map(s => (
            <button key={s} className={`opt-pill${connectorFilter === s ? ' active' : ''}`}
              onClick={() => setConnectorFilter(s)}>{s === 'all' ? 'All' : s}</button>
          ))}
          <span className="opt-label" style={{ marginLeft: 'auto' }}>{filteredConnectors.length} platforms</span>
        </div>
        <div className="connector-grid">
          {filteredConnectors.map((connector) => (
            <article className={`connector-card ${connector.status}`} key={connector.id}>
              <div className="connector-card-head">
                <ConnectorLogo connector={connector} />
                <div className="connector-card-title">
                  <strong>{connector.name}</strong>
                  <span>{connector.category}</span>
                </div>
                <em className={`connector-status ${connector.status}`}>{connector.status}</em>
              </div>
              <p className="connector-protocol">{connector.protocol}</p>
              <div className="connector-meta">
                {connector.status === 'connected' ? (
                  <>
                    <span><b>{connector.sites.toLocaleString()}</b> sites</span>
                    <span><b>{connector.capacityMw.toFixed(1)}</b> MW</span>
                  </>
                ) : (
                  <span className="connector-cta">
                    {connector.status === 'beta' ? 'Early access' : 'Ready to connect'}
                  </span>
                )}
              </div>
            </article>
          ))}
          {filteredConnectors.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: 12, padding: '8px 0' }}>No platforms match the selected status.</p>
          )}
        </div>
      </section>

      <section className="integration-layout">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Adapter normalization</p>
              <h2>Vendor payloads mapped into canonical records</h2>
            </div>
            <div className="panel-actions">
              <span className="live-indicator">{coverage.confidence}% confidence</span>
              <button className="icon-btn" onClick={exportCompliance} title="Export compliance report">
                <Download size={13} />
              </button>
            </div>
          </div>
          <div className="adapter-summary">
            <span><b>{coverage.recordCounts.telemetry}</b><em>Telemetry</em></span>
            <span><b>{coverage.recordCounts.flexibility}</b><em>Flex</em></span>
            <span><b>{coverage.recordCounts.market}</b><em>Market</em></span>
            <span><b>{coverage.recordCounts.constraint}</b><em>Rules</em></span>
          </div>
          <div className="adapter-list">
            {adapterResults.map((result) => (
              <div key={result.payloadId}>
                <article
                  className={`adapter-row${expandedAdapter === result.payloadId ? ' expanded' : ''}`}
                  onClick={() => setExpandedAdapter(expandedAdapter === result.payloadId ? null : result.payloadId)}
                  style={{ cursor: 'pointer' }}
                >
                  <div>
                    <strong>{result.vendor}</strong>
                    <span>{result.adapter} · {result.payloadId}</span>
                  </div>
                  <b>{result.records.map((record) => record.kind).join(', ')}</b>
                  <em>{result.confidence}%</em>
                  <small>{result.warnings[0] ?? 'No warnings'}</small>
                  <ChevronRight size={13} style={{
                    transform: expandedAdapter === result.payloadId ? 'rotate(90deg)' : 'none',
                    transition: 'transform .15s', color: 'var(--muted)', flexShrink: 0,
                  }} />
                </article>
                {expandedAdapter === result.payloadId && (
                  <div className="adapter-detail">
                    <div className="adapter-detail-head">Normalized records ({result.records.length})</div>
                    {result.records.map((rec, i) => (
                      <div key={i} className="adapter-record">
                        <span className="adapter-rec-kind">{rec.kind}</span>
                        <pre className="adapter-rec-json">{JSON.stringify(rec, null, 2)}</pre>
                      </div>
                    ))}
                    {result.warnings.length > 0 && (
                      <div className="adapter-warnings">
                        {result.warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Readiness checks</p>
              <h2>Validation before dispatch</h2>
            </div>
            <span className="live-indicator">{integrationReadiness}% ready</span>
          </div>
          <div className="finding-list">
            {readinessFindings.map((finding) => (
              <article className={`finding-row ${finding.severity}`} key={finding.id}>
                <div><strong>{finding.label}</strong><span>{finding.detail}</span></div>
                <em>{finding.severity}</em>
                <small>{finding.affectedRecords.slice(0, 2).join(', ') || 'No affected records'}</small>
              </article>
            ))}
          </div>
        </section>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Source systems</p>
            <h2>Where operational data enters VELA</h2>
          </div>
          <div className="panel-actions">
            <DatabaseZap size={19} />
          </div>
        </div>
        <div className="opt-bar">
          <span className="opt-label">Health</span>
          {(['all', 'healthy', 'limited', 'delayed'] as const).map(h => (
            <button key={h} className={`opt-pill${healthFilter === h ? ' active' : ''}`}
              onClick={() => setHealthFilter(h)}>{h === 'all' ? 'All' : h}</button>
          ))}
          <span className="opt-label" style={{ marginLeft: 'auto' }}>{filteredSources.length} sources</span>
        </div>

        <div className="integration-grid">
          {filteredSources.map((source) => (
            <article className="integration-row" key={source.system}>
              <div><strong>{source.system}</strong><span>{source.category}</span></div>
              <p>{source.signals}</p>
              <span>{source.cadence}</span>
              <span>{source.adapter}</span>
              <em className={source.health}>{source.health}</em>
            </article>
          ))}
          {filteredSources.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: 12, padding: '8px 0' }}>No sources match the selected health filter.</p>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Standards map</p>
            <h2>External requirements mapped to VELA records</h2>
          </div>
          <span className="live-indicator">{integrationStandards.filter((item) => item.implementation !== 'missing').length} tracked</span>
        </div>
        <div className="standards-grid">
          {integrationStandards.map((standard) => (
            <article className={`standard-card ${standard.implementation}`} key={standard.id}>
              <div className="standard-card-head">
                <div><strong>{standard.name}</strong><span>{standard.source} · {standard.domain}</span></div>
                <em>{standard.implementation}</em>
              </div>
              <p>{standard.requirement}</p>
              <div className="standard-meta">
                <span>{standard.velaRecord}</span>
                <small>{standard.note}</small>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Control-loop SLA</p>
            <h2>Telemetry cadence, latency, ramp, and approval fit</h2>
          </div>
          <span className="live-indicator">{controlLoopChecks.filter((item) => item.status === 'ready').length} ready</span>
        </div>
        <div className="control-loop-list">
          {controlLoopChecks.map((check) => (
            <article className={`control-loop-row ${check.status}`} key={`${check.assetId}-${check.product}`}>
              <div>
                <strong>{assetById[check.assetId]?.name}</strong>
                <span>{check.product} · {check.interval}</span>
              </div>
              <b>{check.observedLoopSeconds}s</b>
              <em>{check.latencySlackSeconds >= 0 ? '+' : ''}{check.latencySlackSeconds}s slack</em>
              <small>{check.rampHeadroomMw >= 0 ? '+' : ''}{check.rampHeadroomMw} MW ramp</small>
              <p>{check.note}{check.approvalRequired ? ' Approval gate is attached.' : ''}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Source confidence</p>
            <h2>Freshness and decision impact</h2>
          </div>
        </div>
        <div className="quality-grid">
          {dataQualitySignals.map((signal) => (
            <article className={`quality-card ${signal.status}`} key={signal.label}>
              <div className="quality-card-head"><strong>{signal.label}</strong><em>{signal.freshness}</em></div>
              <span>{signal.source}</span>
              <div className="quality-meter"><span style={{ width: `${signal.confidence}%` }} /></div>
              <p>{signal.impact}</p>
            </article>
          ))}
        </div>
      </section>
    </>
  )
}

function RunLogPage() {
  const [evidenceSearch, setEvidenceSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'used' | 'watch' | 'blocked'>('all')

  const filteredRefs = useMemo(() =>
    modelRunSnapshot.inputRefs.filter(ref => {
      const matchSearch = evidenceSearch === '' ||
        ref.source.toLowerCase().includes(evidenceSearch.toLowerCase()) ||
        ref.recordType.toLowerCase().includes(evidenceSearch.toLowerCase())
      const matchStatus = statusFilter === 'all' || ref.status === statusFilter
      return matchSearch && matchStatus
    }), [evidenceSearch, statusFilter])

  const downloadReplay = () => downloadJson(`replay-${replayManifest.fingerprint}-${Date.now()}.json`, {
    fingerprint: replayManifest.fingerprint,
    generatedAt: replayManifest.generatedAt,
    modelVersion: modelRunSnapshot.modelVersion,
    replayReady: replayManifest.replayReady,
    coverage: replayManifest.coverage,
    gaps: replayManifest.gaps,
    inputRefs: modelRunSnapshot.inputRefs,
    rankedDecisions: modelRunSnapshot.rankedDecisions,
    persistenceEvents: modelRunSnapshot.persistenceEvents,
  })

  return (
    <>
      <PageHeader eyebrow="Evidence ledger" title="Run log" meta={modelRunSnapshot.modelVersion} />
      <section className="model-run-panel">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Model-run snapshot</p>
              <h2>Inputs used for the current recommendation</h2>
            </div>
            <div className="panel-actions">
              <span className="live-indicator">{modelRunSnapshot.modelVersion}</span>
              <button className="icon-btn" onClick={downloadReplay} title="Download replay package">
                <Download size={13} />
              </button>
            </div>
          </div>
          <div className="run-summary">
            <span><b>{modelRunSnapshot.readinessScore}%</b><em>Readiness</em></span>
            <span><b>{modelRunSnapshot.evidenceConfidence}%</b><em>Evidence</em></span>
            <span><b>{modelRunSnapshot.inputRefs.length}</b><em>Refs</em></span>
            <span><b>{modelRunSnapshot.rankedDecisions.length}</b><em>Candidates</em></span>
          </div>
          <p className="run-copy">{modelRunSnapshot.decisionSummary}</p>
          <div className="evidence-filter">
            <div className="search-wrap">
              <Search size={13} />
              <input
                className="evidence-search"
                placeholder="Search source or record type…"
                value={evidenceSearch}
                onChange={e => setEvidenceSearch(e.target.value)}
              />
              {evidenceSearch && (
                <button className="search-clear" onClick={() => setEvidenceSearch('')}><X size={11} /></button>
              )}
            </div>
            <div className="opt-bar" style={{ padding: 0 }}>
              {(['all', 'used', 'watch', 'blocked'] as const).map(s => (
                <button key={s} className={`opt-pill${statusFilter === s ? ' active' : ''}`}
                  onClick={() => setStatusFilter(s)}>{s === 'all' ? 'All' : s}</button>
              ))}
            </div>
          </div>
          <div className="evidence-list">
            {filteredRefs.map((ref) => (
              <article className={`evidence-row ${ref.status}`} key={`${ref.recordType}-${ref.id}`}>
                <div><strong>{ref.source}</strong><span>{ref.recordType} · {ref.id}</span></div>
                <b>{ref.confidence}%</b>
                <em>{ref.status}</em>
              </article>
            ))}
            {filteredRefs.length === 0 && (
              <p style={{ color: 'var(--muted)', fontSize: 12, padding: '8px 0' }}>No records match.</p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Ranked decisions</p>
              <h2>Persisted candidate ordering</h2>
            </div>
          </div>
          <CandidateScoreChartPanel />
          <div className="rank-list">
            {modelRunSnapshot.rankedDecisions.map((rank, index) => (
              <article className="rank-row" key={rank.candidateId}>
                <span>{index + 1}</span>
                <div><strong>{rank.product}</strong><em>{rank.action} · {rank.interval}</em></div>
                <b>{rank.score}</b>
                <small>{rank.feasibility}% feasible · {formatSignedUsd(rank.downsideRevenue)}</small>
                <p>{rank.dominantRisk}</p>
              </article>
            ))}
          </div>
          <div className="ledger-events">
            {modelRunSnapshot.persistenceEvents.map((event) => (
              <div className="ledger-event" key={`${event.timestamp}-${event.event}`}>
                <span>{event.timestamp.slice(11, 19)}Z</span>
                <strong>{event.event}</strong>
                <em>{event.detail}</em>
              </div>
            ))}
          </div>
        </section>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Replay package</p>
            <h2>Evidence coverage and fingerprint</h2>
          </div>
          <span className="live-indicator">{replayManifest.fingerprint}</span>
        </div>
        <div className="replay-summary">
          <span><b>{replayManifest.replayReady ? 'Ready' : 'Held'}</b><em>Replay status</em></span>
          <span><b>{replayManifest.coverage.length}</b><em>Record groups</em></span>
          <span><b>{replayManifest.gaps.length}</b><em>Gaps</em></span>
          <span><b>{replayManifest.generatedAt.slice(11, 19)}Z</b><em>Generated</em></span>
        </div>
        <div className="replay-layout">
          <div className="replay-coverage">
            {replayManifest.coverage.map((item) => (
              <article className="replay-row" key={item.recordType}>
                <div><strong>{item.recordType}</strong><span>{item.used} used · {item.warnings} watch · {item.blocked} blocked</span></div>
                <b>{item.confidence}%</b>
                <div className="bar-track"><span style={{ width: `${item.confidence}%` }} /></div>
              </article>
            ))}
          </div>
          <div className="replay-gaps">
            {replayManifest.gaps.map((gap) => (
              <article className={`replay-gap ${gap.severity}`} key={gap.id}>
                <strong>{gap.label}</strong>
                <p>{gap.detail}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Operator overrides</p>
            <h2>Manual limits attached to this run</h2>
          </div>
          <span className="live-indicator">{overrideImpacts.length} records</span>
        </div>
        <div className="override-grid">
          {overrideImpacts.map((impact) => (
            <article className={`override-row ${impact.approvalImpact}`} key={impact.overrideId}>
              <div><strong>{impact.label}</strong><span>{impact.rationale}</span></div>
              <b>{impact.targetMwBefore} {'->'} {impact.targetMwAfter} MW</b>
              <em>{impact.scoreDelta > 0 ? '+' : ''}{impact.scoreDelta}</em>
              <small>{impact.status} · {impact.approvalImpact}</small>
            </article>
          ))}
        </div>
      </section>
    </>
  )
}

type Density = 'compact' | 'comfortable' | 'spacious'

function App() {
  const [activePage, setActivePage] = useState<PageId>('command')
  const [selectedAssetId, setSelectedAssetId] = useState(assets[0].id)
  const [selectedDecisionId, setSelectedDecisionId] = useState(topDecision.id)
  const [density, setDensity] = useState<Density>('comfortable')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [analyticsCollapsed, setAnalyticsCollapsed] = useState(false)
  const settingsRef = useRef<HTMLDivElement>(null)

  const secondaryBadge: Partial<Record<PageId, { text: string; warn?: boolean }>> = {
    coordination: coordinationReadiness.blockedCount > 0
      ? { text: `${coordinationReadiness.blockedCount} blocked`, warn: true }
      : { text: `${coordinationReadiness.score}%` },
    model: { text: `${decisionCandidates.length} candidates` },
    integrations: coverage.warningCount > 0
      ? { text: `${coverage.warningCount} warnings`, warn: true }
      : { text: `${coverage.confidence}% conf` },
    runlog: { text: modelRunSnapshot.modelVersion },
  }

  const selectedAsset = useMemo(
    () => assets.find((asset) => asset.id === selectedAssetId) ?? assets[0],
    [selectedAssetId],
  )
  const selectedDecision = useMemo(
    () => decisionCandidates.find((decision) => decision.id === selectedDecisionId) ?? topDecision,
    [selectedDecisionId],
  )
  const activeLabel = pageItems.find((item) => item.id === activePage)?.label ?? 'Command'

  useEffect(() => {
    if (!settingsOpen) return
    const handler = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) setSettingsOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [settingsOpen])

  return (
    <main className={`vela-shell${density !== 'comfortable' ? ` density-${density}` : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <svg width="26" height="24" viewBox="418 48 620 544" fillRule="evenodd" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><path id="velaMarkApp" d="M 962 56 L 958 56 L 949 62 L 938 67 L 931 72 L 926 74 L 924 76 L 917 79 L 915 81 L 900 89 L 895 93 L 887 97 L 847 123 L 844 126 L 831 134 L 816 146 L 812 148 L 741 204 L 734 211 L 727 216 L 719 224 L 694 245 L 645 292 L 644 292 L 605 332 L 605 333 L 565 375 L 558 384 L 549 393 L 542 403 L 536 409 L 532 415 L 511 440 L 509 444 L 504 449 L 492 465 L 486 475 L 483 478 L 482 481 L 479 484 L 472 496 L 464 507 L 463 510 L 459 515 L 457 520 L 455 522 L 449 534 L 443 543 L 439 552 L 437 554 L 423 582 L 423 585 L 436 580 L 442 579 L 445 577 L 448 577 L 464 571 L 467 571 L 470 569 L 473 569 L 480 566 L 494 563 L 501 560 L 508 559 L 512 557 L 517 557 L 524 554 L 528 554 L 540 550 L 545 550 L 553 547 L 559 547 L 568 544 L 573 544 L 577 542 L 589 541 L 598 538 L 609 537 L 614 535 L 627 534 L 628 533 L 637 532 L 638 531 L 649 531 L 650 530 L 660 529 L 661 528 L 677 528 L 678 527 L 684 527 L 685 526 L 691 526 L 692 525 L 722 525 L 722 522 L 719 515 L 719 511 L 717 507 L 717 492 L 716 491 L 716 485 L 715 484 L 715 474 L 717 468 L 717 455 L 718 454 L 718 449 L 720 445 L 720 439 L 721 438 L 725 419 L 727 415 L 727 412 L 729 408 L 729 405 L 731 402 L 731 399 L 736 388 L 736 385 L 738 382 L 738 380 L 740 377 L 744 365 L 747 360 L 748 355 L 753 346 L 756 337 L 764 321 L 766 319 L 766 317 L 768 315 L 780 291 L 785 284 L 788 277 L 795 267 L 800 257 L 804 252 L 806 247 L 831 209 L 854 178 L 876 151 L 879 146 L 902 119 L 912 109 L 918 101 L 943 76 L 943 75 L 949 69 L 950 69 L 952 66 L 962 58 Z M 883 189 L 856 225 L 851 234 L 838 253 L 836 258 L 826 274 L 823 281 L 821 283 L 804 318 L 802 325 L 799 330 L 799 332 L 796 337 L 795 342 L 789 355 L 787 363 L 785 366 L 783 374 L 781 377 L 781 380 L 779 383 L 779 386 L 777 389 L 776 395 L 773 402 L 772 409 L 770 413 L 770 417 L 767 425 L 767 429 L 765 433 L 764 443 L 762 447 L 762 454 L 761 455 L 761 460 L 760 461 L 759 473 L 787 491 L 802 502 L 827 523 L 849 545 L 852 546 L 858 546 L 859 547 L 865 547 L 866 548 L 871 548 L 876 550 L 883 550 L 892 553 L 903 554 L 911 557 L 917 557 L 921 559 L 932 560 L 940 563 L 945 563 L 953 566 L 958 566 L 961 568 L 966 568 L 969 570 L 974 570 L 980 573 L 984 573 L 987 575 L 991 575 L 998 578 L 1005 579 L 1028 587 L 1033 587 L 1033 585 L 1030 584 L 1018 576 L 978 546 L 941 510 L 925 489 L 915 474 L 913 469 L 909 464 L 894 435 L 894 433 L 892 431 L 891 426 L 887 418 L 886 413 L 884 410 L 881 401 L 881 398 L 879 395 L 879 391 L 876 384 L 876 381 L 874 376 L 874 372 L 871 364 L 871 358 L 870 357 L 870 352 L 869 351 L 869 346 L 868 345 L 868 317 L 867 316 L 868 263 L 870 258 L 871 243 L 872 242 L 872 238 L 874 233 L 874 227 L 875 226 L 875 223 L 878 214 L 878 210 L 882 199 L 882 196 L 884 193 L 884 189 Z"/><clipPath id="velaClipApp"><use href="#velaMarkApp"/></clipPath><linearGradient id="velaBlueApp" x1="0%" y1="90%" x2="70%" y2="10%"><stop offset="0%" stop-color="#258AE8"/><stop offset="100%" stop-color="#0C6DCC"/></linearGradient></defs><use href="#velaMarkApp" fill="url(#velaBlueApp)"/><g clipPath="url(#velaClipApp)"><polygon points="420,586 650,290 728,527" fill="#2F8DE2"/><polygon points="650,290 966,56 792,372" fill="#0A67C1"/><polygon points="650,290 792,372 804,468" fill="#0A4198"/><polygon points="420,586 728,527 804,468" fill="#1768D9"/><polygon points="792,372 888,188 882,438" fill="#7AB8F4"/><polygon points="882,438 1036,586 804,468" fill="#2577D9"/><polygon points="804,468 1036,586 728,527" fill="#083891"/><polygon points="882,438 888,188 966,320" fill="#4B95F0" opacity="0.65"/></g></svg>
          <div>
            <strong>vela</strong>
            <span>Virtual energy operations</span>
          </div>
        </div>

        <nav aria-label="Primary">
          {primaryItems.map((item) => {
            const Icon = item.icon
            return (
              <button
                className={activePage === item.id ? 'active' : ''}
                key={item.id}
                type="button"
                onClick={() => setActivePage(item.id)}
              >
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            )
          })}

          <div className="nav-section">
            <span className="nav-section-label">Analytics</span>
            <button
              className="nav-section-toggle"
              type="button"
              title={analyticsCollapsed ? 'Expand' : 'Collapse'}
              onClick={() => setAnalyticsCollapsed(c => !c)}
            >
              <ChevronDown size={11} style={{ transform: analyticsCollapsed ? 'rotate(-90deg)' : 'none', transition: 'transform .2s' }} />
            </button>
          </div>

          {!analyticsCollapsed && secondaryItems.map((item) => {
            const Icon = item.icon
            const badge = secondaryBadge[item.id]
            return (
              <button
                className={activePage === item.id ? 'active' : ''}
                key={item.id}
                type="button"
                onClick={() => setActivePage(item.id)}
              >
                <Icon size={17} />
                <span className="nav-item-label">{item.label}</span>
                {badge && (
                  <span className={`nav-badge${badge.warn ? ' warn' : ''}`}>{badge.text}</span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="operator-card">
          <p className="label">Control mode</p>
          <strong>Operator approval</strong>
          <span>Advisory only. Dispatch stays blocked until gates, overrides, and source quality are reviewed.</span>
        </div>
      </aside>

      <section className="workspace" aria-label={activeLabel}>
        {activePage === 'command' && (
          <CommandPage
            selectedDecision={selectedDecision}
            setSelectedDecisionId={setSelectedDecisionId}
            goToPage={setActivePage}
          />
        )}
        {activePage === 'portfolio' && (
          <PortfolioPage selectedAsset={selectedAsset} setSelectedAssetId={setSelectedAssetId} />
        )}
        {activePage === 'markets' && <MarketsPage />}
        {activePage === 'coordination' && <CoordinationPage />}
        {activePage === 'model' && <ModelPage selectedDecision={selectedDecision} />}
        {activePage === 'integrations' && <IntegrationsPage />}
        {activePage === 'runlog' && <RunLogPage />}
      </section>

      {/* Floating settings */}
      <div ref={settingsRef}>
        {settingsOpen && (
          <div className="settings-panel">
            <div className="settings-header">
              <strong>Display settings</strong>
              <button className="icon-btn" onClick={() => setSettingsOpen(false)}><X size={13} /></button>
            </div>
            <hr className="settings-divider" />
            <div className="settings-section">
              <div className="settings-title">Density</div>
              <div className="settings-row">
                {(['compact', 'comfortable', 'spacious'] as Density[]).map(d => (
                  <button key={d} className={`opt-pill${density === d ? ' active' : ''}`} onClick={() => setDensity(d)}>
                    {d.charAt(0).toUpperCase() + d.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <div className="settings-section">
              <div className="settings-title">Charts</div>
              <div className="settings-row">
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>Use the ↓ button on each chart panel to collapse it. Click legend items to toggle series.</span>
              </div>
            </div>
            <div className="settings-section">
              <div className="settings-title">KPI cards</div>
              <div className="settings-row">
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>Click any KPI card to swap the metric shown.</span>
              </div>
            </div>
          </div>
        )}
        <button className={`settings-fab${settingsOpen ? ' open' : ''}`} onClick={() => setSettingsOpen(o => !o)} title="Display settings">
          <Settings size={18} />
        </button>
      </div>
    </main>
  )
}

export default App

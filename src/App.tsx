import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  BatteryCharging,
  Building2,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  CloudSun,
  DatabaseZap,
  FileText,
  Gauge,
  LineChart,
  Network,
  ShieldCheck,
  SlidersHorizontal,
  SunMedium,
  Zap,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
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

const pageItems: Array<{ id: PageId; label: string; icon: typeof Network }> = [
  { id: 'command', label: 'Command', icon: Network },
  { id: 'portfolio', label: 'Portfolio', icon: DatabaseZap },
  { id: 'markets', label: 'Markets', icon: LineChart },
  { id: 'coordination', label: 'Coordination', icon: ClipboardCheck },
  { id: 'model', label: 'Model', icon: SlidersHorizontal },
  { id: 'integrations', label: 'Integrations', icon: ShieldCheck },
  { id: 'runlog', label: 'Run log', icon: FileText },
]

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

const formatUsd = (value: number) =>
  new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 0,
    style: 'currency',
    currency: 'USD',
  }).format(value)

const formatSignedUsd = (value: number) => `${value < 0 ? '-' : ''}${formatUsd(Math.abs(value))}`

// ---- Chart style constants ----
const AX = { fontSize: 10, fill: '#68736f' } as const
const GRID = { stroke: '#dbe2de' }
const TIP_STYLE = { fontSize: 12, borderRadius: 6, border: '1px solid #dbe2de', background: '#fff' }

function LmpChartPanel() {
  return (
    <section className="panel chart-panel">
      <div className="panel-head">
        <div>
          <p className="label">LMP price curve</p>
          <h2>Day-ahead vs real-time — 24-hour window</h2>
        </div>
        <span className="live-indicator">${_baseLmp}/MWh base</span>
      </div>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={lmpSeries} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="daGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#235a91" stopOpacity={0.13} />
                <stop offset="95%" stopColor="#235a91" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
            <XAxis dataKey="hour" tick={AX} tickLine={false} axisLine={GRID} interval={3} />
            <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} width={38} />
            <Tooltip contentStyle={TIP_STYLE} formatter={(v: unknown, n?: string | number) => [`$${v as number}/MWh`, n === 'da' ? 'DA price' : 'RT price'] as [string, string]} />
            <Area type="monotone" dataKey="da" stroke="#235a91" strokeWidth={2} fill="url(#daGrad)" name="da" />
            <Area type="monotone" dataKey="rt" stroke="#9b6515" strokeWidth={1.5} strokeDasharray="5 3" fill="none" name="rt" />
          </AreaChart>
        </ResponsiveContainer>
        <div className="chart-legend">
          <span className="legend-item legend-da">Day-ahead</span>
          <span className="legend-item legend-rt">Real-time</span>
        </div>
      </div>
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
            <Bar dataKey="available" stackId="cap" fill="#167a55" name="available" />
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
                <Cell key={i} fill={entry.amount >= 0 ? '#167a55' : '#a23b35'} fillOpacity={0.85} />
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
              <Cell key={i} fill={entry.revenue >= 0 ? '#167a55' : '#a23b35'} fillOpacity={0.82} />
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
              <Cell key={i} fill={entry.delta >= 0 ? '#167a55' : '#a23b35'} fillOpacity={0.85} />
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
              <Cell key={i} fill={entry.score >= 80 ? '#167a55' : entry.score >= 65 ? '#9b6515' : '#a23b35'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function KpiCard({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string
  value: string
  detail: string
  icon: typeof Network
}) {
  return (
    <section className="metric-card">
      <div className="metric-icon">
        <Icon size={18} />
      </div>
      <div>
        <p className="label">{label}</p>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
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
  return (
    <>
      <PageHeader eyebrow="CAISO aggregate portfolio" title="Command" meta={`${stats.constrained} constrained sources`} />

      <section className="metrics-grid">
        <KpiCard icon={Network} label="Portfolio MW" value={`${stats.capacity} MW`} detail="Registered capacity across five resource classes" />
        <KpiCard icon={Gauge} label="Available" value={`${stats.available} MW`} detail={`${stats.utilization}% dispatchable this interval`} />
        <KpiCard icon={CircleDollarSign} label="Forecast net" value={formatUsd(forecastRevenue)} detail="Current recommended dispatch window" />
        <KpiCard icon={AlertTriangle} label="Readiness" value={`${integrationReadiness}%`} detail={`${coverage.adaptersOnline} adapters online, ${coverage.warningCount} warnings`} />
      </section>

      <LmpChartPanel />

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
            <div className="confidence-dial">
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
          </div>
          <div className="queue-list">
            {decisionCandidates.map((decision) => (
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
          </div>
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
  const assetTelemetry = telemetrySamples.filter((sample) => sample.assetId === selectedAsset.id)
  const assetEnvelopes = flexibilityEnvelopes.filter((envelope) => envelope.assetId === selectedAsset.id)
  const assetPolicies = constraintPolicies.filter((policy) => policy.assetId === selectedAsset.id)
  const AssetIcon = assetIcons[selectedAsset.type]

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
          <div className="asset-table">
            <div className="asset-table-head">
              <span>Asset</span><span>Region</span><span>MW</span><span>Ready</span><span>Telemetry</span>
            </div>
            {assets.map((asset) => {
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
          <div className="compact-list">
            {assetEnvelopes.map((envelope) => (
              <div className="compact-row" key={`${envelope.assetId}-${envelope.interval}`}>
                <div><strong>{envelope.interval}</strong><span>{envelope.confidence}% envelope confidence</span></div>
                <b>{envelope.maxExportMw} MW</b>
                <em>{envelope.rampRateMwPerMinute} MW/min</em>
                <small>{envelope.controlLatencySeconds + envelope.telemetryLatencySeconds}s loop</small>
              </div>
            ))}
            {assetTelemetry.map((sample) => (
              <div className="telemetry-chip wide" key={`${sample.assetId}-${sample.timestamp}`}>
                <strong>{sample.source}</strong>
                <span>{sample.timestamp.slice(11, 19)}Z</span>
                <b>{sample.realPowerMw} MW</b>
                <em className={sample.quality}>{sample.quality}</em>
              </div>
            ))}
            {assetPolicies.map((policy) => (
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
            <CloudSun size={19} />
          </div>
          <div className="market-table">
            {marketSignals.map((signal) => (
              <article className="market-row" key={`${signal.product}-${signal.region}`}>
                <div><strong>{signal.product}</strong><span>{signal.region}</span></div>
                <div><strong>${signal.price}/MWh</strong><span>{signal.confidence}% confidence</span></div>
                <div><strong>{signal.gridCondition}</strong><span>Grid</span></div>
                <div><strong>{signal.weatherSignal}</strong><span>{signal.obligationMw} MW obligation</span></div>
                <span className={`risk ${signal.risk}`}>{signal.risk}</span>
              </article>
            ))}
          </div>
        </section>

        <section className="panel settlement-panel">
          <div className="panel-head">
            <div>
              <p className="label">Settlement view</p>
              <h2>Expected award and margin</h2>
            </div>
            <span className="live-indicator">{formatSignedUsd(settlementProjection.netMargin)}</span>
          </div>
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
        </section>
      </section>

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
            <p>
              VELA can recommend a bid, but approval should stay gated until resource eligibility,
              telemetry, utility review, and customer constraints are all replayable.
            </p>
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
                <article className="owner-card" key={owner}>
                  <strong>{owner}</strong>
                  <span>{owned.length} checkpoints</span>
                  <em>{blocked > 0 ? `${blocked} blocked` : 'No blocks'}</em>
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
        </div>
        <div className="coordination-list">
          {coordinationReadiness.checkpoints.map((checkpoint) => (
            <article className={`coordination-row ${checkpoint.status}`} key={checkpoint.id}>
              <div>
                <strong>{checkpoint.label}</strong>
                <span>{checkpoint.requirement}</span>
              </div>
              <b>{checkpoint.owner}</b>
              <em>{checkpoint.dueBy}</em>
              <small className={`risk ${checkpoint.risk}`}>{checkpoint.risk}</small>
              <p>{checkpoint.evidence}</p>
            </article>
          ))}
        </div>
      </section>
    </>
  )
}

function ModelPage({ selectedDecision }: { selectedDecision: DecisionCandidate }) {
  return (
    <>
      <PageHeader eyebrow="Optimization workbench" title="Model" meta={selectedDecision.robustModel ? `${selectedDecision.robustModel.scenarios.length} scenarios` : 'No robust model'} />
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
                <article className={`sensitivity-card ${item.scoreDelta < 0 ? 'negative' : 'positive'}`} key={item.id}>
                  <div className="sensitivity-head">
                    <div><strong>{item.label}</strong><span>{item.parameter} {item.direction === 'up' ? '+' : '-'}{item.deltaPercent}%</span></div>
                    <b>{item.scoreDelta > 0 ? '+' : ''}{item.scoreDelta}</b>
                  </div>
                  <div className="sensitivity-values">
                    <span><b>{formatSignedUsd(item.expectedRevenueDelta)}</b><em>Revenue</em></span>
                    <span><b>{item.feasibilityDelta > 0 ? '+' : ''}{item.feasibilityDelta}</b><em>Feasibility</em></span>
                  </div>
                  <p>{item.interpretation}</p>
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

function IntegrationsPage() {
  return (
    <>
      <PageHeader eyebrow="Data fabric" title="Integrations" meta={`${coverage.confidence}% adapter confidence`} />
      <section className="integration-layout">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Adapter normalization</p>
              <h2>Vendor payloads mapped into canonical records</h2>
            </div>
            <span className="live-indicator">{coverage.confidence}% confidence</span>
          </div>
          <div className="adapter-summary">
            <span><b>{coverage.recordCounts.telemetry}</b><em>Telemetry</em></span>
            <span><b>{coverage.recordCounts.flexibility}</b><em>Flex</em></span>
            <span><b>{coverage.recordCounts.market}</b><em>Market</em></span>
            <span><b>{coverage.recordCounts.constraint}</b><em>Rules</em></span>
          </div>
          <div className="adapter-list">
            {adapterResults.map((result) => (
              <article className="adapter-row" key={result.payloadId}>
                <div><strong>{result.vendor}</strong><span>{result.adapter} · {result.payloadId}</span></div>
                <b>{result.records.map((record) => record.kind).join(', ')}</b>
                <em>{result.confidence}%</em>
                <small>{result.warnings[0] ?? 'Normalized without warnings'}</small>
              </article>
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

      <section className="panel integration-panel">
        <div className="panel-head">
          <div>
            <p className="label">Source systems</p>
            <h2>Where operational data enters VELA</h2>
          </div>
          <DatabaseZap size={19} />
        </div>
        <div className="integration-grid">
          {integrationSources.map((source) => (
            <article className="integration-row" key={source.system}>
              <div><strong>{source.system}</strong><span>{source.category}</span></div>
              <p>{source.signals}</p>
              <span>{source.cadence}</span>
              <span>{source.adapter}</span>
              <em className={source.health}>{source.health}</em>
            </article>
          ))}
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
            <span className="live-indicator">{modelRunSnapshot.modelVersion}</span>
          </div>
          <div className="run-summary">
            <span><b>{modelRunSnapshot.readinessScore}%</b><em>Readiness</em></span>
            <span><b>{modelRunSnapshot.evidenceConfidence}%</b><em>Evidence</em></span>
            <span><b>{modelRunSnapshot.inputRefs.length}</b><em>Refs</em></span>
            <span><b>{modelRunSnapshot.rankedDecisions.length}</b><em>Candidates</em></span>
          </div>
          <p className="run-copy">{modelRunSnapshot.decisionSummary}</p>
          <div className="evidence-list">
            {modelRunSnapshot.inputRefs.map((ref) => (
              <article className={`evidence-row ${ref.status}`} key={`${ref.recordType}-${ref.id}`}>
                <div><strong>{ref.source}</strong><span>{ref.recordType} · {ref.id}</span></div>
                <b>{ref.confidence}%</b>
                <em>{ref.status}</em>
              </article>
            ))}
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

function App() {
  const [activePage, setActivePage] = useState<PageId>('command')
  const [selectedAssetId, setSelectedAssetId] = useState(assets[0].id)
  const [selectedDecisionId, setSelectedDecisionId] = useState(topDecision.id)

  const selectedAsset = useMemo(
    () => assets.find((asset) => asset.id === selectedAssetId) ?? assets[0],
    [selectedAssetId],
  )
  const selectedDecision = useMemo(
    () => decisionCandidates.find((decision) => decision.id === selectedDecisionId) ?? topDecision,
    [selectedDecisionId],
  )
  const activeLabel = pageItems.find((item) => item.id === activePage)?.label ?? 'Command'

  return (
    <main className="vela-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">V</div>
          <div>
            <strong>VELA</strong>
            <span>Virtual energy operations</span>
          </div>
        </div>

        <nav aria-label="Primary">
          {pageItems.map((item) => {
            const Icon = item.icon
            return (
              <button
                className={activePage === item.id ? 'active' : ''}
                key={item.id}
                type="button"
                onClick={() => setActivePage(item.id)}
              >
                <Icon size={17} /> <span>{item.label}</span>
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
    </main>
  )
}

export default App

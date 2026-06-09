import { useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BatteryCharging,
  CheckCircle2,
  ChevronRight,
  Download,
  Lightbulb,
  Loader2,
  ShieldCheck,
  SunMedium,
  TrendingUp,
  Wind,
  Zap,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DemoAssetIn, DemoAssetType, ObligationIn } from '../types/demo'
import { startDemoFleet, startDispatch } from '../services/demoApi'
import type {
  ParsedAsset,
  PortfolioReport,
  ReadinessFinding,
  StreamCategory,
} from '../backend/onboardAnalysis'

type PageId = string

const ASSET_ICON: Record<DemoAssetType, typeof BatteryCharging> = {
  BESS: BatteryCharging,
  Solar: SunMedium,
  Wind: Wind,
  EV_Fleet: Zap,
  Flex_Load: Activity,
}

const CATEGORY_COLOR: Record<StreamCategory, string> = {
  capacity: '#1A74D8',
  energy: '#d97706',
  ancillary: '#235a91',
  flexibility: '#7c5cd0',
}
const CATEGORY_LABEL: Record<StreamCategory, string> = {
  capacity: 'Capacity',
  energy: 'Energy',
  ancillary: 'Ancillary services',
  flexibility: 'Flexibility / DR',
}

const usd = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
const usdc = (n: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(n)

const AX = { fontSize: 10, fill: '#68736f' } as const
const GRID = { stroke: '#dbe2de' }
const TIP = { fontSize: 12, borderRadius: 6, border: '1px solid #dbe2de', background: '#fff' }

export function ReportStage({
  report,
  parsed,
  onBack,
  goToPage,
}: {
  report: PortfolioReport
  parsed: ParsedAsset[]
  onBack: () => void
  goToPage: (id: PageId) => void
}) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [activating, setActivating] = useState(false)
  const [activateNote, setActivateNote] = useState<string | null>(null)

  const stackData = useMemo(
    () =>
      report.productSummary.map((p) => ({
        name: p.product,
        captured: p.annualUsd - p.untappedUsd,
        untapped: p.untappedUsd,
        category: p.category,
      })),
    [report],
  )

  const downloadReport = () => {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vela-assessment-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const downloadSummary = () => {
    const lines = [
      `VELA — VPP REVENUE & READINESS ASSESSMENT`,
      `Generated ${new Date(report.generatedAt).toLocaleString()}`,
      ``,
      `Portfolio: ${report.assetCount} assets · ${report.totalMw} MW · ${report.totalMwh} MWh · ${report.isos.join(', ')}`,
      ``,
      `Projected annual net revenue : ${usd(report.annualNetUsd)}  (p10 ${usd(report.p10Usd)} — p90 ${usd(report.p90Usd)})`,
      `Estimated today (single program): ${usd(report.annualStatusQuoUsd)}`,
      `Uplift with Vela            : ${usd(report.upliftUsd)}  (+${report.upliftPct}%)`,
      `Revenue per MW per year     : ${usd(report.perMwYr)}`,
      `Market-readiness score      : ${report.readinessScore}/100`,
      `Estimated time to enroll    : ~${report.enrollmentTimelineWeeks} weeks`,
      ``,
      `REVENUE BY MARKET PRODUCT`,
      ...report.productSummary.map(
        (p) =>
          `  ${p.product.padEnd(24)} ${usd(p.annualUsd).padStart(14)}   untapped ${usd(p.untappedUsd)}  (${p.eligibleAssets} assets / ${p.eligibleMw} MW)`,
      ),
      ``,
      `READINESS FINDINGS`,
      ...report.findings.map((f) => `  [${f.status.toUpperCase().padEnd(4)}] ${f.label} — ${f.detail}`),
      ``,
      `RECOMMENDATIONS`,
      ...report.recommendations.map(
        (r) => `  (${r.priority}) ${r.title}${r.impactUsd ? ` — +${usd(r.impactUsd)}/yr` : ''}\n      ${r.detail}`,
      ),
      ``,
      `RISK FLAGS`,
      ...report.riskFlags.map((r) => `  [${r.severity}] ${r.label} — ${r.detail}`),
      ``,
      `Estimates are advisory and model-based. Actual market revenue depends on clearing prices, enrollment, and dispatch performance.`,
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `vela-assessment-${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const activate = async () => {
    setActivating(true)
    setActivateNote(null)
    try {
      const assets: DemoAssetIn[] = parsed.map((a) => ({
        asset_id: a.asset_id,
        asset_type: a.asset_type,
        rated_mw: a.rated_mw,
        rated_mwh: a.rated_mwh,
        chemistry: a.chemistry,
      }))
      await startDemoFleet(assets)
      const obligations: ObligationIn[] = [
        {
          obligation_type: 'capacity',
          committed_mw: Math.round(report.totalMw * 0.6),
          start_hour: 16,
          end_hour: 20,
          penalty_linear_per_mwh: 1000,
        },
      ]
      await startDispatch(DEMO_DISPATCH_INTERVAL, obligations)
      goToPage('fleet')
    } catch (err) {
      setActivateNote(
        `Live optimizer not reachable (${err instanceof Error ? err.message.slice(0, 50) : 'offline'}). The assessment above is complete — start the backend to run live dispatch.`,
      )
      setActivating(false)
    }
  }

  return (
    <>
      {/* ── Hero: the number ── */}
      <section className="panel onboard-hero">
        <div className="onboard-hero-main">
          <p className="label">Projected annual net revenue · {report.isos.join(' · ')}</p>
          <div className="onboard-hero-figure">{usd(report.annualNetUsd)}</div>
          <div className="onboard-range">
            <span className="onboard-range-label">p10 {usdc(report.p10Usd)}</span>
            <div className="onboard-range-track">
              <span
                className="onboard-range-fill"
                style={{
                  left: '8%',
                  right: '8%',
                }}
              />
              <span className="onboard-range-marker" style={{ left: '50%' }} />
            </div>
            <span className="onboard-range-label">p90 {usdc(report.p90Usd)}</span>
          </div>
          <p className="onboard-hero-sub">
            Across {report.assetCount} assets ({report.totalMw} MW · {report.totalMwh} MWh). Net of{' '}
            {usd(report.annualDegradationUsd)} modeled battery degradation. {usd(report.perMwYr)} per MW per year.
          </p>
        </div>
        <div className="onboard-hero-uplift">
          <div className="onboard-uplift-card">
            <TrendingUp size={18} />
            <strong>+{report.upliftPct}%</strong>
            <span>{usd(report.upliftUsd)}/yr uplift vs. a single-program baseline of {usd(report.annualStatusQuoUsd)}</span>
          </div>
          <div className="onboard-readiness-card">
            <div
              className="confidence-dial"
              style={{
                background: `radial-gradient(circle at center, #fff 54%, transparent 55%), conic-gradient(var(--green) 0 ${report.readinessScore}%, var(--surface-2) ${report.readinessScore}% 100%)`,
              }}
            >
              <span>{report.readinessScore}</span>
              <small>ready</small>
            </div>
            <span>Market readiness · ~{report.enrollmentTimelineWeeks} wks to enroll</span>
          </div>
        </div>
      </section>

      {/* ── Status quo vs Vela comparison ── */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Where the uplift comes from</p>
            <h2>Today's single program vs. Vela's stacked optimization</h2>
          </div>
          <span className="live-indicator">{report.productSummary.length} products stacked</span>
        </div>
        <div className="onboard-compare">
          <div className="onboard-compare-col">
            <p className="label">Status quo</p>
            <strong>{usd(report.annualStatusQuoUsd)}</strong>
            <span>Typically one channel — a single capacity or energy contract, partially monetized.</span>
            <div className="onboard-compare-bar">
              <span
                className="onboard-compare-fill quo"
                style={{ width: `${Math.max(6, (report.annualStatusQuoUsd / report.annualNetUsd) * 100)}%` }}
              />
            </div>
          </div>
          <div className="onboard-compare-arrow">
            <ArrowRight size={18} />
          </div>
          <div className="onboard-compare-col">
            <p className="label">With Vela</p>
            <strong className="text-green">{usd(report.annualNetUsd)}</strong>
            <span>Every eligible product co-optimized against degradation and obligations.</span>
            <div className="onboard-compare-bar">
              <span className="onboard-compare-fill vela" style={{ width: '100%' }} />
            </div>
          </div>
        </div>
      </section>

      {/* ── Revenue stack by product ── */}
      <section className="panel chart-panel">
        <div className="panel-head">
          <div>
            <p className="label">Revenue stack</p>
            <h2>Annual revenue by market product</h2>
          </div>
          <div className="onboard-legend">
            <span><i style={{ background: 'var(--strong-line)' }} /> Captured today</span>
            <span><i style={{ background: 'var(--green)' }} /> Untapped with Vela</span>
          </div>
        </div>
        <div className="chart-area">
          <ResponsiveContainer width="100%" height={Math.max(180, stackData.length * 42)}>
            <BarChart data={stackData} layout="vertical" margin={{ top: 4, right: 28, bottom: 0, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" {...GRID} horizontal={false} />
              <XAxis type="number" tick={AX} tickLine={false} axisLine={GRID} tickFormatter={(v) => usdc(v as number)} />
              <YAxis type="category" dataKey="name" tick={{ ...AX, fontSize: 10 }} tickLine={false} axisLine={false} width={150} />
              <Tooltip
                contentStyle={TIP}
                formatter={(v: unknown, n?: string | number) =>
                  [usd(v as number), n === 'captured' ? 'Captured today' : 'Untapped'] as [string, string]
                }
              />
              <Bar dataKey="captured" stackId="r" fill="var(--strong-line)" />
              <Bar dataKey="untapped" stackId="r" radius={[0, 3, 3, 0]}>
                {stackData.map((d, i) => (
                  <Cell key={i} fill={CATEGORY_COLOR[d.category]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="onboard-product-table">
          <div className="onboard-product-head">
            <span>Product</span>
            <span>Category</span>
            <span>Eligible</span>
            <span>Annual</span>
            <span>Untapped</span>
          </div>
          {report.productSummary.map((p) => (
            <div className="onboard-product-row" key={p.product}>
              <strong>{p.product}</strong>
              <em className="onboard-cat" style={{ color: CATEGORY_COLOR[p.category] }}>
                {CATEGORY_LABEL[p.category]}
              </em>
              <span>{p.eligibleMw} MW · {p.eligibleAssets}</span>
              <b>{usd(p.annualUsd)}</b>
              <span className="text-green">{usd(p.untappedUsd)}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── 12-month ramp ── */}
      <section className="panel chart-panel">
        <div className="panel-head">
          <div>
            <p className="label">First-year ramp</p>
            <h2>Cumulative net revenue as enrollments clear</h2>
          </div>
          <span className="live-indicator">{usd(report.monthly.at(-1)?.cumulativeVela ?? 0)} yr 1</span>
        </div>
        <div className="chart-area">
          <div className="chart-legend">
            <span className="legend-item" style={{ color: 'var(--green)' }}>With Vela (ramping)</span>
            <span className="legend-item" style={{ color: 'var(--muted)' }}>Status quo</span>
          </div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={report.monthly} margin={{ top: 4, right: 16, bottom: 0, left: 4 }}>
              <defs>
                <linearGradient id="gVela" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1A74D8" stopOpacity={0.22} />
                  <stop offset="95%" stopColor="#1A74D8" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
              <XAxis dataKey="month" tick={AX} tickLine={false} axisLine={GRID} />
              <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={(v) => usdc(v as number)} width={48} />
              <Tooltip
                contentStyle={TIP}
                formatter={(v: unknown, n?: string | number) =>
                  [usd(v as number), n === 'cumulativeVela' ? 'With Vela' : 'Status quo'] as [string, string]
                }
              />
              <Area type="monotone" dataKey="cumulativeStatusQuo" stroke="#9aa6a1" strokeWidth={1.5} fill="none" strokeDasharray="4 3" />
              <Area type="monotone" dataKey="cumulativeVela" stroke="#1A74D8" strokeWidth={2} fill="url(#gVela)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ── Per-asset breakdown ── */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Asset-level detail</p>
            <h2>Net revenue and stacking by resource</h2>
          </div>
          <span className="live-indicator">{report.assessments.length} assets</span>
        </div>
        <div className="onboard-asset-list">
          {report.assessments.map((a) => {
            const Icon = ASSET_ICON[a.asset.asset_type]
            const open = expanded === a.asset.asset_id
            const maxStream = Math.max(...a.streams.map((s) => s.annualUsd), 1)
            return (
              <div key={a.asset.asset_id}>
                <button
                  className={`onboard-asset-row${open ? ' open' : ''}`}
                  onClick={() => setExpanded(open ? null : a.asset.asset_id)}
                >
                  <ChevronRight size={14} className={`cp-chevron${open ? ' open' : ''}`} />
                  <span className="onboard-asset-name">
                    <Icon size={16} color="var(--green)" />
                    <span>
                      <strong>{a.asset.asset_id}</strong>
                      <em>
                        {a.asset.asset_type.replace('_', ' ')} · {a.asset.rated_mw} MW
                        {a.asset.rated_mwh ? ` · ${a.asset.rated_mwh} MWh` : ''} · {a.asset.region}
                      </em>
                    </span>
                  </span>
                  <span className="onboard-asset-figures">
                    <b>{usd(a.netAnnualUsd)}</b>
                    <em>{a.streams.length} streams</em>
                  </span>
                  <span className={`conf-pill ${a.readiness >= 85 ? 'good' : a.readiness >= 70 ? 'mid' : 'low'}`}>
                    {a.readiness}
                  </span>
                </button>
                {open && (
                  <div className="onboard-asset-detail">
                    {a.streams.map((s) => (
                      <div className="onboard-stream-row" key={s.id}>
                        <span className="onboard-stream-name">
                          <i style={{ background: CATEGORY_COLOR[s.category] }} />
                          {s.product}
                        </span>
                        <div className="onboard-stream-bar">
                          <span style={{ width: `${(s.annualUsd / maxStream) * 100}%`, background: CATEGORY_COLOR[s.category] }} />
                        </div>
                        <b>{usd(s.annualUsd)}</b>
                        <em>{s.basis}</em>
                      </div>
                    ))}
                    {a.degradationUsd > 0 && (
                      <div className="onboard-stream-row degr">
                        <span className="onboard-stream-name">
                          <i style={{ background: 'var(--red)' }} />
                          Degradation cost
                        </span>
                        <div className="onboard-stream-bar" />
                        <b className="text-red">−{usd(a.degradationUsd)}</b>
                        <em>Battery wear at {a.cyclesPerYear} cycles/yr, capped against warranty</em>
                      </div>
                    )}
                    {a.flags.length > 0 && (
                      <div className="onboard-asset-flags">
                        {a.flags.map((f, i) => (
                          <span key={i}><AlertTriangle size={11} /> {f}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Readiness + risks ── */}
      <section className="two-up">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Market readiness</p>
              <h2>What's certified, what needs work</h2>
            </div>
            <span className="live-indicator">{report.readinessScore}/100</span>
          </div>
          <div className="onboard-finding-list">
            {report.findings.map((f) => (
              <FindingRow key={f.id} f={f} />
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Risk register</p>
              <h2>Flags to clear before bidding</h2>
            </div>
            <span className="live-indicator">{report.riskFlags.length} flags</span>
          </div>
          <div className="onboard-risk-list">
            {report.riskFlags.length === 0 && (
              <p style={{ color: 'var(--muted)', fontSize: 13, padding: '8px 2px' }}>
                <CheckCircle2 size={14} style={{ verticalAlign: 'middle', marginRight: 6, color: 'var(--green)' }} />
                No material risks detected in this portfolio.
              </p>
            )}
            {report.riskFlags.map((r) => (
              <article className={`onboard-risk-row ${r.severity}`} key={r.id}>
                <div className="onboard-risk-head">
                  <strong>{r.label}</strong>
                  <em className={`risk ${r.severity === 'high' ? 'high' : r.severity === 'medium' ? 'medium' : 'low'}`}>
                    {r.severity}
                  </em>
                </div>
                <p>{r.detail}</p>
              </article>
            ))}
          </div>
        </section>
      </section>

      {/* ── Recommendations ── */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="label">Action plan</p>
            <h2>Ranked by dollar impact</h2>
          </div>
          <Lightbulb size={18} color="var(--amber)" />
        </div>
        <div className="onboard-rec-list">
          {report.recommendations.map((r, i) => (
            <article className={`onboard-rec-row ${r.priority}`} key={r.id}>
              <span className="onboard-rec-num">{i + 1}</span>
              <div className="onboard-rec-body">
                <div className="onboard-rec-title">
                  <strong>{r.title}</strong>
                  <em className={`onboard-prio ${r.priority}`}>{r.priority}</em>
                </div>
                <p>{r.detail}</p>
              </div>
              {r.impactUsd > 0 && <b className="text-green">+{usd(r.impactUsd)}/yr</b>}
            </article>
          ))}
        </div>
      </section>

      {/* ── Footer actions ── */}
      {activateNote && (
        <section className="panel onboard-warnbox">
          <p><AlertTriangle size={13} /> {activateNote}</p>
        </section>
      )}
      <section className="panel onboard-report-footer">
        <button className="btn-ghost" onClick={onBack}>
          <ArrowLeft size={15} /> Back to assets
        </button>
        <div className="onboard-footer-right">
          <button className="onboard-import" onClick={downloadSummary}>
            <Download size={13} /> Summary (.txt)
          </button>
          <button className="onboard-import" onClick={downloadReport}>
            <Download size={13} /> Full report (.json)
          </button>
          <button className="btn btn-lg" disabled={activating} onClick={() => void activate()}>
            {activating ? (
              <>
                <Loader2 size={16} className="spin" /> Activating fleet…
              </>
            ) : (
              <>
                Activate fleet &amp; go live <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </section>

      <p className="onboard-disclaimer">
        <ShieldCheck size={12} /> Estimates are advisory and model-based. Actual revenue depends on
        clearing prices, enrollment, accreditation, and dispatch performance. Confidence{' '}
        {Math.round(report.confidence * 100)}% based on import data quality.
      </p>
    </>
  )
}

const DEMO_DISPATCH_INTERVAL = 6

function FindingRow({ f }: { f: ReadinessFinding }) {
  const Icon = f.status === 'pass' ? CheckCircle2 : f.status === 'warn' ? AlertTriangle : AlertTriangle
  return (
    <article className={`onboard-finding-row ${f.status}`}>
      <Icon size={15} />
      <div>
        <strong>{f.label}</strong>
        <span>{f.detail}</span>
      </div>
      <em>{f.status}</em>
    </article>
  )
}

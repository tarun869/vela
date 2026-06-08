import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, CheckCircle2, X, AlertTriangle } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { SettlementSummary, DispatchRecord } from '../types/demo'
import { getSettlementSummary, getSettlementRecords } from '../services/demoApi'

const AX = { fontSize: 10, fill: 'var(--muted)' }
const GRID = { stroke: 'var(--line)' }
const TIP_STYLE = {
  fontSize: 12,
  borderRadius: 6,
  border: '1px solid var(--line)',
  background: 'var(--surface)',
}

function fmt$(n: number): string {
  return '$' + n.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function sign$(n: number): string {
  return (n >= 0 ? '+' : '') + fmt$(n)
}

export function SettlementDemoPage() {
  const [summary, setSummary] = useState<SettlementSummary | null>(null)
  const [records, setRecords] = useState<DispatchRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [sum, recs] = await Promise.all([getSettlementSummary(), getSettlementRecords()])
      setSummary(sum)
      setRecords(recs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load settlement data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  // Aggregate revenue by asset for the bar chart
  const assetRevenue = (() => {
    const byAsset: Record<string, { asset_id: string; vela: number; baseline: number }> = {}
    for (const r of records) {
      if (!byAsset[r.asset_id]) {
        byAsset[r.asset_id] = { asset_id: r.asset_id, vela: 0, baseline: 0 }
      }
      byAsset[r.asset_id].vela += r.revenue_usd
    }
    // Distribute baseline proportionally across assets
    const totalVela = Object.values(byAsset).reduce((s, a) => s + a.vela, 0)
    const baseline = summary?.baseline_revenue_usd ?? 0
    for (const entry of Object.values(byAsset)) {
      entry.baseline = totalVela > 0 ? (entry.vela / totalVela) * baseline : 0
    }
    return Object.values(byAsset)
  })()

  const sohTableRows = summary
    ? Object.entries(summary.soh_delta_by_asset).map(([asset_id, delta]) => ({
        asset_id,
        delta,
        end_soh: 100 + delta,
        start_soh: 100,
      }))
    : []

  return (
    <>
      <div className="page-header">
        <div>
          <p className="label" style={{ fontFamily: 'var(--mono)', textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.08em', color: 'var(--muted)' }}>Demo flow · Step 4 of 4</p>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Settlement summary</h1>
        </div>
        <button
          className="icon-btn"
          onClick={() => { void load() }}
          title="Refresh"
          disabled={loading}
        >
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
        </button>
      </div>

      {loading && !summary && (
        <section className="panel" style={{ textAlign: 'center', padding: 40 }}>
          <p className="label">Loading settlement data…</p>
        </section>
      )}

      {error && (
        <section className="panel" style={{ padding: '16px', marginBottom: 12 }}>
          <p style={{ color: 'var(--red)', margin: 0, fontSize: 13 }}>
            <AlertTriangle size={13} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            {error}
          </p>
        </section>
      )}

      {summary && (
        <>
          {/* ── Hero card ── */}
          <section className="panel hero-card">
            <div>
              <p className="label" style={{ margin: '0 0 4px' }}>Net value delivered</p>
              <p style={{ fontSize: 32, fontWeight: 800, margin: 0, fontFamily: 'var(--mono)', color: 'var(--ink)' }}>
                {fmt$(summary.net_value_usd)}
              </p>
              <p style={{ fontSize: 14, color: 'var(--muted)', margin: '6px 0' }}>
                vs rule-based baseline: {fmt$(summary.baseline_revenue_usd)}
              </p>
              <span
                style={{
                  display: 'inline-block',
                  fontWeight: 700,
                  fontSize: 15,
                  padding: '4px 12px',
                  borderRadius: 6,
                  background: summary.outperformance_usd >= 0 ? 'var(--green-soft)' : 'var(--red-soft)',
                  color: summary.outperformance_usd >= 0 ? 'var(--green)' : 'var(--red)',
                }}
              >
                Vela outperformance: {sign$(summary.outperformance_usd)} ({summary.outperformance_pct >= 0 ? '+' : ''}{summary.outperformance_pct.toFixed(1)}%)
              </span>
            </div>
          </section>

          {/* ── Four stat cards ── */}
          <div className="metrics-grid">
            <section className="metric-card">
              <div>
                <p className="label">Revenue captured</p>
                <strong>{fmt$(summary.total_revenue_usd)}</strong>
              </div>
            </section>
            <section className="metric-card">
              <div>
                <p className="label">Penalties avoided</p>
                <strong style={{ color: summary.total_penalties_usd === 0 ? 'var(--green)' : 'var(--red)' }}>
                  {fmt$(summary.total_penalties_usd)}
                </strong>
              </div>
            </section>
            <section className="metric-card">
              <div>
                <p className="label">Degradation cost</p>
                <strong>{fmt$(summary.total_degradation_cost_usd)}</strong>
              </div>
            </section>
            <section className="metric-card">
              <div>
                <p className="label">Compliance</p>
                <strong
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    color: summary.all_obligations_compliant ? 'var(--green)' : 'var(--red)',
                  }}
                >
                  {summary.all_obligations_compliant ? (
                    <><CheckCircle2 size={15} /> All obligations met</>
                  ) : (
                    <><X size={15} /> Breach detected</>
                  )}
                </strong>
              </div>
            </section>
          </div>

          {/* ── Revenue comparison chart ── */}
          {assetRevenue.length > 0 && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Revenue comparison</p>
                  <h2>Vela vs baseline, by asset</h2>
                </div>
              </div>
              <div style={{ padding: '0 8px 12px' }}>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={assetRevenue} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
                    <XAxis dataKey="asset_id" tick={AX} tickLine={false} axisLine={false} />
                    <YAxis tick={AX} tickLine={false} axisLine={false} tickFormatter={v => `$${v.toFixed(0)}`} />
                    <Tooltip contentStyle={TIP_STYLE} formatter={(v) => [typeof v === 'number' ? `$${v.toFixed(2)}` : v, undefined]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="vela" name="Vela" fill="var(--green)" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="baseline" name="Baseline" fill="var(--muted-2)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>
          )}

          {/* ── Asset health table ── */}
          {sohTableRows.length > 0 && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Asset health</p>
                  <h2>SOH change over session</h2>
                </div>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="roster-table">
                  <thead>
                    <tr>
                      <th>Asset</th>
                      <th>Start SOH</th>
                      <th>End SOH</th>
                      <th>Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sohTableRows.map(row => (
                      <tr
                        key={row.asset_id}
                        style={{
                          background: row.delta < -0.3 ? 'var(--amber-soft)' : undefined,
                        }}
                      >
                        <td><strong>{row.asset_id}</strong></td>
                        <td style={{ fontFamily: 'var(--mono)' }}>{row.start_soh.toFixed(2)}%</td>
                        <td style={{ fontFamily: 'var(--mono)' }}>{row.end_soh.toFixed(2)}%</td>
                        <td
                          style={{
                            fontFamily: 'var(--mono)',
                            color: row.delta < 0 ? 'var(--red)' : 'var(--green)',
                          }}
                        >
                          {row.delta >= 0 ? '+' : ''}{row.delta.toFixed(3)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ── Obligation compliance table ── */}
          {summary.obligation_records.length > 0 && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <p className="label">Obligations</p>
                  <h2>Compliance detail</h2>
                </div>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="roster-table">
                  <thead>
                    <tr>
                      <th>Obligation</th>
                      <th>Window</th>
                      <th>Committed</th>
                      <th>Delivered</th>
                      <th>Status</th>
                      <th>Penalty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.obligation_records.map((rec, i) => (
                      <tr
                        key={i}
                        style={{
                          background: !rec.compliant ? 'var(--red-soft)' : rec.compliant ? 'var(--green-soft)' : undefined,
                        }}
                      >
                        <td><strong>{rec.obligation_id}</strong></td>
                        <td style={{ fontSize: 11, fontFamily: 'var(--mono)' }}>
                          {rec.window_start.slice(11, 16)}–{rec.window_end.slice(11, 16)}
                        </td>
                        <td style={{ fontFamily: 'var(--mono)' }}>{rec.committed_mw.toFixed(1)} MW</td>
                        <td style={{ fontFamily: 'var(--mono)' }}>{rec.delivered_mw.toFixed(1)} MW</td>
                        <td>
                          {rec.compliant ? (
                            <span style={{ color: 'var(--green)', fontSize: 12 }}>
                              <CheckCircle2 size={12} style={{ verticalAlign: 'middle', marginRight: 3 }} />
                              Compliant
                            </span>
                          ) : (
                            <span style={{ color: 'var(--red)', fontSize: 12 }}>
                              <X size={12} style={{ verticalAlign: 'middle', marginRight: 3 }} />
                              Breach
                            </span>
                          )}
                        </td>
                        <td style={{ fontFamily: 'var(--mono)', color: rec.penalty_usd > 0 ? 'var(--red)' : 'var(--muted)' }}>
                          {rec.penalty_usd > 0 ? fmt$(rec.penalty_usd) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </>
  )
}

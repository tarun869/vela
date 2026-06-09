import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import {
  BatteryCharging,
  SunMedium,
  Zap,
  Wind,
  Activity,
  CheckCircle2,
  AlertTriangle,
  X,
  Loader2,
} from 'lucide-react'
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { DemoAssetType, DispatchDecision, DispatchRecord, SettlementSummary } from '../types/demo'
import { useFleet } from '../context/FleetContext'
import { overrideDispatch, getSettlementRecords, getSettlementSummary } from '../services/demoApi'
import type { SpikeAlertEntry } from '../context/FleetContext'

const ASSET_ICONS: Record<DemoAssetType, typeof BatteryCharging> = {
  BESS: BatteryCharging,
  Solar: SunMedium,
  Wind: Wind,
  EV_Fleet: Zap,
  Flex_Load: Activity,
}

const AX = { fontSize: 10, fill: 'var(--muted)' }
const GRID = { stroke: 'var(--line)' }
const TIP_STYLE = {
  fontSize: 12,
  borderRadius: 6,
  border: '1px solid var(--line)',
  background: 'var(--surface)',
}

function relTime(ts: number): string {
  const diff = Math.floor((Date.now() - ts) / 1000)
  if (diff < 60) return `${diff}s ago`
  return `${Math.floor(diff / 60)}m ago`
}

function actionStyle(mw: number): { label: string; color: string; bg: string } {
  if (mw > 0.05) return { label: 'DISCHARGE', color: 'var(--green)', bg: 'var(--green-soft)' }
  if (mw < -0.05) return { label: 'CHARGE', color: 'var(--blue)', bg: 'var(--blue-soft)' }
  return { label: 'HOLD', color: 'var(--muted)', bg: 'var(--surface-2)' }
}

function OverrideModal({
  decision,
  onClose,
  onSend,
}: {
  decision: DispatchDecision
  onClose: () => void
  onSend: (mw: number, reason: string) => Promise<void>
}) {
  const [mw, setMw] = useState(decision.recommended_mw)
  const [reason, setReason] = useState('')
  const [sending, setSending] = useState(false)

  const cap = Math.abs(decision.unconstrained_mw) || 10

  const submit = async () => {
    setSending(true)
    await onSend(mw, reason || 'Manual operator override')
    setSending(false)
    onClose()
  }

  return (
    <div className="demo-drawer-backdrop" onClick={onClose}>
      <div className="demo-drawer" style={{ maxWidth: 400 }} onClick={e => e.stopPropagation()}>
        <div className="demo-drawer-head">
          <strong>Override: {decision.asset_id}</strong>
          <button className="icon-btn" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="demo-drawer-body">
          <p className="label">Set dispatch MW (negative = charge)</p>
          <input
            type="range"
            min={-cap}
            max={cap}
            step={0.5}
            value={mw}
            onChange={e => setMw(parseFloat(e.target.value))}
            style={{ width: '100%', margin: '8px 0', accentColor: 'var(--green)' }}
          />
          <p style={{ fontFamily: 'var(--mono)', fontSize: 16, textAlign: 'center', margin: '4px 0 12px' }}>
            {mw >= 0 ? '+' : ''}{mw.toFixed(1)} MW
          </p>
          <label style={{ fontSize: 12, color: 'var(--muted)', display: 'block', marginBottom: 4 }}>Reason</label>
          <input
            type="text"
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="e.g. Thermal protection"
            style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--line)', borderRadius: 5, fontSize: 13, background: 'var(--surface)', color: 'var(--ink)', boxSizing: 'border-box', marginBottom: 12 }}
          />
          <button className="btn" style={{ width: '100%', justifyContent: 'center' }} disabled={sending} onClick={() => { void submit() }}>
            {sending ? <><Loader2 size={14} className="spin" /> Sending…</> : 'Apply override'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function DispatchPage() {
  const { telemetry, plan, priceHistory, alerts, spikeFlash, approveAlert, dismissAlert } = useFleet()
  const [overrideTarget, setOverrideTarget] = useState<DispatchDecision | null>(null)
  const [overrideSuccess, setOverrideSuccess] = useState<Set<string>>(new Set())
  const [records, setRecords] = useState<DispatchRecord[]>([])
  const [summary, setSummary] = useState<SettlementSummary | null>(null)
  const alertFeedRef = useRef<HTMLDivElement>(null)

  // Poll settlement so the revenue chart + stats reflect real accumulated P&L.
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const [recs, sum] = await Promise.all([getSettlementRecords(), getSettlementSummary()])
        if (!cancelled) {
          setRecords(recs)
          setSummary(sum)
        }
      } catch {
        /* tracker not ready yet */
      }
    }
    void poll()
    const t = setInterval(() => void poll(), 4000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])

  // Cumulative revenue vs LMP, built from real settlement records (aggregated per interval).
  const revenueData = useMemo(() => {
    if (records.length === 0) {
      return priceHistory.map(p => ({ time: p.timestamp.slice(11, 16), lmp: p.lmp_per_mwh, revenue: 0 }))
    }
    const byTs = new Map<string, { lmp: number; rev: number }>()
    for (const r of records) {
      const cur = byTs.get(r.timestamp) ?? { lmp: r.lmp_at_dispatch, rev: 0 }
      cur.rev += r.net_value_usd
      cur.lmp = r.lmp_at_dispatch
      byTs.set(r.timestamp, cur)
    }
    const sorted = [...byTs.entries()].sort((a, b) => a[0].localeCompare(b[0]))
    let cum = 0
    return sorted.map(([ts, v]) => {
      cum += v.rev
      return { time: ts.slice(11, 16), lmp: v.lmp, revenue: Math.round(cum) }
    })
  }, [records, priceHistory])

  useEffect(() => {
    if (alertFeedRef.current) alertFeedRef.current.scrollTop = 0
  }, [alerts.length])

  const sendOverride = useCallback(async (mw: number, reason: string) => {
    if (!overrideTarget) return
    await overrideDispatch({ asset_id: overrideTarget.asset_id, mw, reason })
    setOverrideSuccess(prev => new Set([...prev, overrideTarget.asset_id]))
  }, [overrideTarget])

  const sessionRevenue = summary?.total_revenue_usd ?? plan?.total_revenue_expected_usd ?? 0
  const netValue = summary?.net_value_usd ?? 0
  const peakLmp = priceHistory.length > 0 ? Math.max(...priceHistory.map(p => p.lmp_per_mwh)) : 0
  const degCost = summary?.total_degradation_cost_usd ?? plan?.total_constraint_cost_usd ?? 0

  const iconFor = (assetId: string) => {
    const t = telemetry[assetId]?.asset_type as DemoAssetType | undefined
    return (t && ASSET_ICONS[t]) || BatteryCharging
  }

  return (
    <div className={`dispatch-col-layout${spikeFlash ? ' spike-flash' : ''}`}>
      {/* ── LEFT: Dispatch plan ── */}
      <div className="dispatch-left">
        <div style={{ marginBottom: 12 }}>
          <p className="demo-eyebrow">Demo flow · Step 3 of 4</p>
          <h2 style={{ margin: '2px 0 0', fontSize: 16 }}>Current dispatch plan</h2>
          {plan && (
            <p style={{ fontSize: 11, color: 'var(--muted-2)', margin: '2px 0 0', fontFamily: 'var(--mono)' }}>
              {new Date(plan.interval_start).toLocaleTimeString()} · via {plan.recommended_by}
            </p>
          )}
        </div>

        {!plan && (
          <section className="panel" style={{ textAlign: 'center', padding: 32 }}>
            <Loader2 size={22} className="spin" style={{ color: 'var(--muted)', margin: '0 auto 10px', display: 'block' }} />
            <p className="label">Waiting for first dispatch plan…</p>
          </section>
        )}

        {plan?.decisions.map(decision => {
          const action = actionStyle(decision.recommended_mw)
          const AssetIcon = iconFor(decision.asset_id)
          const overridden = overrideSuccess.has(decision.asset_id)
          return (
            <section key={decision.asset_id} className="panel" style={{ marginBottom: 10 }}>
              <div style={{ padding: '10px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <AssetIcon size={14} color="var(--muted)" />
                  <strong style={{ fontSize: 13, flex: 1 }}>{decision.asset_id}</strong>
                  <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, color: action.color, background: action.bg }}>
                    {overridden ? 'OVERRIDDEN' : action.label}
                  </span>
                </div>

                <p style={{ fontFamily: 'var(--mono)', fontSize: 22, fontWeight: 700, margin: '4px 0', color: action.color }}>
                  {decision.recommended_mw >= 0 ? '+' : ''}{decision.recommended_mw.toFixed(1)} MW
                </p>

                <p style={{ fontSize: 12, color: 'var(--muted)', margin: '4px 0 8px', lineHeight: 1.4 }}>
                  {decision.reasoning}
                </p>

                {decision.binding_constraint && (
                  <div style={{ background: 'var(--surface-2)', borderRadius: 5, padding: '6px 8px', fontSize: 11, marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, color: 'var(--amber)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      {decision.binding_constraint.replace(/_/g, ' ')}
                    </span>
                    <p style={{ margin: '2px 0 0', color: 'var(--muted)' }}>
                      Holding this costs ${decision.constraint_cost_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </p>
                    <p style={{ margin: '1px 0 0', color: 'var(--muted-2)' }}>
                      Unconstrained ideal: {decision.unconstrained_mw.toFixed(1)} MW
                    </p>
                  </div>
                )}

                <button
                  style={{ background: 'none', border: 'none', color: 'var(--blue)', fontSize: 11, cursor: 'pointer', padding: 0 }}
                  onClick={() => setOverrideTarget(decision)}
                >
                  Override →
                </button>
              </div>
            </section>
          )
        })}
      </div>

      {/* ── CENTER: Revenue chart + stats ── */}
      <div className="dispatch-center">
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="label">Cumulative net value vs LMP</p>
              <h2>Live settlement this session</h2>
            </div>
          </div>
          <div style={{ padding: '0 8px 8px' }}>
            {revenueData.length > 1 ? (
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={revenueData} margin={{ top: 8, right: 48, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gRevenue" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--green)" stopOpacity={0.5} />
                      <stop offset="95%" stopColor="var(--green)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" {...GRID} vertical={false} />
                  <XAxis dataKey="time" tick={AX} tickLine={false} axisLine={false} minTickGap={28} />
                  <YAxis yAxisId="lmp" tick={AX} tickLine={false} axisLine={false} tickFormatter={v => `$${v}`} />
                  <YAxis yAxisId="rev" orientation="right" tick={AX} tickLine={false} axisLine={false} tickFormatter={v => `$${v.toFixed(0)}`} />
                  <Tooltip contentStyle={TIP_STYLE} />
                  <Area yAxisId="rev" type="monotone" dataKey="revenue" fill="url(#gRevenue)" stroke="var(--green)" strokeWidth={1.5} name="Net value $" isAnimationActive={false} />
                  <Line yAxisId="lmp" type="monotone" dataKey="lmp" stroke="var(--amber)" dot={false} strokeWidth={2} name="LMP $/MWh" isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <p className="label">Accumulating settlement data…</p>
              </div>
            )}
          </div>
        </section>

        <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginTop: 0 }}>
          <section className="metric-card"><div>
            <p className="label">Revenue captured</p>
            <strong>${sessionRevenue.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
          </div></section>
          <section className="metric-card"><div>
            <p className="label">Net value</p>
            <strong style={{ color: netValue >= 0 ? 'var(--green)' : 'var(--red)' }}>${netValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
          </div></section>
          <section className="metric-card"><div>
            <p className="label">Peak LMP</p>
            <strong>${peakLmp.toFixed(0)}<span style={{ fontSize: 12, color: 'var(--muted)' }}>/MWh</span></strong>
          </div></section>
          <section className="metric-card"><div>
            <p className="label">Degradation cost</p>
            <strong>${degCost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
          </div></section>
        </div>
      </div>

      {/* ── RIGHT: Obligations + Alert feed ── */}
      <div className="dispatch-right">
        {plan && plan.obligations_status.length > 0 && (
          <section className="panel" style={{ marginBottom: 12 }}>
            <div className="panel-head"><div><p className="label">Obligations</p><h2>Coverage status</h2></div></div>
            <div style={{ padding: '0 14px 10px' }}>
              {plan.obligations_status.map(obl => {
                const pct = obl.committed_mw > 0 ? Math.min(100, (obl.currently_covered_mw / obl.committed_mw) * 100) : 100
                const icon =
                  obl.status === 'COVERED' ? <CheckCircle2 size={14} color="var(--green)" /> :
                  obl.status === 'AT_RISK' ? <AlertTriangle size={14} color="var(--amber)" /> :
                  <X size={14} color="var(--red)" />
                return (
                  <div key={obl.obligation_id} style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                      {icon}
                      <span style={{ fontSize: 12, fontWeight: 600, flex: 1, textTransform: 'capitalize' }}>{obl.obligation_type.replace(/_/g, ' ')}</span>
                      <span style={{ fontSize: 11, color: 'var(--muted)', fontFamily: 'var(--mono)' }}>
                        {obl.currently_covered_mw.toFixed(1)}/{obl.committed_mw.toFixed(1)} MW
                      </span>
                    </div>
                    <div className="soc-bar" style={{ height: 4 }}>
                      <div className="soc-fill" style={{ width: `${pct}%`, background: obl.status === 'COVERED' ? 'var(--green)' : obl.status === 'AT_RISK' ? 'var(--amber)' : 'var(--red)' }} />
                    </div>
                    {obl.risk_reason && obl.status !== 'COVERED' && (
                      <p style={{ fontSize: 10, color: 'var(--muted-2)', margin: '3px 0 0' }}>{obl.risk_reason}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        )}

        <section className="panel">
          <div className="panel-head"><div><p className="label">Alert feed</p><h2>Live events</h2></div></div>
          <div className="alert-feed" ref={alertFeedRef}>
            {alerts.length === 0 && (
              <p style={{ fontSize: 12, color: 'var(--muted-2)', padding: '12px 14px' }}>
                No alerts yet. Events appear here as the optimizer runs.
              </p>
            )}
            {alerts.map(alert => {
              if (alert.type === 'spike') {
                const spike = alert as SpikeAlertEntry
                if (spike.dismissed) return null
                return (
                  <div key={spike.id} className={`alert-card alert-card--spike${spike.approved ? ' approved' : ''}`}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <strong style={{ fontSize: 13 }}>⚡ Price spike — ${spike.data.lmp.toFixed(0)}/MWh</strong>
                      <button className="icon-btn" style={{ width: 18, height: 18 }} onClick={() => dismissAlert(spike.id)}><X size={11} /></button>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--muted)', margin: '2px 0' }}>
                      Jumped from ${spike.data.prev_lmp.toFixed(0)} (+{spike.data.pct_change.toFixed(0)}%)
                    </p>
                    <p style={{ fontSize: 12, color: 'var(--muted)', margin: '2px 0' }}>
                      Vela recommends: {spike.data.recommended_action.replace(/_/g, ' ').toLowerCase()}
                    </p>
                    <p style={{ fontSize: 12, color: 'var(--green)', margin: '2px 0 8px' }}>
                      Capture opportunity: +${spike.data.additional_revenue_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </p>
                    <p style={{ fontSize: 11, color: spike.data.obligation_risk ? 'var(--amber)' : 'var(--muted-2)', margin: '0 0 8px' }}>
                      Obligation risk: {spike.data.obligation_risk ? '⚠ Yes — protect reserved MW' : 'None'}
                    </p>
                    {!spike.approved ? (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn" style={{ fontSize: 11, padding: '4px 10px', flex: 1, justifyContent: 'center' }} onClick={() => approveAlert(spike.id)}>
                          Approve discharge
                        </button>
                        <button style={{ fontSize: 11, padding: '4px 10px', flex: 1, background: 'var(--surface-2)', border: '1px solid var(--line)', borderRadius: 5, cursor: 'pointer', color: 'var(--ink)' }} onClick={() => dismissAlert(spike.id)}>
                          Keep plan
                        </button>
                      </div>
                    ) : (
                      <p style={{ fontSize: 12, color: 'var(--green)', margin: 0 }}>
                        <CheckCircle2 size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Override registered
                      </p>
                    )}
                  </div>
                )
              }

              if (alert.type === 'obligation') {
                return (
                  <div key={alert.id} className="alert-card alert-card--obligation">
                    <strong style={{ fontSize: 12, textTransform: 'capitalize' }}>⏱ {alert.data.obligation_type.replace(/_/g, ' ')} obligation</strong>
                    <p style={{ fontSize: 12, color: 'var(--muted)', margin: '3px 0 0' }}>
                      {alert.data.status === 'AT_RISK' ? 'At risk' : 'Breach'} · {alert.data.currently_covered_mw.toFixed(1)}/{alert.data.committed_mw.toFixed(1)} MW
                    </p>
                  </div>
                )
              }

              return (
                <div key={alert.id} className="alert-card alert-card--dispatch">
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <strong style={{ fontSize: 12 }}>↻ Interval re-optimized</strong>
                    <span style={{ fontSize: 10, color: 'var(--muted-2)' }}>{relTime(alert.ts)}</span>
                  </div>
                  <p style={{ fontSize: 11, color: 'var(--muted)', margin: '3px 0 0', lineHeight: 1.4 }}>{alert.summary}</p>
                </div>
              )
            })}
          </div>
        </section>
      </div>

      {overrideTarget && (
        <OverrideModal decision={overrideTarget} onClose={() => setOverrideTarget(null)} onSend={sendOverride} />
      )}
    </div>
  )
}

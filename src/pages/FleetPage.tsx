import { useMemo } from 'react'
import {
  BatteryCharging,
  SunMedium,
  Zap,
  Wind,
  Activity,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  ArrowRight,
  Gauge,
  CircleDollarSign,
} from 'lucide-react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import type { DemoAssetType } from '../types/demo'
import { useFleet } from '../context/FleetContext'

type PageId = string

const ASSET_ICONS: Record<DemoAssetType, typeof BatteryCharging> = {
  BESS: BatteryCharging,
  Solar: SunMedium,
  Wind: Wind,
  EV_Fleet: Zap,
  Flex_Load: Activity,
}

const STORAGE_TYPES = new Set<DemoAssetType>(['BESS', 'EV_Fleet', 'Flex_Load'])

function lmpColor(lmp: number): string {
  if (lmp < 40) return 'var(--blue)'
  if (lmp < 150) return 'var(--muted)'
  if (lmp < 300) return 'var(--amber)'
  return 'var(--red)'
}

function socColor(soc: number): string {
  if (soc > 50) return 'var(--green)'
  if (soc > 20) return 'var(--amber)'
  return 'var(--red)'
}

function fmt(n: number, decimals = 1): string {
  return n.toFixed(decimals)
}

export function FleetPage({ goToPage }: { goToPage: (id: PageId) => void }) {
  const { connected, telemetry, sohStart, price, priceHistory, plan, dispatchActive } = useFleet()

  const assets = Object.values(telemetry)

  // Online (rated) capacity — the real fleet size, independent of instantaneous power.
  const onlineCapacity = useMemo(() => assets.reduce((s, a) => s + (a.rated_mw || 0), 0), [assets])
  // Net dispatch power right now (signed): + discharge/export, - charge.
  const netPower = useMemo(() => assets.reduce((s, a) => s + a.power_mw, 0), [assets])
  const avgSoh = useMemo(() => {
    const storage = assets.filter(a => STORAGE_TYPES.has(a.asset_type as DemoAssetType))
    if (storage.length === 0) return 0
    return storage.reduce((s, a) => s + a.soh_pct, 0) / storage.length
  }, [assets])

  // Obligation coverage derived from the live plan (no hardcoding).
  const obligation = useMemo(() => {
    const active = (plan?.obligations_status ?? []).filter(o => o.committed_mw > 0 && o.risk_reason?.startsWith('Not in') !== true)
    if (active.length === 0) return null
    const committed = active.reduce((s, o) => s + o.committed_mw, 0)
    const covered = active.reduce((s, o) => s + o.currently_covered_mw, 0)
    const worst = active.some(o => o.status === 'BREACHED')
      ? 'BREACHED'
      : active.some(o => o.status === 'AT_RISK')
        ? 'AT_RISK'
        : 'COVERED'
    return { committed, covered, status: worst as 'COVERED' | 'AT_RISK' | 'BREACHED' }
  }, [plan])

  const sparkData = priceHistory.map((p, i) => ({ i, v: p.lmp_per_mwh }))

  const obColor =
    obligation?.status === 'BREACHED' ? 'var(--red)' : obligation?.status === 'AT_RISK' ? 'var(--amber)' : 'var(--green)'

  return (
    <>
      <div className="page-header">
        <div>
          <p className="demo-eyebrow">Demo flow · Step 2 of 4</p>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: '2px 0 0' }}>Live fleet</h1>
        </div>
        <div className="status-strip">
          {dispatchActive && (
            <b>
              <span className="status-dot" data-on="true" />
              Optimizer live
            </b>
          )}
          <span
            className="live-indicator"
            style={connected ? undefined : { color: 'var(--muted)', background: 'var(--surface)', borderColor: 'var(--line)' }}
          >
            <span className="status-dot" data-on={connected ? 'true' : 'false'} />
            {connected ? 'Telemetry streaming' : 'Connecting…'}
          </span>
        </div>
      </div>

      {/* ── Summary bar ── */}
      <div className="metrics-grid">
        <section className="metric-card">
          <div className="metric-icon"><BatteryCharging size={18} /></div>
          <div>
            <p className="label">Online capacity</p>
            <strong>{fmt(onlineCapacity)} MW</strong>
            <span>{assets.length} assets connected</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-icon"><Activity size={18} /></div>
          <div>
            <p className="label">Net dispatch</p>
            <strong style={{ color: netPower > 0.1 ? 'var(--green)' : netPower < -0.1 ? 'var(--blue)' : 'var(--ink)' }}>
              {netPower >= 0 ? '+' : ''}{fmt(netPower)} MW
            </strong>
            <span>{netPower > 0.1 ? 'Net discharging / exporting' : netPower < -0.1 ? 'Net charging' : 'Balanced'}</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-icon"><Gauge size={18} /></div>
          <div>
            <p className="label">Average fleet SOH</p>
            <strong>{fmt(avgSoh)}%</strong>
            <span>Storage state of health</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-icon"><CheckCircle2 size={18} /></div>
          <div>
            <p className="label">Capacity obligation</p>
            {obligation ? (
              <>
                <strong style={{ color: obColor }}>
                  {obligation.status === 'COVERED' ? 'Covered' : obligation.status === 'AT_RISK' ? 'At risk' : 'Breach'}
                </strong>
                <span>{fmt(obligation.covered)}/{fmt(obligation.committed)} MW reserved</span>
              </>
            ) : (
              <>
                <strong style={{ color: 'var(--muted)' }}>Standby</strong>
                <span>No active delivery window</span>
              </>
            )}
          </div>
        </section>
      </div>

      {/* ── Price strip ── */}
      {price && (
        <section className="panel price-strip">
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <div>
              <p className="label" style={{ margin: 0 }}>Current LMP</p>
              <strong style={{ fontSize: 28, fontFamily: 'var(--mono)', color: lmpColor(price.lmp_per_mwh), lineHeight: 1.1 }}>
                ${price.lmp_per_mwh.toFixed(2)}
                <span style={{ fontSize: 13, fontWeight: 400, color: 'var(--muted)', marginLeft: 4 }}>/MWh</span>
              </strong>
              <span style={{ fontSize: 11, color: 'var(--muted-2)', display: 'block' }}>
                {price.node} · {price.interval_type.replace('_', '-')}
              </span>
            </div>
            {sparkData.length > 1 && (
              <div style={{ flex: 1, height: 44 }}>
                <ResponsiveContainer width="100%" height={44}>
                  <LineChart data={sparkData}>
                    <Line type="monotone" dataKey="v" stroke={lmpColor(price.lmp_per_mwh)} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </section>
      )}

      {/* ── Empty state ── */}
      {assets.length === 0 && (
        <section className="panel" style={{ textAlign: 'center', padding: 40 }}>
          <Loader2 size={24} className="spin" style={{ color: 'var(--muted)', margin: '0 auto 12px' }} />
          <p className="label">Waiting for telemetry…</p>
          <p style={{ fontSize: 12, color: 'var(--muted-2)' }}>
            Connect a fleet from the Onboard step to start streaming.
          </p>
        </section>
      )}

      {/* ── Asset card grid ── */}
      <div className="asset-grid">
        {assets.map(asset => {
          const type = asset.asset_type as DemoAssetType
          const AssetIcon = ASSET_ICONS[type] ?? BatteryCharging
          const isStorage = STORAGE_TYPES.has(type)
          const sohDelta = asset.soh_pct - (sohStart[asset.asset_id] ?? asset.soh_pct)
          const tempHot = asset.temperature_c > 35
          const power = asset.power_mw
          const utilisation = asset.rated_mw > 0 ? Math.min(100, (Math.abs(power) / asset.rated_mw) * 100) : 0

          return (
            <section key={asset.asset_id} className="panel asset-tile">
              <div className="asset-tile-head">
                <AssetIcon size={16} color="var(--green)" />
                <strong style={{ fontSize: 13, flex: 1 }}>{asset.asset_id}</strong>
                <span className="demo-status-badge" data-status={asset.connection_status}>
                  {asset.connection_status.toUpperCase()}
                </span>
                {asset.alarm && (
                  <span className="demo-alarm-badge"><AlertTriangle size={10} /> {asset.alarm}</span>
                )}
              </div>

              <div style={{ padding: '0 14px 4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                  <span>{isStorage ? 'State of charge' : 'Output'}</span>
                  <span>{isStorage ? `${fmt(asset.soc_pct)}%` : `${fmt(power)} / ${fmt(asset.rated_mw)} MW`}</span>
                </div>
                <div className="soc-bar">
                  <div
                    className="soc-fill"
                    style={{
                      width: `${isStorage ? asset.soc_pct : utilisation}%`,
                      background: isStorage ? socColor(asset.soc_pct) : 'var(--green)',
                    }}
                  />
                </div>
              </div>

              <div className="asset-tile-stats">
                <div>
                  <span className="asset-stat-label">Power</span>
                  <strong style={{ color: power > 0.05 ? 'var(--green)' : power < -0.05 ? 'var(--blue)' : 'var(--muted)', fontFamily: 'var(--mono)' }}>
                    {power >= 0 ? '+' : ''}{fmt(power)} MW
                  </strong>
                </div>
                <div>
                  <span className="asset-stat-label">Temp</span>
                  <strong style={{ color: tempHot ? 'var(--red)' : 'var(--ink)', fontFamily: 'var(--mono)' }}>
                    {fmt(asset.temperature_c)}°C
                    {tempHot && <AlertTriangle size={10} style={{ marginLeft: 3, verticalAlign: 'middle' }} />}
                  </strong>
                </div>
                {isStorage ? (
                  <>
                    <div>
                      <span className="asset-stat-label">SOH</span>
                      <strong style={{ fontFamily: 'var(--mono)' }}>
                        {fmt(asset.soh_pct)}%
                        {Math.abs(sohDelta) > 0.001 && (
                          <span style={{ fontSize: 10, color: sohDelta < 0 ? 'var(--red)' : 'var(--green)', marginLeft: 3 }}>
                            {sohDelta >= 0 ? '+' : ''}{fmt(sohDelta, 2)}
                          </span>
                        )}
                      </strong>
                    </div>
                    <div>
                      <span className="asset-stat-label">Voltage</span>
                      <strong style={{ fontFamily: 'var(--mono)' }}>{fmt(asset.voltage_v)} V</strong>
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <span className="asset-stat-label">Type</span>
                      <strong style={{ fontFamily: 'var(--mono)' }}>{type.replace('_', ' ')}</strong>
                    </div>
                    <div>
                      <span className="asset-stat-label">Capacity factor</span>
                      <strong style={{ fontFamily: 'var(--mono)' }}>{fmt(utilisation)}%</strong>
                    </div>
                  </>
                )}
              </div>
            </section>
          )
        })}
      </div>

      {/* ── CTA ── */}
      {assets.length > 0 && (
        <section className="panel" style={{ padding: '14px 16px' }}>
          <button
            className="btn btn-lg"
            style={{ width: '100%', justifyContent: 'center' }}
            onClick={() => goToPage('dispatch')}
          >
            <CircleDollarSign size={16} /> Open dispatch board <ArrowRight size={16} />
          </button>
        </section>
      )}
    </>
  )
}

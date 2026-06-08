import { useState, useMemo } from 'react'
import {
  BatteryCharging,
  SunMedium,
  Zap,
  Wind,
  Activity,
  AlertTriangle,
  CheckCircle2,
  Loader2,
} from 'lucide-react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'
import type { DemoAssetType } from '../types/demo'
import { useFleetWebSocket } from '../hooks/useFleetWebSocket'
import { startDispatch } from '../services/demoApi'

type PageId = string

const ASSET_ICONS: Record<DemoAssetType, typeof BatteryCharging> = {
  BESS: BatteryCharging,
  Solar: SunMedium,
  Wind: Wind,
  EV_Fleet: Zap,
  Flex_Load: Activity,
}

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
  const { connected, telemetry, sohStart, price, priceHistory } = useFleetWebSocket()
  const [dispatchStarted, setDispatchStarted] = useState(false)
  const [dispatchError, setDispatchError] = useState<string | null>(null)

  const assets = Object.values(telemetry)

  const totalCapacity = useMemo(
    () => assets.reduce((sum, a) => sum + Math.abs(a.power_mw), 0),
    [assets],
  )
  const avgSoh = useMemo(
    () => (assets.length > 0 ? assets.reduce((s, a) => s + a.soh_pct, 0) / assets.length : 0),
    [assets],
  )

  const handleStartDispatch = async () => {
    try {
      await startDispatch(30)
      setDispatchStarted(true)
      setTimeout(() => goToPage('dispatch'), 1500)
    } catch (err) {
      setDispatchError(err instanceof Error ? err.message : 'Failed to start dispatch')
    }
  }

  const sparkData = priceHistory.map((p, i) => ({ i, v: p.lmp_per_mwh }))

  return (
    <>
      <div className="page-header">
        <div>
          <p className="label" style={{ fontFamily: 'var(--mono)', textTransform: 'uppercase', fontSize: 10, letterSpacing: '0.08em', color: 'var(--muted)' }}>Demo flow · Step 2 of 4</p>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Live fleet</h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: connected ? 'var(--green)' : 'var(--muted-2)',
              display: 'inline-block',
            }}
          />
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {connected ? 'Connected' : 'Connecting…'}
          </span>
        </div>
      </div>

      {/* ── Summary bar ── */}
      <div className="metrics-grid" style={{ marginBottom: 16 }}>
        <section className="metric-card">
          <div className="metric-icon"><Activity size={18} /></div>
          <div>
            <p className="label">Total online capacity</p>
            <strong>{fmt(totalCapacity)} MW</strong>
            <span>{assets.length} assets connected</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-icon"><BatteryCharging size={18} /></div>
          <div>
            <p className="label">Average fleet SOH</p>
            <strong>{fmt(avgSoh)}%</strong>
            <span>State of health</span>
          </div>
        </section>
        <section className="metric-card">
          <div className="metric-icon"><CheckCircle2 size={18} /></div>
          <div>
            <p className="label">Obligations status</p>
            <strong style={{ color: 'var(--green)' }}>All Covered</strong>
            <span>No active alerts</span>
          </div>
        </section>
      </div>

      {/* ── Asset card grid ── */}
      {assets.length === 0 && !connected && (
        <section className="panel" style={{ textAlign: 'center', padding: 40 }}>
          <Loader2 size={24} className="spin" style={{ color: 'var(--muted)', margin: '0 auto 12px' }} />
          <p className="label">Waiting for telemetry…</p>
          <p style={{ fontSize: 12, color: 'var(--muted-2)' }}>
            Start a demo fleet with POST /api/v1/fleet/demo or return to Onboard.
          </p>
        </section>
      )}

      <div className="asset-grid">
        {assets.map(asset => {
          const AssetIcon = ASSET_ICONS[asset.asset_type as DemoAssetType] ?? BatteryCharging
          const sohDelta = asset.soh_pct - (sohStart[asset.asset_id] ?? asset.soh_pct)
          const tempHot = asset.temperature_c > 35
          const power = asset.power_mw

          return (
            <section key={asset.asset_id} className="panel" style={{ padding: 0 }}>
              <div style={{ padding: '12px 14px 8px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <AssetIcon size={16} color="var(--green)" />
                <strong style={{ fontSize: 13, flex: 1 }}>{asset.asset_id}</strong>
                <span
                  className="demo-status-badge"
                  data-status={asset.connection_status}
                >
                  {asset.connection_status.toUpperCase()}
                </span>
                {asset.alarm && (
                  <span className="demo-alarm-badge">
                    <AlertTriangle size={10} /> {asset.alarm}
                  </span>
                )}
              </div>

              <div style={{ padding: '0 14px 4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)', marginBottom: 4 }}>
                  <span>SOC</span>
                  <span>{fmt(asset.soc_pct)}%</span>
                </div>
                <div className="soc-bar">
                  <div
                    className="soc-fill"
                    style={{ width: `${asset.soc_pct}%`, background: socColor(asset.soc_pct) }}
                  />
                </div>
              </div>

              <div style={{ padding: '8px 14px 12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 12 }}>
                <div>
                  <span style={{ color: 'var(--muted)', display: 'block', fontSize: 10 }}>Power</span>
                  <strong
                    style={{
                      color: power > 0 ? 'var(--green)' : power < 0 ? 'var(--blue)' : 'var(--muted)',
                      fontFamily: 'var(--mono)',
                    }}
                  >
                    {power >= 0 ? '+' : ''}{fmt(power)} MW
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--muted)', display: 'block', fontSize: 10 }}>Temperature</span>
                  <strong style={{ color: tempHot ? 'var(--red)' : 'var(--ink)', fontFamily: 'var(--mono)' }}>
                    {fmt(asset.temperature_c)}°C
                    {tempHot && <AlertTriangle size={10} style={{ marginLeft: 3, verticalAlign: 'middle' }} />}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--muted)', display: 'block', fontSize: 10 }}>SOH</span>
                  <strong style={{ fontFamily: 'var(--mono)' }}>
                    {fmt(asset.soh_pct)}%
                    {sohDelta !== 0 && (
                      <span style={{ fontSize: 10, color: sohDelta < 0 ? 'var(--red)' : 'var(--green)', marginLeft: 3 }}>
                        {sohDelta >= 0 ? '+' : ''}{fmt(sohDelta, 2)}
                      </span>
                    )}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--muted)', display: 'block', fontSize: 10 }}>Voltage</span>
                  <strong style={{ fontFamily: 'var(--mono)' }}>{fmt(asset.voltage_v)} V</strong>
                </div>
              </div>
            </section>
          )
        })}
      </div>

      {/* ── Price strip ── */}
      {price && (
        <section className="panel price-strip">
          <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
            <div>
              <p className="label" style={{ margin: 0 }}>Current LMP</p>
              <strong
                style={{
                  fontSize: 28,
                  fontFamily: 'var(--mono)',
                  color: lmpColor(price.lmp_per_mwh),
                  lineHeight: 1.1,
                }}
              >
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
                    <Line
                      type="monotone"
                      dataKey="v"
                      stroke={lmpColor(price.lmp_per_mwh)}
                      dot={false}
                      strokeWidth={1.5}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </section>
      )}

      {/* ── Start Dispatch CTA ── */}
      <section className="panel" style={{ marginTop: 8 }}>
        <div style={{ padding: '12px 16px' }}>
          {dispatchError && (
            <p style={{ color: 'var(--red)', fontSize: 12, marginBottom: 8 }}>
              <AlertTriangle size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
              {dispatchError}
            </p>
          )}
          <button
            className="btn"
            style={{
              width: '100%',
              justifyContent: 'center',
              background: dispatchStarted ? 'var(--green)' : undefined,
              fontSize: 15,
              padding: '12px 0',
            }}
            disabled={dispatchStarted}
            onClick={() => { void handleStartDispatch() }}
          >
            {dispatchStarted ? (
              <><CheckCircle2 size={16} /> Dispatch Active ✓</>
            ) : (
              'Start Dispatch'
            )}
          </button>
        </div>
      </section>
    </>
  )
}

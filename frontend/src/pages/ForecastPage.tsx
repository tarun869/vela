import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from 'recharts'
import { generatePriceForecast, generateLoadForecast } from '../data/mockData'

const PRICE_DATA = generatePriceForecast()
const LOAD_DATA  = generateLoadForecast()

const CHART_PRICE = PRICE_DATA.filter((_, i) => i % 2 === 0)
const CHART_LOAD  = LOAD_DATA.filter((_, i) => i % 2 === 0)

const CustomPriceTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload) return null
  const p = payload.find((p: any) => p.dataKey === 'p50')
  const actual = payload.find((p: any) => p.dataKey === 'actual')
  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 14px', fontSize: 12, boxShadow: '0 4px 12px rgb(0 0 0/0.1)' }}>
      <div style={{ fontWeight: 700, marginBottom: 6, color: '#1e293b' }}>{label}</div>
      {actual?.value !== undefined && (
        <div style={{ color: '#1e293b', marginBottom: 2 }}>Actual: <strong>${Number(actual.value).toFixed(1)}</strong></div>
      )}
      {p && <div style={{ color: '#2563eb' }}>Forecast p50: <strong>${Number(p.value).toFixed(1)}/MWh</strong></div>}
    </div>
  )
}

const CRPS_SCORES = [
  { model: 'LightGBM Quantile', crps: 2.14, bias: 0.8, last24h: '2.31', trend: 'improving' },
  { model: 'Persistence Baseline', crps: 8.72, bias: -2.4, last24h: '9.10', trend: 'stable' },
  { model: 'HMM Regime (AS)', crps: 1.88, bias: 0.3, last24h: '1.95', trend: 'improving' },
]

export default function ForecastPage() {
  const now72 = new Date()
  now72.setHours(18, 0, 0, 0)

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Forecasting</div>
        <div className="page-subtitle">
          LightGBM quantile forecasts · 96-interval horizon · CRPS-calibrated · updated 18:00 PST
        </div>
      </div>

      {/* CRPS model table */}
      <div className="metric-grid metric-grid-3" style={{ marginBottom: 24 }}>
        {CRPS_SCORES.map(m => (
          <div className="metric-card" key={m.model}>
            <div className="metric-label">{m.model}</div>
            <div className="metric-value-sm">{m.crps}</div>
            <div className="metric-sub">CRPS score (lower = better)</div>
            <div style={{ marginTop: 4, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>Bias: </span>
              <span style={{ fontWeight: 600, color: Math.abs(m.bias) < 1 ? 'var(--success)' : 'var(--warning)' }}>
                {m.bias > 0 ? '+' : ''}{m.bias}%
              </span>
              <span style={{ marginLeft: 10, color: 'var(--text-muted)' }}>Trend: </span>
              <span style={{ fontWeight: 600, color: m.trend === 'improving' ? 'var(--success)' : 'var(--text-muted)' }}>
                {m.trend === 'improving' ? '↓' : '→'} {m.trend}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Price forecast fan chart */}
      <div className="chart-card">
        <div className="chart-title">LMP Price Forecast — CAISO SP15</div>
        <div className="chart-subtitle">
          Quantile fan (p10/p25/p50/p75/p90) · dashed line = actuals where available
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={CHART_PRICE} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="gradP90" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#93c5fd" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#93c5fd" stopOpacity={0.05} />
              </linearGradient>
              <linearGradient id="gradP75" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis dataKey="time" tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={7} />
            <YAxis
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={v => `$${v}`}
            />
            <Tooltip content={<CustomPriceTooltip />} />
            {/* Outer band p10-p90 */}
            <Area type="monotone" dataKey="p90" fill="url(#gradP90)" stroke="none" />
            <Area type="monotone" dataKey="p75" fill="url(#gradP75)" stroke="none" />
            {/* Median */}
            <Area
              type="monotone"
              dataKey="p50"
              fill="none"
              stroke="#2563eb"
              strokeWidth={2}
            />
            {/* p25 lower band fill */}
            <Area type="monotone" dataKey="p25" fill="white" stroke="none" />
            {/* Actuals */}
            <Area
              type="monotone"
              dataKey="actual"
              fill="none"
              stroke="#1e293b"
              strokeWidth={1.5}
              strokeDasharray="4 2"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>

        <div className="legend">
          {[
            { color: '#93c5fd', label: 'p10–p90 band', bg: true },
            { color: '#3b82f6', label: 'p25–p75 band', bg: true },
            { color: '#2563eb', label: 'p50 median', bg: false },
            { color: '#1e293b', label: 'Actual (ex-post)', dashed: true },
          ].map(l => (
            <div className="legend-item" key={l.label}>
              {l.dashed
                ? <span className="legend-dot" style={{ background: 'transparent', border: `2px dashed ${l.color}`, borderRadius: 0, width: 14, height: 3 }} />
                : <span className="legend-dot" style={{ background: l.color, opacity: l.bg ? 0.6 : 1 }} />
              }
              {l.label}
            </div>
          ))}
        </div>
      </div>

      {/* Load + Solar side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Load forecast */}
        <div className="chart-card" style={{ marginBottom: 0 }}>
          <div className="chart-title">Site Load Forecast</div>
          <div className="chart-subtitle">kW · p10/p50/p90 quantiles</div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={CHART_LOAD} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gradLoad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#7c3aed" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#7c3aed" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={11} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}kW`} />
              <Tooltip formatter={(v: any) => [`${Number(v).toFixed(0)} kW`]} />
              <Area type="monotone" dataKey="load_p90" fill="url(#gradLoad)" stroke="none" />
              <Area type="monotone" dataKey="load_p50" fill="none" stroke="#7c3aed" strokeWidth={2} />
              <Area type="monotone" dataKey="load_p10" fill="white" stroke="none" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Solar forecast */}
        <div className="chart-card" style={{ marginBottom: 0 }}>
          <div className="chart-title">Solar Generation Forecast</div>
          <div className="chart-subtitle">kW · pvlib clear-sky × cloud-factor uncertainty</div>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={CHART_LOAD} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gradSol" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={11} />
              <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} tickFormatter={v => `${v}kW`} />
              <Tooltip formatter={(v: any) => [`${Number(v).toFixed(0)} kW`]} />
              <Area type="monotone" dataKey="solar_p90" fill="url(#gradSol)" stroke="none" />
              <Area type="monotone" dataKey="solar_p50" fill="none" stroke="#f59e0b" strokeWidth={2} />
              <Area type="monotone" dataKey="solar_p10" fill="white" stroke="none" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Forecast accuracy table */}
      <div className="card" style={{ marginTop: 20, padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px 12px', borderBottom: '1px solid var(--border-light)' }}>
          <div className="section-title">Forecast Model Accuracy — Rolling 7-day Window</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            CRPS = Continuous Ranked Probability Score · lower is better
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Target</th>
              <th style={{ textAlign: 'right' }}>CRPS (7d avg)</th>
              <th style={{ textAlign: 'right' }}>RMSE</th>
              <th style={{ textAlign: 'right' }}>MAE</th>
              <th style={{ textAlign: 'right' }}>Bias</th>
              <th>Trend</th>
            </tr>
          </thead>
          <tbody>
            {[
              { model: 'LightGBM Quantile',    target: 'LMP SP15',       crps: 2.14, rmse: 8.4,  mae: 6.1,  bias: '+0.8%',  trend: '↓ improving' },
              { model: 'LightGBM Quantile',    target: 'Site Load',      crps: 38.2, rmse: 54.1, mae: 42.0, bias: '+1.2%',  trend: '↓ improving' },
              { model: 'pvlib × Cloud Factor', target: 'Solar Hayward',  crps: 68.4, rmse: 94.2, mae: 71.3, bias: '-0.4%',  trend: '→ stable'    },
              { model: 'HMM 4-state',          target: 'AS Regime',      crps: 1.88, rmse: null, mae: null, bias: '+0.3%',  trend: '↓ improving' },
            ].map((r, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 500 }}>{r.model}</td>
                <td style={{ color: 'var(--text-muted)' }}>{r.target}</td>
                <td style={{ textAlign: 'right', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>{r.crps}</td>
                <td style={{ textAlign: 'right', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                  {r.rmse ?? '—'}
                </td>
                <td style={{ textAlign: 'right', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                  {r.mae ?? '—'}
                </td>
                <td style={{ textAlign: 'right', fontWeight: 600 }}>{r.bias}</td>
                <td style={{ color: r.trend.startsWith('↓') ? 'var(--success)' : 'var(--text-muted)', fontWeight: 500 }}>
                  {r.trend}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

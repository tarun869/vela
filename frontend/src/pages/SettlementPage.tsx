import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts'
import { SETTLEMENT_LINES, SETTLEMENT_SUMMARY } from '../data/mockData'

const WATERFALL_DATA = [
  { name: 'Energy Arb',       value: 50_878,  fill: '#22c55e' },
  { name: 'AS Spinning',      value: 18_440,  fill: '#3b82f6' },
  { name: 'AS Reg Up',        value: 28_110,  fill: '#6366f1' },
  { name: 'DR Event',         value: 9_778,   fill: '#f59e0b' },
  { name: 'AS Non-Spin',      value: 7_056,   fill: '#06b6d4' },
  { name: 'V2G Export',       value: 1_094,   fill: '#84cc16' },
  { name: 'Capacity',         value: 9_195,   fill: '#a855f7' },
  { name: 'Vela Fee',         value: -24_910, fill: '#ef4444' },
  { name: 'Customer Pmt',     value: 99_641,  fill: '#16a34a' },
]

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.[0]) return null
  const v = Number(payload[0].value)
  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 14px', fontSize: 12, boxShadow: '0 4px 12px rgb(0 0 0/0.1)' }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>
      <div style={{ color: v < 0 ? 'var(--danger)' : 'var(--success)', fontWeight: 600 }}>
        {v < 0 ? '−' : '+'}${Math.abs(v).toLocaleString()}
      </div>
    </div>
  )
}

function statusBadge(s: string) {
  if (s === 'settled')  return <span className="badge badge-online"><span className="badge-dot" />Settled</span>
  if (s === 'pending')  return <span className="badge badge-standby"><span className="badge-dot" />Pending</span>
  return <span className="badge badge-offline"><span className="badge-dot" />Disputed</span>
}

const PERIODS = ['June 2026', 'May 2026', 'April 2026', 'Q1 2026']

export default function SettlementPage() {
  const s = SETTLEMENT_SUMMARY
  const totalSettled = SETTLEMENT_LINES.filter(l => l.status === 'settled').reduce((a, l) => a + l.revenue, 0)
  const totalPending = SETTLEMENT_LINES.filter(l => l.status === 'pending').reduce((a, l) => a + l.revenue, 0)

  return (
    <div>
      <div className="page-header flex justify-between items-center">
        <div>
          <div className="page-title">Settlement & Revenue</div>
          <div className="page-subtitle">CAISO settlement statements · M&V · revenue attribution</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {PERIODS.map(p => (
            <button
              key={p}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                border: '1px solid',
                fontSize: 13,
                fontWeight: 500,
                fontFamily: 'inherit',
                cursor: 'pointer',
                background: p === 'June 2026' ? 'var(--primary)' : '#fff',
                color:      p === 'June 2026' ? '#fff'           : 'var(--text-muted)',
                borderColor: p === 'June 2026' ? 'var(--primary)' : 'var(--border)',
              }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Revenue summary */}
      <div className="metric-grid metric-grid-4" style={{ marginBottom: 24 }}>
        <div className="metric-card">
          <div className="metric-label">Gross Revenue</div>
          <div className="metric-value-sm">${(s.grossRevenue / 1000).toFixed(1)}k</div>
          <div className="metric-delta up">↑ +12.4% vs May</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Vela Platform Fee</div>
          <div className="metric-value-sm" style={{ color: 'var(--danger)' }}>−${(s.velaFee / 1000).toFixed(1)}k</div>
          <div className="metric-sub">20% of gross revenue</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Customer Payment</div>
          <div className="metric-value-sm" style={{ color: 'var(--success)' }}>${(s.customerPayment / 1000).toFixed(1)}k</div>
          <div className="metric-sub">
            Incl. <span style={{ color: 'var(--primary)', fontWeight: 600 }}>${(s.performanceBonus / 1000).toFixed(1)}k</span> perf. bonus
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Delivery Fraction</div>
          <div className="metric-value-sm">{Math.round(s.deliveryFraction * 100)}%</div>
          <div className="metric-delta up">
            Availability: {Math.round(s.availabilityFraction * 100)}%
          </div>
        </div>
      </div>

      {/* Waterfall + table side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.3fr', gap: 20, marginBottom: 24 }}>
        {/* Waterfall chart */}
        <div className="chart-card" style={{ marginBottom: 0 }}>
          <div className="chart-title">Revenue Waterfall — {s.period}</div>
          <div className="chart-subtitle">Program revenues · Vela fee · net customer payment</div>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={WATERFALL_DATA} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                tickLine={false}
                axisLine={false}
                angle={-35}
                textAnchor="end"
                interval={0}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="#e2e8f0" />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {WATERFALL_DATA.map((entry, i) => (
                  <Cell key={i} fill={entry.fill} fillOpacity={0.85} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Settlement status */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="section-title">Settlement Status</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ background: 'var(--success-bg)', border: '1px solid var(--success-border)', borderRadius: 8, padding: '14px 16px' }}>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--success)', marginBottom: 4 }}>Settled</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--success)' }}>${(totalSettled / 1000).toFixed(1)}k</div>
              <div style={{ fontSize: 12, color: 'var(--success)', marginTop: 2 }}>
                {SETTLEMENT_LINES.filter(l => l.status === 'settled').length} lines
              </div>
            </div>
            <div style={{ background: 'var(--warning-bg)', border: '1px solid var(--warning-border)', borderRadius: 8, padding: '14px 16px' }}>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--warning)', marginBottom: 4 }}>Pending</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--warning)' }}>${(totalPending / 1000).toFixed(1)}k</div>
              <div style={{ fontSize: 12, color: 'var(--warning)', marginTop: 2 }}>
                {SETTLEMENT_LINES.filter(l => l.status === 'pending').length} lines
              </div>
            </div>
          </div>

          <div className="divider" />

          <div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>Performance M&V</div>
            {[
              { label: 'Obligation delivery', pct: s.deliveryFraction * 100, color: '#16a34a' },
              { label: 'Site availability',   pct: s.availabilityFraction * 100, color: '#2563eb' },
              { label: 'Obligations met',     pct: s.obligationsMetPct, color: '#7c3aed' },
            ].map(item => (
              <div key={item.label} style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                  <span style={{ color: 'var(--text-muted)' }}>{item.label}</span>
                  <span style={{ fontWeight: 600 }}>{item.pct.toFixed(1)}%</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${item.pct}%`, background: item.color }} />
                </div>
              </div>
            ))}
          </div>

          <div style={{ background: 'var(--primary-light)', borderRadius: 8, padding: '12px 14px' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--primary)', marginBottom: 2 }}>Performance Bonus Earned</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--primary)' }}>
              +${s.performanceBonus.toLocaleString()}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              Delivery {Math.round(s.deliveryFraction * 100)}% ≥ 95% threshold
            </div>
          </div>
        </div>
      </div>

      {/* Settlement lines table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px 12px', borderBottom: '1px solid var(--border-light)' }}>
          <div className="section-title">Settlement Lines — {s.period}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            CAISO-cleared programs · ISO-reported volumes · settlement prices
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th>Category</th>
              <th>Program</th>
              <th style={{ textAlign: 'right' }}>Volume (MWh)</th>
              <th style={{ textAlign: 'right' }}>Price ($/MWh)</th>
              <th style={{ textAlign: 'right' }}>Revenue</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {SETTLEMENT_LINES.map(line => (
              <tr key={line.id}>
                <td style={{ fontWeight: 500 }}>{line.category}</td>
                <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{line.program}</td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {line.volumeMwh > 0 ? line.volumeMwh.toFixed(1) : '—'}
                </td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: 'var(--text-muted)' }}>
                  {line.price > 0 ? `$${line.price.toFixed(2)}` : '—'}
                </td>
                <td style={{ textAlign: 'right', fontWeight: 600, fontVariantNumeric: 'tabular-nums', color: 'var(--success)' }}>
                  ${line.revenue.toLocaleString()}
                </td>
                <td>{statusBadge(line.status)}</td>
              </tr>
            ))}
            <tr style={{ background: '#f8fafc' }}>
              <td colSpan={4} style={{ fontWeight: 700, color: 'var(--text-muted)', fontSize: 12 }}>TOTAL GROSS REVENUE</td>
              <td style={{ textAlign: 'right', fontWeight: 700, fontSize: 15 }}>
                ${s.grossRevenue.toLocaleString()}
              </td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

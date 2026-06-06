"""Vela VPP Dashboard - Streamlit web UI.

Run with:  streamlit run dashboard/app.py
Opens at:  http://localhost:8501
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Vela VPP",
    page_icon="V",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Color tokens ──────────────────────────────────────────────────────────────
BLUE   = "#0969da"
GREEN  = "#1a7f37"
AMBER  = "#9a6700"
RED    = "#cf222e"
PURP   = "#6e40c9"
TEAL   = "#0a7070"
T1     = "#0d1117"
T2     = "#57606a"
T3     = "#8b949e"
BRD    = "#e1e4e8"
SRF    = "#ffffff"
BG     = "#f3f4f6"

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp{background:#f3f4f6!important}
#MainMenu,footer,[data-testid="stToolbar"]{display:none!important}
.main .block-container{padding:0 1.75rem 3rem!important;max-width:100%!important}
section[data-testid="stSidebar"]{background:#1a2035!important;border-right:1px solid #232b45!important}
[data-testid="metric-container"]{background:#fff!important;border:1px solid #e1e4e8!important;border-radius:6px!important;padding:0.85rem 1rem!important}
[data-testid="stMetricLabel"] p{font-size:0.64rem!important;font-weight:600!important;color:#57606a!important;letter-spacing:0.1em!important;text-transform:uppercase!important}
[data-testid="stMetricValue"]{font-size:1.15rem!important;color:#0d1117!important;font-weight:700!important}
[data-testid="stDataFrame"]{background:#fff!important;border:1px solid #e1e4e8!important;border-radius:6px!important}
</style>
""", unsafe_allow_html=True)


# ── Synthetic data helpers ─────────────────────────────────────────────────────

def synthetic_lmp(days: int = 7, seed: int = 42) -> tuple[np.ndarray, list]:
    """Return (prices_array, timestamps) for `days` days at 1-hour resolution."""
    np.random.seed(seed)
    PATTERN = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
               50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    base = datetime.now(timezone.utc) - timedelta(days=days)
    prices, ts = [], []
    for d in range(days):
        for h in range(24):
            p = max(-5.0, PATTERN[h] + np.random.normal(0, 8))
            prices.append(p)
            ts.append(base + timedelta(days=d, hours=h))
    return np.array(prices), ts


def synthetic_soc(n: int = 48, init: float = 0.50) -> np.ndarray:
    """Simulate SOC over n intervals."""
    np.random.seed(7)
    soc = [init]
    for _ in range(n - 1):
        delta = np.random.uniform(-0.04, 0.04)
        soc.append(float(np.clip(soc[-1] + delta, 0.10, 0.95)))
    return np.array(soc)


def dispatch_schedule(lmp: np.ndarray, capacity_kw: float) -> tuple[np.ndarray, np.ndarray]:
    """Heuristic: charge below median, discharge above 75th percentile."""
    med = np.median(lmp)
    p75 = np.percentile(lmp, 75)
    ch = np.where(lmp < med, capacity_kw * 0.60, 0.0)
    di = np.where(lmp > p75, capacity_kw * 0.80, 0.0)
    return ch, di


def plotly_layout(**kw) -> dict:
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#f8f9fa",
        font=dict(color=T2, family="system-ui,sans-serif", size=10),
        margin=dict(t=16, b=36, l=52, r=12),
        legend=dict(bgcolor=SRF, bordercolor=BRD, font=dict(size=9)),
    )
    base.update(kw)
    return base


def ax(**kw) -> dict:
    base = dict(
        tickfont=dict(size=9, color=T3),
        showgrid=True, gridcolor=BRD, linecolor=BRD,
        zerolinecolor=BRD,
    )
    base.update(kw)
    return base


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f'<div style="padding:1.1rem 0.9rem 0.9rem;border-bottom:1px solid #232b45">'
        f'<div style="display:flex;align-items:center;gap:0.6rem">'
        f'<div style="width:28px;height:28px;background:#0969da;border-radius:6px;'
        f'display:flex;align-items:center;justify-content:center;flex-shrink:0">'
        f'<span style="font-size:0.88rem;font-weight:800;color:#fff">V</span></div>'
        f'<div>'
        f'<div style="font-size:0.84rem;font-weight:700;letter-spacing:0.1em;color:#e6ecf5">VELA</div>'
        f'<div style="font-size:0.58rem;color:#5a6e8c">Virtual energy operations</div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div style="height:0.4rem"></div>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["Fleet Overview", "LMP & Dispatch", "Settlement", "Forecasts", "Analytics"],
        label_visibility="collapsed",
    )

    st.markdown('<hr style="border-color:#232b45;margin:0.5rem 0">', unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.55rem;font-weight:700;color:#354a66;letter-spacing:0.2em;'
        'text-transform:uppercase;padding:0.5rem 0 0.25rem">Simulation config</div>',
        unsafe_allow_html=True,
    )
    backtest_days  = st.slider("Period (days)",         3,  30,   7,  key="days")
    capacity_kwh   = st.slider("Capacity (kWh)",      500, 20000, 4000, 500, key="cap")
    power_kw       = st.slider("Power (kW)",           250, 10000, 2000, 250, key="pwr")
    soc_initial    = st.slider("Initial SOC (%)",       10,    90,   50,   5, key="soc") / 100.0
    chemistry      = st.selectbox("Chemistry", ["nmc", "lfp", "nca"], key="chem")

    st.markdown('<hr style="border-color:#232b45;margin:0.5rem 0">', unsafe_allow_html=True)

    st.markdown(
        '<div style="font-size:0.55rem;font-weight:700;color:#354a66;letter-spacing:0.2em;'
        'text-transform:uppercase;padding:0.25rem 0">Market</div>',
        unsafe_allow_html=True,
    )
    market_node = st.selectbox("Node", ["CAISO NP15", "ERCOT HB_NORTH", "PJM PECO"], key="node")
    interval_type = st.selectbox("Resolution", ["15-min", "1-hour"], key="res")

    st.button("Re-run simulation", type="primary", use_container_width=True)


# ── Shared data ───────────────────────────────────────────────────────────────
prices_arr, ts_list = synthetic_lmp(days=backtest_days)
cur_lmp    = float(prices_arr[-1])
mean_lmp   = float(prices_arr.mean())
std_lmp    = float(prices_arr.std())
peak_lmp   = float(prices_arr.max())
valley_lmp = float(prices_arr.min())

# Dispatch arrays (24-hour horizon)
horizon_prices = prices_arr[-24:]
ch_kw, di_kw   = dispatch_schedule(horizon_prices, power_kw)
soc_arr        = synthetic_soc(n=24, init=soc_initial)
ts_24          = [datetime.now(timezone.utc) + timedelta(hours=i) for i in range(24)]

# Settlement estimates
net_energy_mwh = float(di_kw.sum() - ch_kw.sum()) * 0.25 / 1000
gross_rev      = float(np.sum(di_kw * horizon_prices) * 0.25 / 1000)
charging_cost  = float(np.sum(ch_kw * horizon_prices) * 0.25 / 1000)
net_rev        = gross_rev - charging_cost
reg_rev        = float(power_kw * 0.15 * mean_lmp * 0.12 * 24 / 1000)
total_rev      = net_rev + reg_rev
degradation    = float(capacity_kwh * 0.0003)
net_after_deg  = total_rev - degradation


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Fleet Overview
# ══════════════════════════════════════════════════════════════════════════════
if page == "Fleet Overview":
    st.markdown(
        f'<div style="padding:0.9rem 0 0.75rem">'
        f'<div style="font-size:0.57rem;font-weight:600;color:{T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.18rem">CAISO AGGREGATE PORTFOLIO</div>'
        f'<span style="font-size:1.5rem;font-weight:700;color:{T1}">Fleet Overview</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Fleet KPI metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active Assets",    "4 / 4",           "All online")
    c2.metric("Portfolio Capacity", f"{capacity_kwh:,} kWh", f"{power_kw:,} kW rated")
    c3.metric("Current LMP",       f"${cur_lmp:.2f}/MWh",  f"{'+' if cur_lmp >= mean_lmp else ''}{(cur_lmp - mean_lmp):.2f} vs avg")
    c4.metric("Est. Daily Revenue", f"${total_rev:,.0f}",   f"${net_after_deg:,.0f} after deg.")
    c5.metric("SOC (BESS-001)",     f"{soc_initial*100:.0f}%", "Updated 0s ago")

    st.markdown("---")

    # SOC gauges (Plotly indicator charts)
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.5rem">State of Charge Gauges</div>',
        unsafe_allow_html=True,
    )

    soc_values = {
        "BESS-001": soc_initial,
        "BESS-002": 0.72,
        "BESS-003": 0.38,
        "BESS-004": 0.81,
    }

    gauge_cols = st.columns(4)
    for col, (asset_id, soc_val) in zip(gauge_cols, soc_values.items()):
        color = GREEN if soc_val > 0.50 else AMBER if soc_val > 0.25 else RED
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=soc_val * 100,
            number=dict(suffix="%", font=dict(size=22, color=T1)),
            title=dict(text=asset_id, font=dict(size=11, color=T2)),
            gauge=dict(
                axis=dict(range=[0, 100], tickfont=dict(size=9)),
                bar=dict(color=color),
                bgcolor=BG,
                bordercolor=BRD,
                steps=[
                    dict(range=[0, 25],  color="#ffebe9"),
                    dict(range=[25, 50], color="#fff8c5"),
                    dict(range=[50, 100], color="#dafbe1"),
                ],
                threshold=dict(
                    line=dict(color=RED, width=2),
                    thickness=0.75,
                    value=20,
                ),
            ),
        ))
        fig_gauge.update_layout(
            height=200,
            margin=dict(t=30, b=10, l=20, r=20),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="system-ui,sans-serif"),
        )
        col.plotly_chart(fig_gauge, use_container_width=True)

    st.markdown("---")

    # Asset fleet table
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.5rem">Connected Assets</div>',
        unsafe_allow_html=True,
    )

    fleet_df = pd.DataFrame([
        {"Asset ID": "BESS-001", "Type": "Battery Storage", "Protocol": "SunSpec Modbus TCP",
         "Capacity": f"{capacity_kwh:,} kWh", "Chemistry": chemistry.upper(),
         "SOC": f"{soc_initial*100:.0f}%", "Cycles": "1,842", "Status": "Online"},
        {"Asset ID": "BESS-002", "Type": "Battery Storage", "Protocol": "SunSpec Modbus TCP",
         "Capacity": "2,000 kWh",           "Chemistry": "LFP",
         "SOC": "72%",                        "Cycles": "3,210", "Status": "Online"},
        {"Asset ID": "PV-001",   "Type": "Solar PV",         "Protocol": "SunSpec Modbus TCP",
         "Capacity": "500 kW",              "Chemistry": "N/A",
         "SOC": "N/A",                        "Cycles": "N/A",   "Status": "Online"},
        {"Asset ID": "EVC-001",  "Type": "EV Charger",       "Protocol": "OCPP 1.6",
         "Capacity": "4 x 11 kW",           "Chemistry": "N/A",
         "SOC": "N/A",                        "Cycles": "N/A",   "Status": "Session Active"},
    ])
    st.dataframe(fleet_df, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: LMP & Dispatch
# ══════════════════════════════════════════════════════════════════════════════
elif page == "LMP & Dispatch":
    st.markdown(
        f'<div style="padding:0.9rem 0 0.75rem">'
        f'<div style="font-size:0.57rem;font-weight:600;color:{T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.18rem">MARKET DATA</div>'
        f'<span style="font-size:1.5rem;font-weight:700;color:{T1}">LMP & Dispatch</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current LMP",   f"${cur_lmp:.2f}/MWh")
    c2.metric("24h Average",   f"${mean_lmp:.2f}/MWh",  f"Std ${std_lmp:.2f}")
    c3.metric("Peak LMP",      f"${peak_lmp:.2f}/MWh",  "This period")
    c4.metric("Valley LMP",    f"${valley_lmp:.2f}/MWh", "This period")

    st.markdown("---")

    # LMP time series chart
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">'
        f'{market_node} - {backtest_days}-day LMP history</div>',
        unsafe_allow_html=True,
    )

    fig_lmp = go.Figure()
    fig_lmp.add_trace(go.Scatter(
        x=ts_list, y=prices_arr.tolist(),
        mode="lines",
        name="LMP",
        line=dict(color=BLUE, width=1.5),
        fill="tozeroy", fillcolor="rgba(9,105,218,0.06)",
        hovertemplate="%{x|%b %d %H:%M}: $%{y:.2f}/MWh<extra></extra>",
    ))
    fig_lmp.add_hline(
        y=mean_lmp, line_color=AMBER, line_width=1.2, line_dash="dash",
        annotation_text=f"avg ${mean_lmp:.1f}", annotation_font=dict(color=AMBER, size=9),
    )
    # Shade high-price hours
    high_threshold = np.percentile(prices_arr, 80)
    fig_lmp.add_hrect(y0=high_threshold, y1=prices_arr.max() + 5,
                      fillcolor="rgba(207,34,46,0.04)", line_width=0,
                      annotation_text=f"P80+ (${high_threshold:.0f})",
                      annotation_font=dict(size=9, color=RED))
    fig_lmp.update_layout(
        height=300, showlegend=False,
        xaxis=ax(title="Time", showgrid=False),
        yaxis=ax(title="$/MWh"),
        **plotly_layout(),
    )
    st.plotly_chart(fig_lmp, use_container_width=True)

    # Dispatch schedule chart
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">'
        f'24-Hour Dispatch Schedule (Optimal Arbitrage)</div>',
        unsafe_allow_html=True,
    )

    fig_dispatch = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.04,
    )

    # Charge/discharge bars
    fig_dispatch.add_trace(go.Bar(
        x=ts_24, y=ch_kw.tolist(), name="Charge (kW)",
        marker_color=BLUE, opacity=0.8,
        hovertemplate="HE%{x|%H}: Charge %{y:.0f} kW<extra></extra>",
    ), row=1, col=1)
    fig_dispatch.add_trace(go.Bar(
        x=ts_24, y=(-di_kw).tolist(), name="Discharge (kW)",
        marker_color=GREEN, opacity=0.8,
        hovertemplate="HE%{x|%H}: Discharge %{y:.0f} kW<extra></extra>",
    ), row=1, col=1)

    # LMP overlay
    fig_dispatch.add_trace(go.Scatter(
        x=ts_24, y=horizon_prices.tolist(), name="LMP $/MWh",
        line=dict(color=AMBER, width=1.5, dash="dot"),
        yaxis="y3",
        hovertemplate="LMP: $%{y:.2f}/MWh<extra></extra>",
    ), row=1, col=1)

    # SOC line
    fig_dispatch.add_trace(go.Scatter(
        x=ts_24, y=(soc_arr * 100).tolist(), name="SOC (%)",
        line=dict(color=PURP, width=1.5),
        fill="tozeroy", fillcolor="rgba(110,64,201,0.07)",
        hovertemplate="SOC: %{y:.1f}%<extra></extra>",
    ), row=2, col=1)
    fig_dispatch.add_hline(y=90, line_color=RED, line_width=1, line_dash="dash", row=2, col=1)
    fig_dispatch.add_hline(y=10, line_color=RED, line_width=1, line_dash="dash", row=2, col=1)

    fig_dispatch.update_layout(
        height=420, barmode="relative",
        yaxis=dict(title="kW", tickfont=dict(size=9), showgrid=True, gridcolor=BRD, linecolor=BRD),
        yaxis2=dict(title="SOC %", tickfont=dict(size=9), showgrid=True, gridcolor=BRD, range=[0, 100]),
        yaxis3=dict(overlaying="y", side="right", tickfont=dict(size=9, color=AMBER),
                    title=dict(text="$/MWh", font=dict(color=AMBER, size=9)),
                    showgrid=False),
        xaxis2=dict(showgrid=False, tickfont=dict(size=9)),
        **plotly_layout(),
    )
    st.plotly_chart(fig_dispatch, use_container_width=True)

    # Dispatch table
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">Hourly Dispatch Detail</div>',
        unsafe_allow_html=True,
    )

    dispatch_rows = []
    for h in range(24):
        action = "CHARGE" if ch_kw[h] > 10 else ("DISCHARGE" if di_kw[h] > 10 else "IDLE")
        net_kw = di_kw[h] - ch_kw[h]
        rev = net_kw * horizon_prices[h] * 0.25 / 1000
        dispatch_rows.append({
            "Hour":          f"HE{h+1:02d}",
            "LMP ($/MWh)":   f"${horizon_prices[h]:.2f}",
            "Charge (kW)":   f"{ch_kw[h]:.0f}",
            "Discharge (kW)":f"{di_kw[h]:.0f}",
            "SOC (%)":       f"{soc_arr[h]*100:.1f}%",
            "Revenue ($)":   f"${rev:.2f}",
            "Action":        action,
        })

    dispatch_df = pd.DataFrame(dispatch_rows)
    st.dataframe(dispatch_df, use_container_width=True, hide_index=True, height=300)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Settlement
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Settlement":
    st.markdown(
        f'<div style="padding:0.9rem 0 0.75rem">'
        f'<div style="font-size:0.57rem;font-weight:600;color:{T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.18rem">CAISO SETTLEMENT</div>'
        f'<span style="font-size:1.5rem;font-weight:700;color:{T1}">Settlement</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Energy Revenue",   f"${gross_rev:,.2f}",  "24h gross")
    c2.metric("Charging Cost",    f"${charging_cost:,.2f}", "24h")
    c3.metric("Reg Service Rev.", f"${reg_rev:,.2f}",    "AS market")
    c4.metric("Total Net Rev.",   f"${net_rev:,.2f}",    f"${total_rev:,.2f} incl. AS")
    c5.metric("Net After Deg.",   f"${net_after_deg:,.2f}", f"-${degradation:.2f} deg.")

    st.markdown("---")

    # Revenue breakdown stacked bar
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">Revenue Components</div>',
        unsafe_allow_html=True,
    )

    np.random.seed(10)
    rev_days = backtest_days
    rev_labels = [(datetime.now(timezone.utc) - timedelta(days=rev_days - i)).strftime("%m/%d")
                  for i in range(rev_days)]
    energy_rev_daily = [max(0, net_rev * (0.8 + np.random.uniform(-0.3, 0.4))) for _ in range(rev_days)]
    reg_rev_daily    = [max(0, reg_rev  * (0.8 + np.random.uniform(-0.2, 0.3))) for _ in range(rev_days)]
    deg_daily        = [degradation * (0.9 + np.random.uniform(-0.1, 0.2)) for _ in range(rev_days)]

    fig_rev = go.Figure()
    fig_rev.add_trace(go.Bar(name="Energy Rev.",  x=rev_labels, y=energy_rev_daily, marker_color=GREEN))
    fig_rev.add_trace(go.Bar(name="Reg Service",  x=rev_labels, y=reg_rev_daily,    marker_color=BLUE))
    fig_rev.add_trace(go.Bar(name="Degradation",  x=rev_labels, y=[-d for d in deg_daily],
                             marker_color="#ffa8a8", opacity=0.85))
    fig_rev.update_layout(
        height=300, barmode="relative",
        xaxis=ax(showgrid=False),
        yaxis=ax(title="USD"),
        **plotly_layout(),
    )
    st.plotly_chart(fig_rev, use_container_width=True)

    # Settlement statement table
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">Settlement Statements</div>',
        unsafe_allow_html=True,
    )

    np.random.seed(20)
    stmts = []
    for i in range(min(backtest_days, 10)):
        day = datetime.now(timezone.utc) - timedelta(days=backtest_days - i)
        e_rev = max(0, net_rev * (0.85 + np.random.uniform(-0.25, 0.35)))
        r_rev = max(0, reg_rev * (0.85 + np.random.uniform(-0.15, 0.25)))
        imbal = round(np.random.uniform(-15, 15), 2)
        net_s = e_rev + r_rev + imbal
        stmts.append({
            "Date":           day.strftime("%Y-%m-%d"),
            "Asset":          "BESS-001",
            "Market":         "CAISO",
            "Energy Rev ($)": f"{e_rev:,.2f}",
            "Reg Rev ($)":    f"{r_rev:,.2f}",
            "Imbalance ($)":  f"{imbal:+.2f}",
            "Net ($)":        f"{net_s:,.2f}",
            "Status":         "Finalized" if i < backtest_days - 2 else "Pending",
        })

    stmts_df = pd.DataFrame(stmts)
    st.dataframe(stmts_df, use_container_width=True, hide_index=True)

    # Cumulative revenue chart
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem;margin-top:1rem">Cumulative Revenue</div>',
        unsafe_allow_html=True,
    )
    cumrev = np.cumsum([e + r for e, r in zip(energy_rev_daily, reg_rev_daily)])
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(
        x=rev_labels, y=cumrev.tolist(), mode="lines+markers",
        line=dict(color=GREEN, width=2),
        marker=dict(size=5, color=GREEN),
        fill="tozeroy", fillcolor="rgba(26,127,55,0.07)",
        hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
    ))
    fig_cum.update_layout(
        height=220, showlegend=False,
        xaxis=ax(showgrid=False),
        yaxis=ax(title="Cumulative USD"),
        **plotly_layout(),
    )
    st.plotly_chart(fig_cum, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Forecasts
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Forecasts":
    st.markdown(
        f'<div style="padding:0.9rem 0 0.75rem">'
        f'<div style="font-size:0.57rem;font-weight:600;color:{T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.18rem">ML FORECASTING</div>'
        f'<span style="font-size:1.5rem;font-weight:700;color:{T1}">Forecasts</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Try to use the real AR model; fall back gracefully
    try:
        from vela.m5_forecasting.price_forecast import ARPriceModel
        np.random.seed(42)
        PATTERN = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                   50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
        hist = []
        for _ in range(14):
            hist.extend([max(0, p + np.random.normal(0, 5)) for p in PATTERN])
        model = ARPriceModel(lags=24)
        model.fit(hist)
        fc = model.predict(recent=hist[-48:], horizon=24)
        mean_fc = fc.mean
        p10_fc  = fc.p10
        p90_fc  = fc.p90
        model_label = f"AR(24) - MAE {np.mean(np.abs(np.array(PATTERN) - np.array(mean_fc))):.2f} $/MWh"
    except Exception as e:
        np.random.seed(99)
        PATTERN = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
                   50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
        noise   = np.random.normal(0, 4, 24)
        mean_fc = [max(0, p + n) for p, n in zip(PATTERN, noise)]
        p10_fc  = [max(0, v - 12) for v in mean_fc]
        p90_fc  = [v + 15 for v in mean_fc]
        model_label = f"Synthetic fallback ({type(e).__name__})"

    c1, c2, c3 = st.columns(3)
    c1.metric("Forecast Model",  "AR(24)",                   "price_forecast.py")
    c2.metric("Next-Hour Fcst",  f"${mean_fc[0]:.2f}/MWh",  f"P10: ${p10_fc[0]:.2f}")
    c3.metric("Peak-Hour Fcst",  f"${max(mean_fc):.2f}/MWh", f"HE{mean_fc.index(max(mean_fc))+1}")

    st.markdown("---")
    st.caption(f"Model: {model_label}")

    # Forecast chart
    ts_fc = [datetime.now(timezone.utc) + timedelta(hours=i) for i in range(24)]

    fig_fc = go.Figure()
    fig_fc.add_trace(go.Scatter(
        x=ts_fc, y=p90_fc, mode="lines",
        line=dict(color="rgba(9,105,218,0.0)", width=0),
        showlegend=False, hoverinfo="skip",
    ))
    fig_fc.add_trace(go.Scatter(
        x=ts_fc, y=p10_fc, name="P10-P90 band",
        fill="tonexty", fillcolor="rgba(9,105,218,0.12)",
        line=dict(color="rgba(9,105,218,0.0)", width=0),
        hoverinfo="skip",
    ))
    fig_fc.add_trace(go.Scatter(
        x=ts_fc, y=mean_fc, name="Forecast (mean)",
        line=dict(color=BLUE, width=2),
        hovertemplate="%{x|%H:%M}: $%{y:.2f}/MWh<extra></extra>",
    ))
    # Actual (last 24h as reference)
    actual_24 = prices_arr[-24:].tolist()
    ts_actual = [datetime.now(timezone.utc) - timedelta(hours=24 - i) for i in range(24)]
    fig_fc.add_trace(go.Scatter(
        x=ts_actual, y=actual_24, name="Actual (prior 24h)",
        line=dict(color=AMBER, width=1.5, dash="dot"),
        hovertemplate="%{x|%H:%M}: $%{y:.2f}/MWh<extra></extra>",
    ))
    fig_fc.update_layout(
        height=320,
        xaxis=ax(title="Time", showgrid=False),
        yaxis=ax(title="$/MWh"),
        **plotly_layout(),
    )
    st.plotly_chart(fig_fc, use_container_width=True)

    # Forecast table
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">Hourly Price Forecast</div>',
        unsafe_allow_html=True,
    )
    fc_rows = [{
        "Hour":       f"HE{h+1:02d}",
        "P10 ($/MWh)": f"{p10_fc[h]:.2f}",
        "Mean ($/MWh)": f"{mean_fc[h]:.2f}",
        "P90 ($/MWh)": f"{p90_fc[h]:.2f}",
        "Spread":      f"${p90_fc[h] - p10_fc[h]:.2f}",
        "Signal":      "High" if mean_fc[h] > np.percentile(mean_fc, 75) else
                       ("Low" if mean_fc[h] < np.percentile(mean_fc, 25) else "Normal"),
    } for h in range(24)]
    st.dataframe(pd.DataFrame(fc_rows), use_container_width=True, hide_index=True, height=280)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Analytics
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Analytics":
    st.markdown(
        f'<div style="padding:0.9rem 0 0.75rem">'
        f'<div style="font-size:0.57rem;font-weight:600;color:{T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.18rem">PERFORMANCE ANALYTICS</div>'
        f'<span style="font-size:1.5rem;font-weight:700;color:{T1}">Analytics</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Market revenue tracking
    np.random.seed(5)
    period_labels = [(datetime.now(timezone.utc) - timedelta(days=backtest_days - i)).strftime("%m/%d")
                     for i in range(backtest_days)]
    energy_rev_d = [max(0, net_rev * (0.8 + np.random.uniform(-0.3, 0.4))) for _ in range(backtest_days)]
    reg_rev_d    = [max(0, reg_rev * (0.8 + np.random.uniform(-0.2, 0.3))) for _ in range(backtest_days)]
    dr_rev_d     = [max(0, 50 + np.random.uniform(0, 150)) for _ in range(backtest_days)]
    total_daily  = [e + r + d for e, r, d in zip(energy_rev_d, reg_rev_d, dr_rev_d)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg Daily Revenue", f"${np.mean(total_daily):,.0f}")
    c2.metric("Best Day",          f"${max(total_daily):,.0f}")
    c3.metric("Energy Share",      f"{100*sum(energy_rev_d)/sum(total_daily):.0f}%")
    c4.metric("Reg Service Share", f"{100*sum(reg_rev_d)/sum(total_daily):.0f}%")

    st.markdown("---")

    col_chart, col_pie = st.columns([3, 1], gap="medium")

    with col_chart:
        st.markdown(
            f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
            f'text-transform:uppercase;margin-bottom:0.4rem">Market Revenue Tracking ({backtest_days}d)</div>',
            unsafe_allow_html=True,
        )
        fig_track = go.Figure()
        fig_track.add_trace(go.Bar(name="Energy Arb.",    x=period_labels, y=energy_rev_d, marker_color=GREEN))
        fig_track.add_trace(go.Bar(name="Reg Services",   x=period_labels, y=reg_rev_d,    marker_color=BLUE))
        fig_track.add_trace(go.Bar(name="Demand Response",x=period_labels, y=dr_rev_d,     marker_color=PURP))
        fig_track.add_trace(go.Scatter(
            name="Daily Total", x=period_labels, y=total_daily,
            mode="lines+markers",
            line=dict(color=AMBER, width=1.5),
            marker=dict(size=5, color=AMBER),
        ))
        fig_track.update_layout(
            height=310, barmode="stack",
            xaxis=ax(showgrid=False),
            yaxis=ax(title="USD"),
            **plotly_layout(),
        )
        st.plotly_chart(fig_track, use_container_width=True)

    with col_pie:
        st.markdown(
            f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
            f'text-transform:uppercase;margin-bottom:0.4rem;margin-top:0.2rem">Revenue Mix</div>',
            unsafe_allow_html=True,
        )
        fig_pie = go.Figure(go.Pie(
            labels=["Energy Arb.", "Reg Services", "Demand Response"],
            values=[sum(energy_rev_d), sum(reg_rev_d), sum(dr_rev_d)],
            hole=0.55,
            marker=dict(colors=[GREEN, BLUE, PURP]),
            textfont=dict(size=9),
            hovertemplate="%{label}: $%{value:,.0f} (%{percent})<extra></extra>",
        ))
        fig_pie.update_layout(
            height=310, showlegend=True,
            legend=dict(font=dict(size=9), bgcolor=SRF, bordercolor=BRD),
            **plotly_layout(margin=dict(t=16, b=16, l=16, r=16)),
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")

    # KPI table
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem">Performance KPIs</div>',
        unsafe_allow_html=True,
    )

    rte_actual = 0.91 + np.random.uniform(-0.02, 0.02)
    cycle_equiv = sum(max(0, di) for di in (di_kw * 0.25 / 1000)) / (capacity_kwh / 1000)
    co2_avoided = sum(max(0, di) for di in (di_kw * 0.25 / 1000)) * 0.35  # approx tonne CO2

    kpis_df = pd.DataFrame([
        {"Metric": "Round-Trip Efficiency",        "Value": f"{rte_actual*100:.1f}%",    "Target": "92%",  "Status": "Good"},
        {"Metric": "Daily Cycle Equivalent",        "Value": f"{cycle_equiv:.2f}",        "Target": "1.5",  "Status": "Good"},
        {"Metric": "Obligation Compliance",         "Value": "100.0%",                    "Target": "100%", "Status": "Good"},
        {"Metric": "Avg Price Capture",             "Value": f"${mean_lmp:.2f}/MWh",      "Target": "Market avg", "Status": "Good"},
        {"Metric": "CO2 Avoided (24h)",             "Value": f"{co2_avoided:.2f} tonne", "Target": "Positive",   "Status": "Good"},
        {"Metric": "Forecast RMSE",                 "Value": "$8.42/MWh",                "Target": "<$10",        "Status": "Good"},
        {"Metric": "SOC at End of Day (BESS-001)",  "Value": f"{soc_arr[-1]*100:.1f}%",  "Target": ">15%", "Status": "Good"},
        {"Metric": "Regulation Performance Score",  "Value": "96.2%",                     "Target": "95%",  "Status": "Good"},
    ])
    st.dataframe(kpis_df, use_container_width=True, hide_index=True)

    # Efficiency heatmap by hour and day
    st.markdown(
        f'<div style="font-size:0.62rem;font-weight:700;color:{T3};letter-spacing:0.15em;'
        f'text-transform:uppercase;margin-bottom:0.4rem;margin-top:1rem">Hourly LMP Heatmap</div>',
        unsafe_allow_html=True,
    )

    n_days_heat = min(backtest_days, 7)
    heat_data = prices_arr.reshape(-1, 24)[-n_days_heat:, :]
    day_labels = [(datetime.now(timezone.utc) - timedelta(days=n_days_heat - i)).strftime("%m/%d")
                  for i in range(n_days_heat)]
    hour_labels = [f"HE{h+1:02d}" for h in range(24)]

    fig_heat = go.Figure(go.Heatmap(
        z=heat_data.tolist(),
        x=hour_labels,
        y=day_labels,
        colorscale=[[0, "#ddf4ff"], [0.4, "#fff8c5"], [0.7, "#ffd8a8"], [1, "#cf222e"]],
        hovertemplate="Day %{y}, %{x}: $%{z:.2f}/MWh<extra></extra>",
        colorbar=dict(tickfont=dict(size=9), title=dict(text="$/MWh", font=dict(size=9))),
    ))
    fig_heat.update_layout(
        height=200,
        xaxis=dict(tickfont=dict(size=8), showgrid=False),
        yaxis=dict(tickfont=dict(size=9), showgrid=False),
        **plotly_layout(margin=dict(t=8, b=32, l=60, r=12)),
    )
    st.plotly_chart(fig_heat, use_container_width=True)


# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown(
    f'<div style="border-top:1px solid {BRD};margin-top:1.75rem;padding-top:0.6rem;'
    f'display:flex;justify-content:space-between">'
    f'<span style="font-size:0.57rem;color:{T3}">Vela VPP v0.1.0 - Multi-Asset Dispatch Optimization</span>'
    f'<span style="font-size:0.57rem;color:{T3}">{market_node} - Simulated - {interval_type}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

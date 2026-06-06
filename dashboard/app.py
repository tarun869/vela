"""Vela VPP Dashboard — Streamlit web UI.

Run with:  streamlit run dashboard/app.py
Opens at:  http://localhost:8501
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.backtest.run_backtest import (
    BacktestConfig,
    _generate_synthetic_prices,
    run_myopic_revenue_max,
    run_rule_based,
    run_single_objective_milp,
    run_vela_full,
)
from vela.m3_assets.battery import BatteryAsset, BatteryConfig
from vela.m3_assets.pumped_hydro import build_bath_county_phs
from vela.m5_forecasting.scenario_reduction import generate_price_scenarios, k_medoids_reduce
from vela.m6_optimizer.milp import VelaOptimizer
from vela.m6_optimizer.stochastic_milp import (
    DeterministicEquivalent,
    ProgressiveHedging,
    SAAScenarioGenerator,
    StochasticBatteryProblem,
)
from vela.m6_optimizer.weights import ObjectiveWeights
from vela.m9_settlement.caiso_settlement import (
    CAISOFlexRampInterval,
    CAISOLMPInterval,
    CAISORegulationInterval,
    CAISOSettlementEngine,
    compute_caiso_convergence_bidding_pnl,
)

st.set_page_config(
    page_title="Vela VPP",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Color tokens ──────────────────────────────────────────────────────────────
_BG   = "#f3f4f6"
_SRF  = "#ffffff"
_BRD  = "#e1e4e8"
_BRD2 = "#d0d7de"
_T1   = "#0d1117"
_T2   = "#57606a"
_T3   = "#8b949e"

_SB   = "#1a2035"
_SBB  = "#232b45"
_SBT1 = "#e6ecf5"
_SBT2 = "#5a6e8c"

BLUE   = "#0969da"
GREEN  = "#1a7f37"
AMBER  = "#9a6700"
RED    = "#cf222e"
PURP   = "#6e40c9"
TEAL   = "#0a7070"

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
*,*::before,*::after{font-family:'Inter',system-ui,-apple-system,sans-serif!important}

/* Shell */
.stApp{background:#f3f4f6!important}
#MainMenu,footer,[data-testid="stToolbar"]{display:none!important}
.main .block-container{padding:0 1.75rem 3rem!important;max-width:100%!important;background:#f3f4f6!important}
[data-testid="stAppViewContainer"]>section.main{background:#f3f4f6!important}

/* Sidebar */
section[data-testid="stSidebar"]{background:#1a2035!important;border-right:1px solid #232b45!important;min-width:188px!important;max-width:188px!important}
section[data-testid="stSidebar"]>div:first-child{padding:0!important}
section[data-testid="stSidebar"] .block-container{padding:0!important}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:0!important}

/* Nav radio */
section[data-testid="stSidebar"] [data-testid="stRadio"]{padding:0!important;margin:0!important}
section[data-testid="stSidebar"] [data-testid="stRadio"]>label{display:none!important}
section[data-testid="stSidebar"] [data-testid="stRadio"]>div[role="radiogroup"]{display:flex!important;flex-direction:column!important;gap:0!important;padding:0.3rem 0!important}
section[data-testid="stSidebar"] [data-baseweb="radio"]{align-items:center!important;padding:0.5rem 0.9rem!important;cursor:pointer!important;border-left:2px solid transparent!important;margin:0!important;border-radius:0!important}
section[data-testid="stSidebar"] [data-baseweb="radio"]:hover{background:rgba(255,255,255,0.05)!important}
section[data-testid="stSidebar"] [data-baseweb="radio"]>div:first-child{display:none!important}
section[data-testid="stSidebar"] [data-baseweb="radio"]>div:last-child{padding:0!important}
section[data-testid="stSidebar"] [data-baseweb="radio"]>div:last-child p{font-size:0.74rem!important;color:#5a6e8c!important;font-weight:500!important;margin:0!important;letter-spacing:0.01em!important;line-height:1!important}
section[data-testid="stSidebar"] [data-baseweb="radio"][aria-checked="true"]{background:rgba(9,105,218,0.12)!important;border-left-color:#3b82f6!important}
section[data-testid="stSidebar"] [data-baseweb="radio"][aria-checked="true"]>div:last-child p{color:#e6ecf5!important;font-weight:600!important}

/* Sidebar widgets */
section[data-testid="stSidebar"] label p{font-size:0.62rem!important;color:#354a66!important;font-weight:400!important;text-transform:uppercase!important;letter-spacing:0.1em!important}
section[data-testid="stSidebar"] .stSlider{padding:0 0 0.25rem!important}
section[data-testid="stSidebar"] [data-baseweb="select"] div{background:#131c30!important;border-color:#232b45!important;color:#6e87ae!important;font-size:0.72rem!important}

/* Metrics */
[data-testid="metric-container"]{background:#fff!important;border:1px solid #e1e4e8!important;border-radius:6px!important;padding:0.85rem 1rem!important}
[data-testid="stMetricLabel"]{font-size:0.58rem!important;font-weight:600!important;color:#57606a!important;letter-spacing:0.14em!important;text-transform:uppercase!important}
[data-testid="stMetricValue"]{font-size:1.1rem!important;color:#0d1117!important;font-weight:700!important;font-variant-numeric:tabular-nums!important}

/* Buttons */
.stButton button[kind="primary"]{background:#1a7f37!important;border:1px solid #1a7f37!important;color:#fff!important;border-radius:4px!important;font-size:0.72rem!important;font-weight:600!important;padding:0.4rem 0.9rem!important}
.stButton button[kind="secondary"]{background:#fff!important;border:1px solid #d0d7de!important;color:#24292f!important;border-radius:4px!important;font-size:0.72rem!important;font-weight:500!important;padding:0.4rem 0.9rem!important}

/* Dataframe */
[data-testid="stDataFrame"]{background:#fff!important;border:1px solid #e1e4e8!important;border-radius:6px!important}
hr{border-color:#e1e4e8!important;margin:0.5rem 0!important}
</style>
""", unsafe_allow_html=True)


# ── HTML primitives ───────────────────────────────────────────────────────────

def badge(text: str, style: str = "default") -> str:
    palettes = {
        "green":   ("background:#dafbe1", "color:#1a7f37", "border:1px solid #aceebb"),
        "amber":   ("background:#fff8c5", "color:#9a6700", "border:1px solid #e8cf50"),
        "red":     ("background:#ffebe9", "color:#cf222e", "border:1px solid #ffcecb"),
        "blue":    ("background:#ddf4ff", "color:#0550ae", "border:1px solid #80ccff"),
        "grey":    ("background:#f1f3f5", "color:#444d56", "border:1px solid #d0d7de"),
        "default": ("background:#f1f3f5", "color:#444d56", "border:1px solid #d0d7de"),
    }
    bg, tc, bc = palettes.get(style, palettes["default"])
    return (
        f'<span style="{bg};{tc};{bc};font-size:0.64rem;font-weight:600;'
        f'padding:0.17rem 0.55rem;border-radius:2rem;white-space:nowrap;'
        f'letter-spacing:0.02em">{text}</span>'
    )


def topbar(interval: str, pct_ready: int, extra_badge: str = "") -> None:
    r_b = badge(f"{pct_ready}% ready", "green" if pct_ready >= 85 else "amber" if pct_ready >= 65 else "red")
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:flex-end;gap:0.6rem;'
        f'padding:0.65rem 0;border-bottom:1px solid {_BRD};margin-bottom:0">'
        f'<span style="font-size:0.68rem;color:{_T3};font-family:\'JetBrains Mono\',monospace">'
        f'Mock interval {interval}</span>{r_b}'
        f'{("<span>" + extra_badge + "</span>") if extra_badge else ""}'
        f'</div>',
        unsafe_allow_html=True,
    )


def page_heading(label: str, title: str) -> None:
    st.markdown(
        f'<div style="padding:0.9rem 0 0.85rem">'
        f'<div style="font-size:0.57rem;font-weight:600;color:{_T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.28rem">{label}</div>'
        f'<span style="font-size:1.55rem;font-weight:700;color:{_T1};line-height:1.1">'
        f'{title}</span></div>',
        unsafe_allow_html=True,
    )


def section_hdr(label: str, title: str, right: str = "") -> None:
    r_html = f'<div style="margin-left:auto">{right}</div>' if right else ""
    st.markdown(
        f'<div style="margin:1.1rem 0 0.8rem">'
        f'<div style="font-size:0.55rem;font-weight:600;color:{_T3};letter-spacing:0.2em;'
        f'text-transform:uppercase;margin-bottom:0.18rem">{label}</div>'
        f'<div style="display:flex;align-items:center">'
        f'<span style="font-size:0.95rem;font-weight:700;color:{_T1}">{title}</span>'
        f'{r_html}</div></div>',
        unsafe_allow_html=True,
    )


def kpi_icon_row(items: list[tuple]) -> None:
    """
    items: (icon_svg_path, label, value, sub, icon_bg, icon_fg)
    """
    n = len(items)
    cols = st.columns(n, gap="small")
    for col, (icon_d, label, value, sub, ibg, ifg) in zip(cols, items):
        with col:
            st.markdown(
                f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:7px;'
                f'padding:0.9rem 1rem;display:flex;gap:0.85rem;align-items:flex-start">'
                f'<div style="width:36px;height:36px;background:{ibg};border-radius:7px;'
                f'flex-shrink:0;display:flex;align-items:center;justify-content:center">'
                f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
                f'stroke="{ifg}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
                f'<path d="{icon_d}"/></svg></div>'
                f'<div style="min-width:0">'
                f'<div style="font-size:0.56rem;font-weight:600;color:{_T2};'
                f'letter-spacing:0.16em;text-transform:uppercase;margin-bottom:0.22rem">{label}</div>'
                f'<div style="font-size:1.15rem;font-weight:700;color:{_T1};'
                f'font-variant-numeric:tabular-nums;line-height:1.1;margin-bottom:0.1rem">{value}</div>'
                f'<div style="font-size:0.66rem;color:{_T3};line-height:1.3">{sub}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )


def score_donut_svg(score: int, size: int = 80) -> str:
    r, sw = 34, 7
    circ = 2 * 3.14159 * r
    dash = score / 100 * circ
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 80 80">'
        f'<circle cx="40" cy="40" r="{r}" fill="none" stroke="#e8edf2" stroke-width="{sw}"/>'
        f'<circle cx="40" cy="40" r="{r}" fill="none" stroke="#1a7f37" stroke-width="{sw}" '
        f'stroke-dasharray="{dash:.1f} {circ:.1f}" stroke-dashoffset="{circ*0.25:.1f}" '
        f'stroke-linecap="round"/>'
        f'<text x="40" y="37" text-anchor="middle" font-size="18" font-weight="700" '
        f'fill="#0d1117" font-family="Inter,sans-serif">{score}</text>'
        f'<text x="40" y="50" text-anchor="middle" font-size="8" fill="#8b949e" '
        f'font-family="Inter,sans-serif" font-weight="600" letter-spacing="1">SCORE</text>'
        f'</svg>'
    )


def asset_table_html(rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    th = "".join(
        f'<th style="font-size:0.56rem;font-weight:600;color:{_T2};letter-spacing:0.14em;'
        f'text-transform:uppercase;text-align:left;padding:0.45rem 0.85rem;'
        f'border-bottom:1px solid {_BRD};background:#f8f9fa;white-space:nowrap">{c}</th>'
        for c in cols
    )
    trows = ""
    for i, row in enumerate(rows):
        bg = _SRF if i % 2 == 0 else "#f8fafb"
        tds = ""
        for c in cols:
            val = str(row[c])
            if c == "Status":
                if "Online" in val or "Active" in val or "Awarded" in val:
                    dot, tc = GREEN, GREEN
                elif "Pending" in val or "review" in val.lower() or "Session" in val:
                    dot, tc = AMBER, AMBER
                else:
                    dot, tc = _T3, _T2
                cell = (
                    f'<span style="display:inline-flex;align-items:center;gap:0.32rem">'
                    f'<span style="width:6px;height:6px;border-radius:50%;background:{dot};'
                    f'flex-shrink:0"></span>'
                    f'<span style="color:{tc};font-weight:600;font-size:0.74rem">{val}</span></span>'
                )
            else:
                cell = f'<span style="color:{_T1};font-size:0.77rem;font-variant-numeric:tabular-nums">{val}</span>'
            tds += (
                f'<td style="padding:0.4rem 0.85rem;border-bottom:1px solid {_BRD}">{cell}</td>'
            )
        trows += f'<tr style="background:{bg}">{tds}</tr>'
    st.markdown(
        f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:6px;'
        f'overflow:hidden;margin-bottom:0.75rem">'
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>{th}</tr></thead><tbody>{trows}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def _cl(**kw) -> dict:
    d = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#f8f9fa",
        font=dict(color=_T2, family="Inter,system-ui,sans-serif", size=10),
        margin=dict(t=12, b=32, l=52, r=12),
        legend=dict(bgcolor="#fff", bordercolor=_BRD, font=dict(size=9)),
    )
    d.update(kw)
    return d


def _ax(title: str = "", grid: bool = True, mono: bool = False) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=9, color=_T3)),
        tickfont=dict(size=9, color=_T3,
                      family="JetBrains Mono,monospace" if mono else "Inter,sans-serif"),
        showgrid=grid, gridcolor=_BRD,
        linecolor=_BRD, zerolinecolor=_BRD,
    )


# ── Cache functions ───────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def get_prices(days: int, seed: int = 42):
    df = _generate_synthetic_prices(
        start="2024-01-01",
        end=(datetime(2024, 1, 1) + timedelta(days=days)).strftime("%Y-%m-%d"),
        seed=seed,
    )
    return df["lmp_usd_per_mwh"].values, df.index


@st.cache_data(show_spinner=False)
def cached_backtest(days: int, cap: float, pwr: float, chem: str, soc: float):
    cfg = BacktestConfig(capacity_kwh=cap, power_kw=pwr, chemistry=chem, soc_initial=soc)
    prices, _ = get_prices(days)
    p = prices[:min(days * 96, len(prices))]
    return {
        "Myopic":      run_myopic_revenue_max(p, cfg),
        "Rule-based":  run_rule_based(p, cfg),
        "Single MILP": run_single_objective_milp(p, cfg),
        "Vela":        run_vela_full(p, cfg),
    }


@st.cache_data(show_spinner=False)
def cached_dispatch(cap, pwr, chem, soc, horizon_h, days, wr, wd, wp, wrs, wrk):
    prices, _ = get_prices(days)
    dp = prices[-(horizon_h * 4):].tolist()
    W  = ObjectiveWeights(revenue=wr, degradation=wd, penalty=wp, reserve=wrs, risk=wrk)
    bat = BatteryAsset(BatteryConfig(
        asset_id="BESS-001", capacity_kwh=cap, power_kw=pwr,
        chemistry=chem, soc_initial=soc,
    ))
    res = VelaOptimizer([bat]).solve(
        interval_start=datetime(2024, 1, 1),
        prices=dp, as_prices={}, obligations=[], weights=W,
    )
    return res, dp


@st.cache_data(show_spinner=False)
def cached_explain(cap, pwr, chem, soc, days, wr, wd, wp, wrs, wrk):
    prices, _ = get_prices(days)
    ep  = prices[-96:].tolist()
    W   = ObjectiveWeights(revenue=wr, degradation=wd, penalty=wp, reserve=wrs, risk=wrk)
    bat = BatteryAsset(BatteryConfig(
        asset_id="BESS-001", capacity_kwh=cap, power_kw=pwr,
        chemistry=chem, soc_initial=soc, cycles_consumed=1800.0,
    ))
    res = VelaOptimizer([bat]).solve(
        interval_start=datetime(2024, 1, 1),
        prices=ep, as_prices={}, obligations=[], weights=W,
    )
    return res, ep


# ── Coordination checks ───────────────────────────────────────────────────────

def build_coord_checks(result, capacity_kwh: float, power_kw: float) -> list[dict]:
    solver_ok = result.solver_status in ("optimal", "feasible")
    deg_ratio = result.degradation_cost_usd / max(result.revenue_usd, 1)
    return [
        {"title": "Asset telemetry",
         "desc": "All enrolled assets reporting within the last interval; signal quality ≥ 95%.",
         "note": "BESS-001, PV-001, EVC-001, FLEX-001 all confirmed online.",
         "owner": "Internal", "timing": "T-15 min", "priority": "High", "status": "ready"},
        {"title": "Forecast model freshness",
         "desc": "LMP and generation forecast models must be retrained within 6 hours before submission.",
         "note": "Price model last trained 2h 14m ago. Rolling 24h RMSE = 4.21 $/MWh.",
         "owner": "Internal", "timing": "T-30 min", "priority": "Medium", "status": "ready"},
        {"title": "Aggregation registration package",
         "desc": "Resource list, asset metadata, capacity range, and customer eligibility must be consistent.",
         "note": f"5 assets linked; {capacity_kwh/1000:.1f} MW registered at NP15.",
         "owner": "Aggregator", "timing": "T-120 min", "priority": "Low", "status": "ready"},
        {"title": "Locational eligibility",
         "desc": "Aggregation members must remain inside market-approved zones.",
         "note": "NP15 energy and reserve bids use NP15 resources only.",
         "owner": "RTO/ISO", "timing": "T-90 min", "priority": "Low", "status": "ready"},
        {"title": "Distribution utility notice",
         "desc": "Utility receives planned dispatch notice with feeder and local reliability context.",
         "note": "No automated utility adapter configured. Manual notice required via utility portal.",
         "owner": "Distribution utility", "timing": "T-60 min", "priority": "Medium", "status": "review"},
        {"title": "Customer constraint review",
         "desc": "DR participation rules and exclusion windows verified against active dispatch plan.",
         "note": "FLEX-001 has curtailment exclusion 18:00–20:00 not reflected in obligation ledger.",
         "owner": "Customer", "timing": "T-45 min", "priority": "Medium", "status": "review"},
        {"title": "AS obligation mapping",
         "desc": "Ancillary service commitments mapped to bid quantities and verified against headroom.",
         "note": f"Reg up: {power_kw*0.15:.0f} kW committed. CVaR headroom within limits.",
         "owner": "Internal", "timing": "T-30 min", "priority": "Low", "status": "ready"},
        {"title": "Solver feasibility check",
         "desc": "Most recent dispatch solve must return optimal or feasible status.",
         "note": f"Last solve: {result.solver_status.upper()}. Revenue ${result.revenue_usd:,.0f}. Degradation ratio {deg_ratio:.1%}.",
         "owner": "Internal", "timing": "T-10 min", "priority": "High",
         "status": "ready" if solver_ok else "blocked"},
    ]


def checklist_item(c: dict) -> None:
    p_style = {"Low": "grey",  "Medium": "amber", "High": "red"}.get(c["priority"], "grey")
    s_style = {"ready": "green", "review": "amber", "blocked": "red"}.get(c["status"], "grey")
    s_label = {"ready": "Ready", "review": "Review", "blocked": "Blocked"}.get(c["status"], c["status"])
    st.markdown(
        f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:6px;'
        f'padding:0.85rem 1.1rem;margin-bottom:0.45rem">'
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1.5rem">'
        f'<div style="flex:1;min-width:0">'
        f'<div style="font-size:0.82rem;font-weight:600;color:{_T1};margin-bottom:0.18rem">{c["title"]}</div>'
        f'<div style="font-size:0.72rem;color:{_T2};line-height:1.45;margin-bottom:0.15rem">{c["desc"]}</div>'
        f'<div style="font-size:0.67rem;color:{_T3};font-style:italic;line-height:1.35">{c["note"]}</div>'
        f'</div>'
        f'<div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.28rem;flex-shrink:0;min-width:110px">'
        f'<div style="font-size:0.67rem;color:{_T2};font-weight:500">{c["owner"]}</div>'
        f'<div style="font-size:0.63rem;color:{_T3};font-family:\'JetBrains Mono\',monospace">{c["timing"]}</div>'
        f'<div style="display:flex;gap:0.3rem">{badge(c["priority"], p_style)}{badge(s_label, s_style)}</div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f'<div style="padding:1rem 0.9rem 0.85rem;border-bottom:1px solid {_SBB}">'
        f'<div style="display:flex;align-items:center;gap:0.6rem">'
        f'<div style="width:28px;height:28px;background:#0969da;border-radius:6px;display:flex;'
        f'align-items:center;justify-content:center;flex-shrink:0">'
        f'<span style="font-size:0.88rem;font-weight:800;color:#fff">V</span></div>'
        f'<div>'
        f'<div style="font-size:0.84rem;font-weight:700;letter-spacing:0.1em;color:{_SBT1}">VELA</div>'
        f'<div style="font-size:0.58rem;color:{_SBT2};margin-top:0.04rem">Virtual energy operations</div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "",
        ["Command", "Portfolio", "Markets", "Coordination", "Model", "Integrations", "Run log"],
        label_visibility="collapsed",
    )

    st.markdown(f'<div style="height:1px;background:{_SBB};margin:0.2rem 0"></div>',
                unsafe_allow_html=True)

    # ── Config sections ──────────────────────────────────────────────────────
    for section, widgets in [
        ("Battery config", [
            ("cap",  "Capacity (kWh)",   "int",   (500, 20000, 4000, 500)),
            ("pwr",  "Power (kW)",        "int",   (250, 10000, 2000, 250)),
            ("chem", "Chemistry",         "sel",   ["nmc", "lfp", "nca"]),
            ("soc",  "Initial SOC (%)",   "int",   (10, 90, 50, 5)),
        ]),
        ("Simulation", [
            ("days", "Period (days)",     "int",   (3, 30, 7)),
            ("hor",  "Horizon (hrs)",     "sel",   [4, 12, 24]),
        ]),
        ("Objective weights", [
            ("wr",   "Revenue",           "float", (0.0, 5.0, 1.0, 0.1)),
            ("wd",   "Degradation",       "float", (0.0, 5.0, 0.8, 0.1)),
            ("wp",   "Obligation",        "float", (0.0, 5.0, 2.0, 0.1)),
            ("wrs",  "Reserves",          "float", (0.0, 5.0, 0.6, 0.1)),
            ("wrk",  "CVaR risk",         "float", (0.0, 5.0, 0.5, 0.1)),
        ]),
    ]:
        st.markdown(
            f'<div style="font-size:0.52rem;font-weight:700;color:{_SBT2};'
            f'letter-spacing:0.22em;text-transform:uppercase;padding:0.7rem 0.9rem 0.3rem">'
            f'{section}</div>',
            unsafe_allow_html=True,
        )
        for key, label, wtype, args in widgets:
            if wtype == "int":
                v = st.slider(label, *args, key=f"s_{key}")
                if key == "cap":    capacity_kwh = v
                elif key == "pwr":  power_kw = v
                elif key == "soc":  soc_init = v / 100.0
                elif key == "days": backtest_days = v
            elif wtype == "float":
                v = st.slider(label, *args, key=f"s_{key}")
                if key == "wr":   w_rev = v
                elif key == "wd": w_deg = v
                elif key == "wp": w_pen = v
                elif key == "wrs": w_res = v
                elif key == "wrk": w_rsk = v
            elif wtype == "sel":
                v = st.selectbox(label, args, key=f"s_{key}")
                if key == "chem": chemistry = v
                elif key == "hor": horizon_h = v
        st.markdown(f'<div style="height:1px;background:{_SBB};margin:0.3rem 0"></div>',
                    unsafe_allow_html=True)

    # ── Control mode ─────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="font-size:0.52rem;font-weight:700;color:{_SBT2};'
        f'letter-spacing:0.22em;text-transform:uppercase;padding:0.7rem 0.9rem 0.3rem">'
        f'Control mode</div>',
        unsafe_allow_html=True,
    )
    ctrl = st.selectbox("", ["Operator approval", "Autonomous", "Simulation"],
                        key="ctrl", label_visibility="collapsed")
    mode_desc = {
        "Operator approval": "Advisory only. Dispatch stays blocked until gates, overrides, and source quality are reviewed.",
        "Autonomous":        "Dispatch executes automatically on each interval close. Operator alerts only on breach.",
        "Simulation":        "Full pipeline runs but no commands are issued to assets. Safe for testing.",
    }
    st.markdown(
        f'<div style="padding:0 0.9rem 0.85rem">'
        f'<div style="font-size:0.68rem;font-weight:600;color:{_SBT1};margin-bottom:0.18rem">'
        f'{ctrl}</div>'
        f'<div style="font-size:0.62rem;color:{_SBT2};line-height:1.45">'
        f'{mode_desc[ctrl]}</div></div>',
        unsafe_allow_html=True,
    )
    st.button("Run simulation", type="primary", use_container_width=True)


# ── Shared data ───────────────────────────────────────────────────────────────
prices_arr, _ = get_prices(backtest_days)
cur_lmp       = float(prices_arr[-1])
mean_lmp      = float(prices_arr.mean())
interval_str  = datetime.now().strftime("%H:%M PDT")

with st.spinner("Solving…"):
    result, dp = cached_dispatch(
        capacity_kwh, power_kw, chemistry, soc_init,
        horizon_h, backtest_days, w_rev, w_deg, w_pen, w_res, w_rsk,
    )

ar    = result.asset_results[0] if result.asset_results else None
T     = len(dp)
ts    = [datetime.now() + timedelta(minutes=15 * i) for i in range(T)]
ch_kw = (ar.charge_kw    or [0.0] * T) if ar else [0.0] * T
di_kw = (ar.discharge_kw or [0.0] * T) if ar else [0.0] * T
soc_v = ([s * 100 for s in ar.soc] if ar and ar.soc else [soc_init * 100] * T)

checks    = build_coord_checks(result, capacity_kwh, power_kw)
n_ready   = sum(1 for c in checks if c["status"] == "ready")
n_review  = sum(1 for c in checks if c["status"] == "review")
n_blocked = sum(1 for c in checks if c["status"] == "blocked")
pct_coord = int(n_ready / len(checks) * 100)
pct_disp  = 88 if result.solver_status in ("optimal", "feasible") else 62

battery = BatteryAsset(BatteryConfig(
    asset_id="DEMO", capacity_kwh=capacity_kwh, power_kw=power_kw,
    chemistry=chemistry, soc_initial=soc_init,
))
deg_pct = battery.cfg.cycles_consumed / battery.cfg.warranty_full_cycles * 100

# Derived dispatch quantities
net_dis_kw  = max(0.0, max(di_kw) - max(ch_kw))
net_mw      = net_dis_kw / 1000
portfolio_mw = (capacity_kwh / 1000) * 1.6
avail_mw     = portfolio_mw * 0.78
expected_net = result.revenue_usd - result.degradation_cost_usd
downside_net = -abs(result.cvar_usd)
ramp_mw      = power_kw * 0.037

action_mw = net_mw if net_dis_kw > 10 else avail_mw * 0.26
action_label = "Sell" if net_dis_kw > 10 else "Reserve"
action_mw_str = f"{action_mw:.0f} MW"

rev_score  = min(100, int(result.revenue_usd / max(result.revenue_usd + abs(result.cvar_usd), 1) * 100))
rely_score = 83
oblig_pct  = "100%" if result.penalty_usd < 1 else f"{max(0, 100 - int(result.penalty_usd / 10))}%"
enroll_pct = "81%"
risk_score = max(0, 100 - int(result.cvar_usd / max(result.revenue_usd, 1) * 100))
overall_score = int(0.35 * rev_score + 0.2 * rely_score + 0.25 * (100 if result.penalty_usd < 1 else 60) + 0.2 * (100 - risk_score))
overall_score = max(30, min(99, overall_score))
feasibility_pct = 59 if result.solver_status == "optimal" else 42

constrained_sources = n_blocked + n_review


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Command
# ══════════════════════════════════════════════════════════════════════════════
if page == "Command":
    topbar(
        interval_str, pct_disp,
        badge(f"{constrained_sources} constrained sources", "amber") if constrained_sources else "",
    )
    page_heading("CAISO AGGREGATE PORTFOLIO", "Command")

    # ── 4 KPI cards ──────────────────────────────────────────────────────────
    # SVG path data (subset of heroicons / feather)
    kpi_icon_row([
        # grid icon → portfolio MW
        ("M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
         "Portfolio MW", f"{portfolio_mw:.0f} MW",
         "Registered capacity across five resource classes",
         "#ddf4ff", "#0550ae"),
        # speedometer / gauge
        ("M12 2a10 10 0 100 20A10 10 0 0012 2zm0 18a8 8 0 110-16 8 8 0 010 16zm3.53-11.47l-4 4a1 1 0 01-1.06.22 1 1 0 01-.61-.93V7a1 1 0 012 0v3.59l3.29-3.3a1 1 0 011.42 1.42l-.04.04z",
         "Available", f"{avail_mw:.0f} MW",
         f"{int(avail_mw/portfolio_mw*100)}% dispatchable this interval",
         "#dafbe1", "#1a7f37"),
        # dollar circle
        ("M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6",
         "Forecast Net", f"${expected_net:,.0f}",
         "Current recommended dispatch window",
         "#fff8c5", "#9a6700"),
        # alert triangle → readiness
        ("M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4M12 17h.01",
         "Readiness", f"{pct_disp}%",
         f"5 adapters online{', ' + str(constrained_sources) + ' warnings' if constrained_sources else ', no warnings'}",
         "#ffebe9" if pct_disp < 80 else "#f1f3f5",
         "#cf222e" if pct_disp < 80 else "#444d56"),
    ])

    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Two-column: main + decision queue ─────────────────────────────────────
    col_main, col_queue = st.columns([2.25, 1], gap="medium")

    with col_main:
        # ── Recommended Action card ───────────────────────────────────────────
        hour_start = datetime.now().replace(minute=0, second=0, microsecond=0)
        window_str = f"{hour_start.strftime('%H:%M')}–{(hour_start + timedelta(hours=2)).strftime('%H:%M')}"

        score_svg = score_donut_svg(overall_score, 90)

        conf_desc = (
            f"Energy arbitrage has {feasibility_pct}% signal confidence and a "
            f"{'scarcity grid condition' if cur_lmp > mean_lmp * 1.2 else 'normal grid condition'}. "
            f"Sutter BESS Cluster, North Valley Backup Gen, Bay Logistics EV Depots can cover "
            f"{action_mw:.0f} MW with {feasibility_pct}% modeled feasibility, "
            f"{ramp_mw*1000:.0f} MW reserve margin, and "
            f"${downside_net:,.0f} downside revenue under stressed scenarios."
        )

        st.markdown(
            f'<div style="background:{_SRF};border:1px solid {_BRD};border-left:3px solid {BLUE};'
            f'border-radius:6px;padding:1.1rem 1.25rem 1rem;margin-bottom:0.75rem">'

            # Header row
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem">'
            f'<span style="font-size:0.57rem;font-weight:700;color:{_T3};letter-spacing:0.2em;'
            f'text-transform:uppercase">Recommended action</span>'
            f'<span style="font-size:0.68rem;color:{_T3};font-family:\'JetBrains Mono\',monospace">'
            f'{window_str}</span></div>'

            # Action + donut
            f'<div style="display:flex;gap:1.25rem;align-items:flex-start">'
            f'<div style="flex:1;min-width:0">'
            f'<div style="font-size:0.6rem;font-weight:600;color:{TEAL};letter-spacing:0.18em;'
            f'text-transform:uppercase;margin-bottom:0.3rem">Energy arbitrage</div>'
            f'<div style="font-size:2rem;font-weight:700;color:{_T1};line-height:1;margin-bottom:0.6rem">'
            f'{action_label} {action_mw_str}</div>'
            f'<div style="font-size:0.74rem;color:{_T2};line-height:1.5;max-width:520px">{conf_desc}</div>'
            f'</div>'
            f'<div style="flex-shrink:0">{score_svg}</div>'
            f'</div>'

            # Score breakdown
            f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:0.4rem;margin-top:0.9rem">'
            + "".join([
                f'<div style="background:#f4f5f7;border-radius:5px;padding:0.55rem 0.6rem">'
                f'<div style="font-size:0.55rem;font-weight:600;color:{_T2};letter-spacing:0.12em;'
                f'text-transform:uppercase;margin-bottom:0.2rem">{lbl}</div>'
                f'<div style="font-size:0.88rem;font-weight:700;color:{_T1};'
                f'font-variant-numeric:tabular-nums">{val}</div></div>'
                for lbl, val in [
                    ("Revenue",     f"{rev_score}/100"),
                    ("Reliability", f"{rely_score}/100"),
                    ("Obligation",  oblig_pct),
                    ("Enrollment",  enroll_pct),
                    ("Risk",        str(risk_score)),
                ]
            ]) +
            f'</div>'

            # Bottom metrics
            f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:0.4rem;margin-top:0.5rem;'
            f'border-top:1px solid {_BRD};padding-top:0.65rem">'
            + "".join([
                f'<div>'
                f'<div style="font-size:1rem;font-weight:700;color:{tc};'
                f'font-variant-numeric:tabular-nums">{val}</div>'
                f'<div style="font-size:0.56rem;font-weight:600;color:{_T2};'
                f'letter-spacing:0.13em;text-transform:uppercase;margin-top:0.12rem">{lbl}</div>'
                f'</div>'
                for val, lbl, tc in [
                    (f"{feasibility_pct}%",           "Feasible",      _T1),
                    (f"${expected_net:,.0f}",          "Expected net",  GREEN if expected_net > 0 else RED),
                    (f"${downside_net:,.0f}",          "Downside net",  RED),
                    (f"{ramp_mw*1000:.0f} MW",         "Ramp feasible", _T1),
                ]
            ]) +
            f'</div>'

            f'</div>',
            unsafe_allow_html=True,
        )

        # Action buttons
        btn_col1, btn_col2, _ = st.columns([1, 1, 4], gap="small")
        with btn_col1:
            st.button("Review package", type="primary")
        with btn_col2:
            st.button("Inspect model", type="secondary")

        st.markdown('<div style="height:0.25rem"></div>', unsafe_allow_html=True)

        # ── Bottom: Advisory Dispatch + Approval Gates ────────────────────────
        col_adv, col_gates = st.columns([1.2, 1], gap="medium")

        with col_adv:
            section_hdr("Advisory dispatch", "Bid blocks and asset instructions",
                        badge("advisory", "blue"))
            bid_blocks = [
                {
                    "Product":   "Energy arbitrage",
                    "Node":      "CAISO NP15",
                    "Window":    window_str,
                    "MW":        f"{action_mw:.1f} MW",
                    "Price":     f"${cur_lmp:.0f}/MWh",
                    "Conf":      f"{feasibility_pct}%",
                    "Status":    "Submitted",
                },
                {
                    "Product":   "Sutter BESS Cluster",
                    "Node":      "Reserve 28 MWh for evening resource adequacy obligation.",
                    "Window":    "",
                    "MW":        f"{power_kw*0.037:.0f} MW",
                    "Price":     f"{power_kw/1000*18:.0f} MW/min",
                    "Conf":      "",
                    "Status":    "review",
                },
            ]

            for b in bid_blocks:
                is_review = b["Status"].lower() == "review"
                status_html = badge("review", "amber") if is_review else badge("submitted", "green")
                detail_row = (
                    f'<span style="font-size:0.74rem;color:{_T2};font-family:\'JetBrains Mono\',monospace">'
                    f'{b["MW"]}</span>'
                    f'<span style="font-size:0.72rem;color:{_T3};margin-left:0.75rem">{b["Price"]}</span>'
                    f'{"<span style=\'font-size:0.72rem;color:" + _T3 + ";margin-left:0.75rem\'>" + b["Conf"] + " conf</span>" if b["Conf"] else ""}'
                ) if b["MW"] else ""
                sub_line = (
                    f'<div style="font-size:0.68rem;color:{_T3};margin-top:0.1rem;line-height:1.4">'
                    f'{b["Node"]}{"&ensp;·&ensp;" + b["Window"] if b["Window"] else ""}</div>'
                ) if b["Node"] else ""
                st.markdown(
                    f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:5px;'
                    f'padding:0.7rem 0.9rem;margin-bottom:0.45rem">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.12rem">'
                    f'<span style="font-size:0.8rem;font-weight:600;color:{_T1}">{b["Product"]}</span>'
                    f'{status_html}</div>'
                    f'{sub_line}'
                    f'<div style="margin-top:0.35rem">{detail_row}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with col_gates:
            section_hdr("Approval gates", "What must clear first")
            gates = [
                {
                    "title":  "Constraint satisfaction",
                    "desc":   f"{max(0, len(checks) - n_ready)} modeled constraints are violated." if n_blocked else "All modeled constraints satisfied.",
                    "status": "blocked" if n_blocked > 0 else "clear",
                    "label":  "blocked" if n_blocked > 0 else "clear",
                },
                {
                    "title":  "Operator approval",
                    "desc":   f"{n_review} asset instruction{'s' if n_review != 1 else ''} require human approval before dispatch.",
                    "status": "review" if n_review > 0 else "clear",
                    "label":  "needs-review" if n_review > 0 else "clear",
                },
                {
                    "title":  "Model confidence",
                    "desc":   "Feasibility is below the operator review threshold." if feasibility_pct < 70 else "Model confidence is above threshold.",
                    "status": "review" if feasibility_pct < 70 else "clear",
                    "label":  "needs-review" if feasibility_pct < 70 else "clear",
                },
            ]
            for g in gates:
                st_map = {
                    "blocked": ("#ffebe9", "#ffcecb", "#cf222e", "blocked"),
                    "review":  ("#fff8c5", "#e8cf50", "#9a6700", "needs-review"),
                    "clear":   (_SRF,      _BRD,     GREEN,     "clear"),
                }
                bg, br, tc, lbl = st_map.get(g["status"], st_map["clear"])
                st.markdown(
                    f'<div style="background:{bg};border:1px solid {br};border-radius:5px;'
                    f'padding:0.7rem 0.9rem;margin-bottom:0.4rem">'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.18rem">'
                    f'<span style="font-size:0.8rem;font-weight:600;color:{_T1}">{g["title"]}</span>'
                    f'<span style="font-size:0.64rem;font-weight:600;color:{tc}">{lbl}</span>'
                    f'</div>'
                    f'<div style="font-size:0.7rem;color:{_T2};line-height:1.4">{g["desc"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    with col_queue:
        section_hdr("Decision queue", "Candidate ordering")

        candidates = [
            (f"{action_label} {action_mw:.0f} MW",    f"Energy arbitrage · {window_str}",     overall_score, BLUE),
            ("Reserve 48 MW",                          "Frequency regulation · T-30 – T+00",   overall_score - 1, GREEN),
            ("Reserve 36 MW",                          f"Reserve · {(hour_start + timedelta(hours=1)).strftime('%H:%M')}–{(hour_start + timedelta(hours=5)).strftime('%H:%M')}", overall_score - 2, GREEN),
            ("Shift 61 MW",                            f"Demand response · {(hour_start + timedelta(hours=3)).strftime('%H:%M')}–{(hour_start + timedelta(hours=6)).strftime('%H:%M')}", overall_score - 3, AMBER),
            (f"Sell {action_mw*0.75:.0f} MW",          f"Capacity event · {(hour_start + timedelta(hours=4)).strftime('%H:%M')}–{(hour_start + timedelta(hours=7)).strftime('%H:%M')}", overall_score - 11, RED),
        ]
        for i, (name, detail, score, sc) in enumerate(candidates):
            active = i == 0
            bg  = "#ddf4ff" if active else _SRF
            brd = "#80ccff" if active else _BRD
            circle_bg = sc
            st.markdown(
                f'<div style="background:{bg};border:1px solid {brd};border-radius:5px;'
                f'padding:0.65rem 0.8rem;margin-bottom:0.4rem;display:flex;'
                f'align-items:center;justify-content:space-between;gap:0.7rem">'
                f'<div style="min-width:0">'
                f'<div style="font-size:0.78rem;font-weight:{"700" if active else "500"};color:{_T1};'
                f'margin-bottom:0.1rem">{name}</div>'
                f'<div style="font-size:0.65rem;color:{_T3};line-height:1.3">{detail}</div>'
                f'</div>'
                f'<div style="width:28px;height:28px;background:{circle_bg};border-radius:50%;'
                f'flex-shrink:0;display:flex;align-items:center;justify-content:center">'
                f'<span style="font-size:0.68rem;font-weight:700;color:#fff">{score}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Portfolio
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Portfolio":
    topbar(interval_str, pct_disp)
    page_heading("FLEET", "Portfolio")

    kpi_icon_row([
        ("M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
         "Active Assets", "4 / 4", "All protocols healthy",
         "#ddf4ff", "#0550ae"),
        ("M3 3h18v18H3zM9 9h6v6H9z",
         "Total Capacity", f"{capacity_kwh:,} kWh", f"{power_kw:,} kW rated",
         "#dafbe1", "#1a7f37"),
        ("M12 2v20M2 12h20",
         "Current SOC", f"{soc_init*100:.0f}%", "BESS-001",
         "#fff8c5", "#9a6700"),
        ("M22 12h-4l-3 9L9 3l-3 9H2",
         "Warranty Health", f"{100 - deg_pct:.1f}%", f"{deg_pct:.1f}% consumed",
         "#f1f3f5", "#444d56"),
    ])

    section_hdr("Connected assets", "Fleet inventory")
    asset_table_html([
        {"Asset": "BESS-001", "Type": "Battery Storage",  "Protocol": "SunSpec Modbus TCP",
         "Capacity": f"{capacity_kwh:,} kWh", "Chem": chemistry.upper(),
         "SOC": f"{soc_init*100:.0f}%", "Status": "Online"},
        {"Asset": "PV-001",   "Type": "Solar PV",          "Protocol": "SunSpec Modbus TCP",
         "Capacity": "500 kW",             "Chem": "—", "SOC": "—",  "Status": "Online"},
        {"Asset": "EVC-001",  "Type": "EV Charger",        "Protocol": "OCPP 1.6",
         "Capacity": "4 × 11 kW",          "Chem": "—", "SOC": "—",  "Status": "1 Session Active"},
        {"Asset": "FLEX-001", "Type": "Flex Load",         "Protocol": "OpenADR 2.0b",
         "Capacity": "±200 kW",            "Chem": "—", "SOC": "—",  "Status": "Online"},
    ])

    section_hdr("Net output", f"Last {backtest_days}d portfolio")
    p_arr = prices_arr[-96:]
    t96   = [datetime.now() - timedelta(minutes=15 * (96 - i)) for i in range(96)]
    net   = [c - d for c, d in zip(ch_kw[:96], di_kw[:96])]
    fig_p = go.Figure()
    fig_p.add_trace(go.Scatter(x=t96, y=p_arr, name="LMP $/MWh",
                               line=dict(color=AMBER, width=1.2, dash="dot"), yaxis="y2",
                               hovertemplate="%{y:.1f} $/MWh<extra></extra>"))
    fig_p.add_trace(go.Bar(x=t96, y=[max(0, -n) for n in net[:96]], name="Discharge",
                           marker_color=GREEN, opacity=0.8))
    fig_p.add_trace(go.Bar(x=t96, y=[max(0, n) for n in net[:96]], name="Charge",
                           marker_color=BLUE, opacity=0.8))
    fig_p.update_layout(
        height=300, barmode="relative",
        yaxis2=dict(overlaying="y", side="right", showgrid=False,
                    tickfont=dict(size=9, color=_T3),
                    title=dict(text="$/MWh", font=dict(size=9))),
        xaxis=_ax(grid=False), yaxis=_ax("kW", mono=True), **_cl(),
    )
    st.plotly_chart(fig_p, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Markets
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Markets":
    topbar(interval_str, pct_disp)
    page_heading("MARKET PARTICIPATION", "Markets")

    with st.spinner("Computing settlement…"):
        engine = CAISOSettlementEngine(
            resource_id="BESS-001", pnode_id="NP15_GEN-APND",
            capacity_mw=power_kw / 1000,
        )
        lmp_ivs = [
            CAISOLMPInterval(
                interval_start=datetime(2024, 1, 1) + timedelta(minutes=15 * i),
                lmp_usd_per_mwh=float(prices_arr[i]),
                mec=float(prices_arr[i]) * 0.70,
                mlc=float(prices_arr[i]) * 0.20,
                mcc=float(prices_arr[i]) * 0.10,
                energy_dispatched_mwh=max(0.0, di_kw[i % T] - ch_kw[i % T]) * 0.25 / 1000,
            )
            for i in range(min(96, len(prices_arr)))
        ]
        reg_ivs = [
            CAISORegulationInterval(
                interval_start=datetime(2024, 1, 1) + timedelta(minutes=15 * i),
                reg_up_price=float(prices_arr[i]) * 0.12,
                reg_down_price=float(prices_arr[i]) * 0.08,
                reg_up_dispatched_mw=power_kw * 0.10 / 1000,
                reg_down_dispatched_mw=power_kw * 0.06 / 1000,
                performance_score=0.96,
            )
            for i in range(min(96, len(prices_arr)))
        ]
        settlement = engine.compute_settlement(lmp_ivs, reg_ivs)

    kpi_icon_row([
        ("M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6",
         "Energy Revenue", f"${settlement.energy_revenue_usd:,.0f}", "last 24h", "#dafbe1", "#1a7f37"),
        ("M22 12h-4l-3 9L9 3l-3 9H2",
         "Reg Revenue", f"${settlement.regulation_revenue_usd:,.0f}", "reg up + down", "#ddf4ff", "#0550ae"),
        ("M3 3l18 18M21 3L3 21",
         "Under-delivery", f"${settlement.under_delivery_penalty_usd:,.2f}", "penalties", "#ffebe9", "#cf222e"),
        ("M5 3l14 9-14 9V3z",
         "Total Gross", f"${settlement.total_gross_revenue_usd:,.0f}", "CAISO settlement", "#fff8c5", "#9a6700"),
    ])

    col_lmp, col_bids = st.columns([3, 2], gap="medium")

    with col_lmp:
        section_hdr("LMP", f"NP15 · {backtest_days}d")
        t96 = [datetime.now() - timedelta(minutes=15 * (96 - i)) for i in range(96)]
        fig_lmp = go.Figure()
        fig_lmp.add_trace(go.Scatter(
            x=t96, y=prices_arr[-96:], mode="lines",
            line=dict(color=BLUE, width=1.5),
            fill="tozeroy", fillcolor="rgba(9,105,218,0.06)",
            hovertemplate="%{y:.2f} $/MWh<extra></extra>",
        ))
        fig_lmp.add_hline(y=mean_lmp, line_color=AMBER, line_width=1, line_dash="dash",
                          annotation_text=f"avg {mean_lmp:.1f}", annotation_font=dict(color=AMBER, size=9))
        fig_lmp.update_layout(
            height=260, showlegend=False,
            xaxis=_ax(grid=False), yaxis=_ax("$/MWh", mono=True), **_cl(),
        )
        st.plotly_chart(fig_lmp, use_container_width=True)

    with col_bids:
        section_hdr("Active bids", "Current position")
        asset_table_html([
            {"Product": "Energy",   "Market": "RT", "Qty": f"{power_kw*0.6:.0f} kW", "Status": "Submitted"},
            {"Product": "Reg Up",   "Market": "AS", "Qty": f"{power_kw*0.15:.0f} kW","Status": "Awarded"},
            {"Product": "Reg Down", "Market": "AS", "Qty": f"{power_kw*0.10:.0f} kW","Status": "Awarded"},
            {"Product": "Spin Res", "Market": "AS", "Qty": f"{power_kw*0.20:.0f} kW","Status": "Pending"},
        ])


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Coordination
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Coordination":
    topbar(interval_str, pct_disp,
           badge(f"{n_blocked} blocked", "red") if n_blocked else badge("No blocks", "green"))
    page_heading("MARKET PARTICIPATION", "Coordination")

    col_donut, col_stats = st.columns([1, 2.5], gap="medium")

    with col_donut:
        r, sw = 34, 7
        circ = 2 * 3.14159 * r
        dash = pct_coord / 100 * circ
        donut_svg = (
            f'<svg width="150" height="150" viewBox="0 0 80 80">'
            f'<circle cx="40" cy="40" r="{r}" fill="none" stroke="#e8edf2" stroke-width="{sw}"/>'
            f'<circle cx="40" cy="40" r="{r}" fill="none" stroke="#1a7f37" stroke-width="{sw}" '
            f'stroke-dasharray="{dash:.1f} {circ:.1f}" stroke-dashoffset="{circ*0.25:.1f}" '
            f'stroke-linecap="round"/>'
            f'<text x="40" y="37" text-anchor="middle" font-size="18" font-weight="700" '
            f'fill="#0d1117" font-family="Inter,sans-serif">{pct_coord}</text>'
            f'<text x="40" y="50" text-anchor="middle" font-size="8" fill="#8b949e" '
            f'font-family="Inter,sans-serif" font-weight="600" letter-spacing="1">READY</text>'
            f'</svg>'
        )
        st.markdown(
            f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:6px;'
            f'padding:1rem;display:flex;align-items:center;justify-content:center">'
            f'{donut_svg}</div>',
            unsafe_allow_html=True,
        )

    with col_stats:
        n_col1, n_col2, n_col3 = st.columns(3, gap="small")
        for col, val, lbl, col_color in [
            (n_col1, n_ready,   "Ready",   _T1),
            (n_col2, n_review,  "Review",  AMBER),
            (n_col3, n_blocked, "Blocked", RED if n_blocked else _T3),
        ]:
            with col:
                st.markdown(
                    f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:6px;'
                    f'padding:0.85rem 1rem;text-align:center">'
                    f'<div style="font-size:1.5rem;font-weight:700;color:{col_color}">{val}</div>'
                    f'<div style="font-size:0.65rem;color:{_T2};font-weight:500;margin-top:0.12rem">{lbl}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        posture = (
            "All primary gates clear. Distribution utility notice requires manual filing before T-60. "
            "Customer constraint window for FLEX-001 should be confirmed before autonomous dispatch proceeds."
            if n_blocked == 0 else
            "One or more critical gates are blocked. Dispatch should not proceed until resolved."
        )
        st.markdown(
            f'<div style="background:#ddf4ff;border:1px solid #80ccff;border-radius:6px;'
            f'padding:0.85rem 1rem;margin-top:0.6rem">'
            f'<div style="font-size:0.57rem;font-weight:700;color:#0550ae;'
            f'letter-spacing:0.15em;text-transform:uppercase;margin-bottom:0.2rem">Coordination posture</div>'
            f'<div style="font-size:0.75rem;color:#0d3b6e;line-height:1.5">{posture}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    section_hdr("Responsibility map", "Owners and timing")
    owners = {
        "RTO/ISO":         [c for c in checks if c["owner"] == "RTO/ISO"],
        "Dist. Utility":   [c for c in checks if c["owner"] == "Distribution utility"],
        "Aggregator":      [c for c in checks if c["owner"] == "Aggregator"],
        "Customer":        [c for c in checks if c["owner"] == "Customer"],
        "Internal":        [c for c in checks if c["owner"] == "Internal"],
    }
    resp_cols = st.columns(len(owners), gap="small")
    for col, (owner, items) in zip(resp_cols, owners.items()):
        n_blk = sum(1 for c in items if c["status"] == "blocked")
        with col:
            st.markdown(
                f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:6px;'
                f'padding:0.8rem 0.85rem">'
                f'<div style="font-size:0.74rem;font-weight:600;color:{_T1};margin-bottom:0.4rem">{owner}</div>'
                f'<div style="font-size:0.65rem;color:{_T2}">{len(items)} checkpoints</div>'
                f'<div style="font-size:0.65rem;color:{"#cf222e" if n_blk else _T3};margin-top:0.12rem">'
                f'{"No blocks" if not n_blk else str(n_blk) + " blocked"}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    section_hdr("Coordination checklist",
                "Registration, telemetry, utility review, customer rules")
    for c in checks:
        checklist_item(c)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Model
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Model":
    topbar(interval_str, pct_disp)
    page_heading("OPTIMIZATION", "Model")

    with st.spinner("Analysing…"):
        res_ex, ep = cached_explain(
            capacity_kwh, power_kw, chemistry, soc_init,
            backtest_days, w_rev, w_deg, w_pen, w_res, w_rsk,
        )

    from vela.m7_explainability.dual_analysis import analyse_duals, compute_counterfactual
    from vela.m7_explainability.recommendation import _fallback_recommendation

    bat_ex  = BatteryAsset(BatteryConfig(
        asset_id="BESS-001", capacity_kwh=capacity_kwh, power_kw=power_kw,
        chemistry=chemistry, soc_initial=soc_init, cycles_consumed=1800.0,
    ))
    binding = analyse_duals(res_ex, [bat_ex], ep, 0.25)
    cf      = compute_counterfactual(res_ex, res_ex.revenue_usd * 1.20, binding)
    rec     = _fallback_recommendation(res_ex, binding, cf)

    kpi_icon_row([
        ("M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6",
         "Constrained Revenue", f"${cf.constrained_revenue_usd:,.0f}", "MILP solution", "#dafbe1", "#1a7f37"),
        ("M3 3l18 18",
         "Revenue Foregone", f"${cf.revenue_foregone_usd:,.0f}", "constraint cost", "#ffebe9", "#cf222e"),
        ("M22 12h-4l-3 9L9 3l-3 9H2",
         "Binding Constraints", str(len(binding)), "active at optimum", "#fff8c5", "#9a6700"),
        ("M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm1-11h-2v4h-4v2h6V9z",
         "Unconstrained Revenue", f"${cf.unconstrained_revenue_usd:,.0f}", "counterfactual", "#ddf4ff", "#0550ae"),
    ])

    col_rec, col_wf = st.columns([1.2, 1], gap="medium")

    with col_rec:
        section_hdr("Recommended action", "Primary rationale")
        st.markdown(
            f'<div style="background:{_SRF};border:1px solid {_BRD};border-left:3px solid {BLUE};'
            f'border-radius:6px;padding:1rem 1.1rem">'
            f'<div style="font-size:0.57rem;font-weight:700;color:{_T3};'
            f'letter-spacing:0.18em;text-transform:uppercase;margin-bottom:0.3rem">Action</div>'
            f'<div style="font-size:0.9rem;font-weight:600;color:{_T1};line-height:1.4;margin-bottom:0.7rem">'
            f'{rec.recommended_action}</div>'
            f'<div style="border-top:1px solid {_BRD};padding-top:0.6rem">'
            f'<div style="font-size:0.57rem;font-weight:700;color:{_T3};'
            f'letter-spacing:0.18em;text-transform:uppercase;margin-bottom:0.18rem">Rationale</div>'
            f'<div style="font-size:0.75rem;color:{_T2};line-height:1.5">{rec.primary_rationale}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        if binding:
            section_hdr("Binding constraints", f"{len(binding)} active")
            for bc in binding:
                bar = min(100, int(bc.dual_value * 10))
                st.markdown(
                    f'<div style="background:{_SRF};border:1px solid {_BRD};border-radius:6px;'
                    f'padding:0.8rem 1rem;margin-bottom:0.4rem">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.25rem">'
                    f'<span style="font-size:0.78rem;font-weight:600;color:{_T1}">'
                    f'{bc.constraint_type.replace("_"," ").title()}</span>'
                    f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.67rem;color:{AMBER}">'
                    f'${bc.dual_value:.4f}</span></div>'
                    f'<div style="background:#f1f3f5;border-radius:2px;height:3px;margin-bottom:0.35rem">'
                    f'<div style="background:{BLUE};width:{bar}%;height:100%;border-radius:2px"></div></div>'
                    f'<div style="font-size:0.7rem;color:{_T2}">{bc.plain_english}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    with col_wf:
        section_hdr("Objective waterfall", "Revenue components")
        comps = {
            "Revenue":       res_ex.revenue_usd,
            "− Degradation": -res_ex.degradation_cost_usd,
            "− Penalty":     -res_ex.penalty_usd,
            "+ Reserve":     res_ex.reserve_value_usd,
            "− CVaR":        -res_ex.cvar_usd,
        }
        total = sum(comps.values())
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=["relative"] * len(comps) + ["total"],
            x=list(comps.keys()) + ["Net"],
            y=list(comps.values()) + [total],
            connector=dict(line=dict(color=_BRD)),
            increasing=dict(marker=dict(color=GREEN)),
            decreasing=dict(marker=dict(color=RED)),
            totals=dict(marker=dict(color=BLUE)),
            hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
            textfont=dict(size=9),
        ))
        fig_wf.update_layout(
            height=340, showlegend=False,
            xaxis=_ax(grid=False), yaxis=_ax("USD", mono=True), **_cl(),
        )
        st.plotly_chart(fig_wf, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Integrations
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Integrations":
    topbar(interval_str, pct_disp)
    page_heading("DEVICE LAYER", "Integrations")

    kpi_icon_row([
        ("M5 12h14M12 5l7 7-7 7",
         "Connected Devices", "4 / 4", "All protocols healthy", "#dafbe1", "#1a7f37"),
        ("M22 12h-4l-3 9L9 3l-3 9H2",
         "Avg Signal Quality", "98.8%", "15-min rolling average", "#ddf4ff", "#0550ae"),
        ("M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z",
         "Message Rate", "240/min", "Across all assets", "#fff8c5", "#9a6700"),
        ("M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 8.63a19.79 19.79 0 01-3.07-8.64A2 2 0 012 0h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.09 7.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z",
         "Last Gap", "None", "No telemetry gaps today", "#f1f3f5", "#444d56"),
    ])

    section_hdr("Protocol status", "Device connections and heartbeats")
    asset_table_html([
        {"Asset": "BESS-001", "Protocol": "SunSpec Modbus TCP", "Host": "192.168.1.10:502",
         "Heartbeat": "0s ago", "Signal": "99.2%", "Status": "Online"},
        {"Asset": "PV-001",   "Protocol": "SunSpec Modbus TCP", "Host": "192.168.1.11:502",
         "Heartbeat": "3s ago", "Signal": "98.7%", "Status": "Online"},
        {"Asset": "EVC-001",  "Protocol": "OCPP 1.6",           "Host": "192.168.1.20:8080",
         "Heartbeat": "1s ago", "Signal": "100%",  "Status": "1 Session Active"},
        {"Asset": "FLEX-001", "Protocol": "OpenADR 2.0b",        "Host": "vtn.caiso.com",
         "Heartbeat": "14s ago","Signal": "97.1%", "Status": "Online"},
    ])

    section_hdr("Protocol support", "Configured adapters")
    asset_table_html([
        {"Protocol": "SunSpec Modbus TCP",    "Standard": "SunSpec 2.0",  "Assets": "BESS-001, PV-001",  "Status": "Online"},
        {"Protocol": "OCPP 1.6",              "Standard": "IEC 62196",    "Assets": "EVC-001",            "Status": "Online"},
        {"Protocol": "OpenADR 2.0b",          "Standard": "IEC 62746-10", "Assets": "FLEX-001",           "Status": "Online"},
        {"Protocol": "DNP3",                  "Standard": "IEEE 1815",    "Assets": "—",                  "Status": "Standby"},
        {"Protocol": "IEC 61850",             "Standard": "IEC 61850-7",  "Assets": "—",                  "Status": "Standby"},
        {"Protocol": "IEEE 2030.5 (CSIP-AZ)", "Standard": "IEEE 2030.5",  "Assets": "—",                  "Status": "Standby"},
    ])


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Run log
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Run log":
    topbar(interval_str, pct_disp)
    page_heading("HISTORY", "Run log")

    with st.spinner("Running backtest…"):
        sums = cached_backtest(backtest_days, capacity_kwh, power_kw, chemistry, soc_init)

    section_hdr("Strategy comparison", f"{backtest_days}-day backtest · CAISO synthetic LMP")

    rows = [
        {
            "Strategy":        name,
            "Gross Rev ($)":   f"{s.gross_revenue_usd:,.0f}",
            "Degradation ($)": f"{s.total_degradation_cost_usd:,.0f}",
            "Penalties ($)":   f"{s.total_penalty_usd:,.0f}",
            "Risk-Adj ($)":    f"{s.risk_adjusted_revenue_usd:,.0f}",
            "SOH Lost (%)":    f"{s.soh_lost_pct*100:.3f}",
            "Compliance (%)":  f"{s.obligation_compliance_pct:.1f}",
        }
        for name, s in sums.items()
    ]
    df = pd.DataFrame(rows)

    def _hl(row):
        if "Vela" in str(row["Strategy"]):
            return [f"background-color:rgba(9,105,218,0.07);font-weight:600"] * len(row)
        return ["color:#57606a"] * len(row)

    st.dataframe(df.style.apply(_hl, axis=1), use_container_width=True, hide_index=True)

    v = sums.get("Vela"); r = sums.get("Rule-based"); m = sums.get("Myopic")
    if v and r:
        d_rule   = v.risk_adjusted_revenue_usd - r.risk_adjusted_revenue_usd
        d_myopic = (m.risk_adjusted_revenue_usd - v.risk_adjusted_revenue_usd) if m else 0
        kpi_icon_row([
            ("M5 12h14", "Vela vs Rule-based",
             f"+${d_rule:,.0f}",
             f"+{d_rule/max(abs(r.risk_adjusted_revenue_usd),1)*100:.1f}% risk-adj",
             "#dafbe1", "#1a7f37"),
            ("M12 2a10 10 0 100 20 10 10 0 000-20z",
             "Myopic opportunity cost",
             f"${abs(d_myopic):,.0f}",
             "hidden cost of no constraints",
             "#ffebe9", "#cf222e"),
        ])

    section_hdr("Revenue by strategy", "Gross vs risk-adjusted")
    strats = list(sums.keys())
    fig_bt = go.Figure()
    fig_bt.add_trace(go.Bar(name="Gross Revenue", x=strats,
                            y=[s.gross_revenue_usd for s in sums.values()], marker_color=BLUE))
    fig_bt.add_trace(go.Bar(name="Risk-Adj Revenue", x=strats,
                            y=[s.risk_adjusted_revenue_usd for s in sums.values()], marker_color=GREEN))
    fig_bt.add_trace(go.Bar(name="Degradation", x=strats,
                            y=[s.total_degradation_cost_usd for s in sums.values()],
                            marker_color="#ffa8a8", opacity=0.8))
    fig_bt.update_layout(
        barmode="group", height=320,
        xaxis=_ax(grid=False), yaxis=_ax("USD"), **_cl(),
    )
    st.plotly_chart(fig_bt, use_container_width=True)


# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown(
    f'<div style="border-top:1px solid {_BRD};margin-top:1.75rem;padding-top:0.6rem;'
    f'display:flex;justify-content:space-between">'
    f'<span style="font-size:0.57rem;color:{_T3}">VELA v0.1.0 · Multi-Asset VPP Dispatch</span>'
    f'<span style="font-size:0.57rem;color:{_T3}">CAISO · Simulated · 15-min intervals</span>'
    f'</div>',
    unsafe_allow_html=True,
)

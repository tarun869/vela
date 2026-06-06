"""Virtual bidding (INC/DEC) modeling for convergence trading."""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


class VirtualPosition(NamedTuple):
    position_id: str
    node: str
    position_type: str     # "INC" or "DEC"
    hour: int
    mw: float
    da_price: float        # Day-ahead LMP when bid was cleared
    rt_price: float        # Real-time LMP at settlement
    pnl: float             # Realized P&L


@dataclass
class VirtualBiddingStrategy:
    """
    Virtual bidding strategy for energy markets.

    Virtual Bids:
    - INC (Increment): Virtual generation — profit when DA > RT (positive spread)
    - DEC (Decrement): Virtual load — profit when RT > DA (negative spread)

    Convergence trading: exploit systematic differences between DA and RT prices.
    Common patterns:
    - Load pockets with persistent congestion
    - Hydro-heavy regions with uncertain dispatch
    - Wind-heavy regions with RT price drops
    """
    max_mw_per_node: float = 50.0
    min_expected_spread: float = 2.0   # $/MWh — minimum spread to bid
    risk_budget_per_day: float = 5000.0  # $ maximum loss per day

    def compute_inc_position(
        self,
        node: str,
        da_price_forecast: float,
        rt_price_forecast: float,
        historical_spread: list[float],
        hour: int,
    ) -> dict:
        """
        Compute INC (virtual supply) position.

        INC profits when actual RT < DA (we sold high in DA, buy back cheap in RT).
        """
        expected_spread = da_price_forecast - rt_price_forecast
        spread_std = float(np.std(historical_spread)) if len(historical_spread) > 1 else 5.0
        sharpe = expected_spread / (spread_std + 1e-6)

        if expected_spread < self.min_expected_spread or sharpe < 0.5:
            return {"position_type": "INC", "mw": 0.0, "expected_pnl": 0.0, "reason": "insufficient_spread"}

        # Size position proportional to confidence (Sharpe-like)
        mw = min(self.max_mw_per_node, self.max_mw_per_node * min(1.0, sharpe / 3.0))
        expected_pnl = mw * expected_spread

        # Risk check: limit downside
        downside_1sigma = mw * (expected_spread - 2 * spread_std)
        if downside_1sigma < -self.risk_budget_per_day / 24:
            mw *= 0.5  # Halve position if risk is too high

        return {
            "node": node,
            "position_type": "INC",
            "mw": round(mw, 1),
            "hour": hour,
            "da_price": da_price_forecast,
            "rt_price_forecast": rt_price_forecast,
            "expected_spread": expected_spread,
            "expected_pnl": mw * expected_spread,
            "spread_std": spread_std,
            "sharpe": sharpe,
        }

    def compute_dec_position(
        self,
        node: str,
        da_price_forecast: float,
        rt_price_forecast: float,
        historical_spread: list[float],
        hour: int,
    ) -> dict:
        """
        Compute DEC (virtual load) position.

        DEC profits when actual RT > DA (we bought cheap in DA, sell high in RT).
        """
        expected_spread = rt_price_forecast - da_price_forecast
        spread_std = float(np.std(historical_spread)) if len(historical_spread) > 1 else 5.0
        sharpe = expected_spread / (spread_std + 1e-6)

        if expected_spread < self.min_expected_spread or sharpe < 0.5:
            return {"position_type": "DEC", "mw": 0.0, "expected_pnl": 0.0, "reason": "insufficient_spread"}

        mw = min(self.max_mw_per_node, self.max_mw_per_node * min(1.0, sharpe / 3.0))

        return {
            "node": node,
            "position_type": "DEC",
            "mw": round(mw, 1),
            "hour": hour,
            "da_price": da_price_forecast,
            "rt_price_forecast": rt_price_forecast,
            "expected_spread": expected_spread,
            "expected_pnl": mw * expected_spread,
            "spread_std": spread_std,
            "sharpe": sharpe,
        }

    def backtest(
        self,
        da_prices: list[float],
        rt_prices: list[float],
        strategy: str = "INC",
        mw: float = 10.0,
        transaction_cost: float = 0.25,  # $/MWh round-trip
    ) -> dict[str, float]:
        """
        Backtest virtual bidding strategy on historical DA/RT prices.

        Parameters
        ----------
        strategy : str
            "INC" (sell DA / buy RT) or "DEC" (buy DA / sell RT)
        """
        da = np.array(da_prices)
        rt = np.array(rt_prices)
        spread = da - rt if strategy == "INC" else rt - da

        # Trade when spread > transaction cost
        active = spread > transaction_cost
        gross_pnl = np.where(active, spread * mw, 0.0)
        net_pnl = np.where(active, (spread - transaction_cost) * mw, 0.0)

        return {
            "total_gross_pnl": float(np.sum(gross_pnl)),
            "total_net_pnl": float(np.sum(net_pnl)),
            "n_trades": int(np.sum(active)),
            "win_rate": float(np.mean(net_pnl[active] > 0)) if active.any() else 0.0,
            "avg_spread_when_active": float(np.mean(spread[active])) if active.any() else 0.0,
            "avg_pnl_per_mwh": float(np.mean(net_pnl[active])) if active.any() else 0.0,
            "sharpe_ratio": float(np.mean(net_pnl) / (np.std(net_pnl) + 1e-6)),
            "max_daily_loss": float(np.min(net_pnl)),
        }


@dataclass
class DARTSpreadForecaster:
    """
    Day-Ahead / Real-Time (DART) spread forecaster.

    Key predictors of DA-RT spread:
    - Wind/solar forecast error (systematic RT underprediction in wind zones)
    - Load forecast error
    - Congestion patterns (consistent DA/RT congestion divergence)
    - Historical spread autocorrelation
    """
    lags: int = 7  # Days of lag features
    _coeffs: np.ndarray = field(default=None, init=False, repr=False)
    _intercept: float = field(default=0.0, init=False, repr=False)
    _fitted: bool = field(default=False, init=False, repr=False)

    def fit(self, dart_spreads: list[float]) -> None:
        """Fit AR model on DART spread time series."""
        y = np.array(dart_spreads[self.lags:])
        X = np.column_stack([
            dart_spreads[i:len(dart_spreads)-self.lags+i]
            for i in range(self.lags)
        ])
        X = np.hstack([np.ones((len(X), 1)), X])
        result = np.linalg.lstsq(X, y, rcond=None)
        coeffs = result[0]
        self._intercept = float(coeffs[0])
        self._coeffs = coeffs[1:]
        self._fitted = True

    def predict(self, recent_spreads: list[float], horizon: int = 24) -> list[float]:
        assert self._fitted, "Must fit before predicting"
        window = list(recent_spreads[-self.lags:])
        preds = []
        for _ in range(horizon):
            val = self._intercept + float(np.dot(self._coeffs, window[-self.lags:]))
            preds.append(val)
            window.append(val)
        return preds

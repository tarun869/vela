"""
Hedge effectiveness analytics for VPP energy price risk management.

Evaluates forward contracts, futures, and swaps as hedges against
spot price volatility, and computes hedge effectiveness per ASC 815.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np


@dataclass
class HedgeInstrument:
    instrument_id: str
    instrument_type: str    # "swap", "futures", "collar", "option"
    notional_mwh: float
    strike_price: float     # Fixed price in swap/futures
    premium_paid_usd: float = 0.0
    expiry: str = ""


@dataclass
class HedgeEffectiveness:
    instrument_id: str
    effectiveness_ratio: float    # Should be 0.80–1.25 per ASC 815
    regression_slope: float
    r_squared: float
    hedge_ratio: float
    dollar_offset: float          # Ratio of hedged gain to unhedged loss


class HedgeAnalytics:
    """
    Computes hedge effectiveness for energy price hedging instruments.

    ASC 815 (formerly SFAS 133) requires 80–125% effectiveness to qualify
    for hedge accounting.
    """

    def effectiveness(
        self,
        instrument: HedgeInstrument,
        spot_prices: np.ndarray,    # Historical spot prices
        forward_prices: np.ndarray, # Corresponding forward/futures prices
    ) -> HedgeEffectiveness:
        """
        Compute regression-based hedge effectiveness.

        Regress spot price changes on forward price changes.
        R² > 0.80 generally indicates highly effective hedge.
        """
        spot_returns = np.diff(spot_prices)
        fwd_returns = np.diff(forward_prices)

        if len(spot_returns) < 2:
            return HedgeEffectiveness(
                instrument_id=instrument.instrument_id,
                effectiveness_ratio=1.0, regression_slope=1.0,
                r_squared=1.0, hedge_ratio=1.0, dollar_offset=1.0,
            )

        # OLS regression
        A = np.vstack([fwd_returns, np.ones(len(fwd_returns))]).T
        slope, intercept = np.linalg.lstsq(A, spot_returns, rcond=None)[0]

        # R-squared
        residuals = spot_returns - (slope * fwd_returns + intercept)
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((spot_returns - np.mean(spot_returns)) ** 2)
        r2 = 1 - ss_res / max(ss_tot, 1e-9)

        # Dollar offset method
        gain_on_hedge = np.sum(np.diff(forward_prices)) * instrument.notional_mwh
        loss_on_exposure = -np.sum(np.diff(spot_prices)) * instrument.notional_mwh
        dollar_offset = gain_on_hedge / max(abs(loss_on_exposure), 1.0)

        return HedgeEffectiveness(
            instrument_id=instrument.instrument_id,
            effectiveness_ratio=abs(dollar_offset),
            regression_slope=float(slope),
            r_squared=float(r2),
            hedge_ratio=float(slope),
            dollar_offset=float(dollar_offset),
        )

    def optimal_hedge_ratio(
        self,
        spot_prices: np.ndarray,
        forward_prices: np.ndarray,
    ) -> float:
        """Minimum variance hedge ratio h* = Cov(S,F)/Var(F)."""
        spot_ret = np.diff(spot_prices)
        fwd_ret = np.diff(forward_prices)
        cov_sf = float(np.cov(spot_ret, fwd_ret)[0, 1])
        var_f = float(np.var(fwd_ret))
        return cov_sf / max(var_f, 1e-9)

"""
Price elasticity of demand model for demand response programs.

Models how electricity consumers respond to price signals using
own-price and cross-price elasticities across time periods.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class ElasticityParams:
    """Customer class elasticity parameters."""
    customer_class: str      # "residential", "commercial_sm", "commercial_lg", "industrial"
    own_price_elasticity: float      # e_ii < 0, typically -0.1 to -0.5
    cross_price_elasticity: float    # e_ij > 0 (substitution effect), typically 0 to 0.15
    income_elasticity: float = 0.3   # Long-run income effect
    short_run_factor: float = 0.4    # Short-run elasticity = factor * long-run


# Typical literature values
DEFAULT_ELASTICITIES: Dict[str, ElasticityParams] = {
    "residential": ElasticityParams("residential", -0.25, 0.10, 0.3, 0.4),
    "commercial_sm": ElasticityParams("commercial_sm", -0.15, 0.08, 0.2, 0.5),
    "commercial_lg": ElasticityParams("commercial_lg", -0.35, 0.12, 0.2, 0.6),
    "industrial": ElasticityParams("industrial", -0.50, 0.15, 0.15, 0.7),
}


class ElasticityModel:
    """
    Linear log-log price elasticity model for demand response.

    Percentage change in demand = elasticity * percentage change in price.

    For multi-period models (time-of-use pricing):
        q_i_new = q_i_base * (1 + e_ii * (p_i_new - p_i_base)/p_i_base
                                + sum_j(e_ij * (p_j_new - p_j_base)/p_j_base))
    """

    def __init__(self, params: ElasticityParams, base_price_usd_kwh: float = 0.12) -> None:
        self.params = params
        self.base_price = base_price_usd_kwh

    def demand_response(
        self,
        base_load_kw: float,
        new_price_usd_kwh: float,
        base_price: Optional[float] = None,
    ) -> Tuple[float, float]:
        """
        Compute demand after a price change.

        Returns:
            (new_demand_kw, change_kw)
        """
        p0 = base_price or self.base_price
        if p0 <= 0:
            return base_load_kw, 0.0

        dp_pct = (new_price_usd_kwh - p0) / p0
        elasticity = self.params.own_price_elasticity * self.params.short_run_factor

        dq_pct = elasticity * dp_pct
        new_demand = base_load_kw * (1.0 + dq_pct)
        new_demand = max(0.0, new_demand)
        return new_demand, new_demand - base_load_kw

    def tou_response(
        self,
        base_loads_kw: List[float],       # Load profile across periods
        new_prices_usd_kwh: List[float],  # New TOU prices per period
        base_prices_usd_kwh: List[float], # Base prices per period
    ) -> List[float]:
        """
        Compute demand response across multiple TOU periods with cross-elasticity.

        Returns adjusted load profile (kW per period).
        """
        n = len(base_loads_kw)
        assert len(new_prices_usd_kwh) == n and len(base_prices_usd_kwh) == n

        e_own = self.params.own_price_elasticity * self.params.short_run_factor
        e_cross = self.params.cross_price_elasticity * self.params.short_run_factor

        new_loads: List[float] = []
        for i in range(n):
            p0_i = base_prices_usd_kwh[i]
            dp_i = (new_prices_usd_kwh[i] - p0_i) / max(p0_i, 0.001)

            # Cross-period effects
            cross_effect = sum(
                e_cross * (new_prices_usd_kwh[j] - base_prices_usd_kwh[j]) / max(base_prices_usd_kwh[j], 0.001)
                for j in range(n) if j != i
            )

            dq_pct = e_own * dp_i + cross_effect
            new_load = max(0.0, base_loads_kw[i] * (1.0 + dq_pct))
            new_loads.append(new_load)

        # Enforce load conservation (shifted demand doesn't disappear)
        original_total = sum(base_loads_kw)
        new_total = sum(new_loads)
        if new_total > 0 and abs(new_total - original_total) / max(original_total, 1) > 0.30:
            # More than 30% total change — scale back (energy cannot be created)
            scale = original_total / new_total
            new_loads = [q * scale for q in new_loads]

        return new_loads

    def price_elasticity_arc(
        self,
        q1: float, q2: float, p1: float, p2: float
    ) -> float:
        """Compute arc price elasticity between two observations."""
        if p1 == p2 or q1 == q2:
            return 0.0
        return ((q2 - q1) / ((q2 + q1) / 2)) / ((p2 - p1) / ((p2 + p1) / 2))

    def critical_peak_reduction(
        self,
        base_load_kw: float,
        cpp_multiplier: float = 4.0,
        base_price: Optional[float] = None,
    ) -> float:
        """
        Estimate demand reduction during Critical Peak Pricing event.

        Args:
            cpp_multiplier: CPP price = multiplier * base price.

        Returns:
            Expected reduction (kW).
        """
        p0 = base_price or self.base_price
        p_cpp = p0 * cpp_multiplier
        new_demand, reduction = self.demand_response(base_load_kw, p_cpp, p0)
        return abs(reduction)


class PortfolioElasticityModel:
    """
    Aggregate elasticity model for a mixed portfolio of customer types.
    """

    def __init__(
        self,
        customer_mix: Dict[str, float],   # customer_class -> fraction of total load
        total_load_kw: float = 10000.0,
        base_price_usd_kwh: float = 0.12,
    ) -> None:
        self.customer_mix = customer_mix
        self.total_load_kw = total_load_kw
        self.base_price = base_price_usd_kwh
        self._models = {
            cls: ElasticityModel(
                DEFAULT_ELASTICITIES.get(cls, DEFAULT_ELASTICITIES["commercial_sm"]),
                base_price_usd_kwh
            )
            for cls in customer_mix
        }

    def aggregate_response(self, new_price_usd_kwh: float) -> Tuple[float, float]:
        """
        Compute fleet-wide demand response to a uniform price change.

        Returns:
            (new_total_demand_kw, total_reduction_kw)
        """
        total_new = 0.0
        for cls, fraction in self.customer_mix.items():
            base = self.total_load_kw * fraction
            model = self._models[cls]
            new_demand, _ = model.demand_response(base, new_price_usd_kwh)
            total_new += new_demand
        return total_new, self.total_load_kw - total_new

    def dr_potential_by_price(
        self, price_range: List[float]
    ) -> Dict[float, float]:
        """
        Compute achievable DR at each price point.

        Returns dict of price_usd_kwh -> reduction_kw.
        """
        return {
            p: self.aggregate_response(p)[1]
            for p in price_range
        }

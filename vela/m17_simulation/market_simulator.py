"""
Synthetic market price generator for VPP simulation and testing.

Generates realistic electricity price scenarios using:
  - Seasonal and diurnal patterns
  - Mean-reversion with stochastic volatility
  - Price spikes from supply-demand dynamics
  - Negative price periods from renewable oversupply
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class MarketSimParams:
    """Parameters for synthetic market price generation."""
    # Base price structure
    base_price_usd_mwh: float = 35.0
    # Mean reversion (Ornstein-Uhlenbeck)
    mean_reversion_speed: float = 3.0     # kappa: reversion speed (per year)
    price_volatility: float = 20.0        # sigma: price volatility ($/MWh/sqrt(year))
    # Seasonal/diurnal multipliers
    peak_multiplier: float = 2.5          # Peak hour price multiplier
    off_peak_multiplier: float = 0.6      # Off-peak multiplier
    weekend_discount: float = 0.85        # Weekend price discount
    # Price spikes
    spike_probability_per_hour: float = 0.002
    spike_magnitude_usd_mwh: float = 200.0
    spike_duration_hours: int = 2
    # Negative prices
    negative_price_probability: float = 0.01
    negative_price_magnitude: float = -20.0
    # Stochastic volatility
    vol_mean_reversion: float = 2.0
    vol_of_vol: float = 0.5
    # Annual seasonality
    summer_premium: float = 0.20          # Summer peak premium (fraction)
    winter_premium: float = 0.15          # Winter heating premium


class MarketSimulator:
    """
    Synthetic electricity market price generator.

    Supports ERCOT, CAISO, PJM-style price profiles.
    """

    # Typical diurnal shape (hourly multipliers 0–23)
    DIURNAL_SHAPE = [
        0.65, 0.60, 0.58, 0.57, 0.60, 0.70,
        0.85, 1.00, 1.15, 1.20, 1.18, 1.15,
        1.12, 1.10, 1.05, 1.05, 1.10, 1.25,
        1.40, 1.45, 1.40, 1.30, 1.15, 0.90,
    ]

    def __init__(self, params: MarketSimParams, seed: int = 42) -> None:
        self.params = params
        self.rng = default_rng(seed)

    def generate_hourly(
        self,
        n_hours: int = 8760,
        start_hour_of_year: int = 0,
    ) -> np.ndarray:
        """
        Generate hourly day-ahead price series.

        Returns:
            Array of prices ($/MWh) of length n_hours.
        """
        p = self.params
        dt = 1.0 / 8760.0  # 1 hour in years
        prices = np.zeros(n_hours)
        z = self.rng.standard_normal(n_hours)
        vol_z = self.rng.standard_normal(n_hours)

        # Stochastic volatility (log-normal vol process)
        sigma = np.zeros(n_hours)
        sigma[0] = p.price_volatility
        for t in range(1, n_hours):
            dsigma = (p.vol_mean_reversion * (p.price_volatility - sigma[t-1]) * dt
                      + p.vol_of_vol * sigma[t-1] * np.sqrt(dt) * vol_z[t])
            sigma[t] = max(1.0, sigma[t-1] + dsigma)

        # Ornstein-Uhlenbeck mean-reverting price
        price = p.base_price_usd_mwh
        for t in range(n_hours):
            hour_of_day = (start_hour_of_year + t) % 24
            day_of_year = (start_hour_of_year + t) // 24
            day_of_week = (day_of_year % 7)  # 0=Mon

            # Seasonal multiplier (sinusoidal)
            seasonal = 1.0 + p.summer_premium * np.sin(2 * np.pi * day_of_year / 365 - np.pi/2)

            # Diurnal and weekday multipliers
            diurnal = self.DIURNAL_SHAPE[hour_of_day]
            weekday_mult = 1.0 if day_of_week < 5 else p.weekend_discount

            # Mean-reversion equilibrium at base * seasonal * diurnal
            mu_t = p.base_price_usd_mwh * seasonal * diurnal * weekday_mult

            # OU increment
            dp = (p.mean_reversion_speed * (mu_t - price) * dt
                  + sigma[t] * np.sqrt(dt) * z[t])
            price = price + dp

            prices[t] = price

        # Add price spikes
        spike_mask = self.rng.random(n_hours) < p.spike_probability_per_hour
        spike_starts = np.where(spike_mask)[0]
        for start in spike_starts:
            end = min(start + p.spike_duration_hours, n_hours)
            prices[start:end] += p.spike_magnitude_usd_mwh

        # Add negative price events
        neg_mask = self.rng.random(n_hours) < p.negative_price_probability
        prices[neg_mask] = np.minimum(prices[neg_mask], p.negative_price_magnitude)

        return prices

    def generate_realtime(
        self,
        day_ahead_prices: np.ndarray,
        rt_premium_mean: float = 0.0,
        rt_premium_std: float = 5.0,
    ) -> np.ndarray:
        """
        Generate real-time prices as perturbations around day-ahead.

        Returns:
            Real-time 5-minute prices (12x hourly resolution).
        """
        n_hours = len(day_ahead_prices)
        n_intervals = n_hours * 12   # 5-minute intervals
        rt_prices = np.zeros(n_intervals)

        for h in range(n_hours):
            da_price = day_ahead_prices[h]
            for m in range(12):
                t = h * 12 + m
                noise = self.rng.normal(rt_premium_mean, rt_premium_std)
                rt_prices[t] = da_price + noise

        return rt_prices

    def generate_ancillary_prices(
        self,
        n_hours: int = 8760,
        regulation_up_premium: float = 10.0,
        regulation_dn_premium: float = 5.0,
        spinning_premium: float = 3.0,
    ) -> Dict[str, np.ndarray]:
        """
        Generate correlated ancillary service price series.

        Returns:
            Dict of service -> price array.
        """
        energy = self.generate_hourly(n_hours)

        corr_noise = lambda std: std * self.rng.standard_normal(n_hours)

        return {
            "energy": energy,
            "reg_up": np.maximum(0, energy * 0.3 + regulation_up_premium + corr_noise(5.0)),
            "reg_dn": np.maximum(0, energy * 0.2 + regulation_dn_premium + corr_noise(3.0)),
            "spinning": np.maximum(0, energy * 0.1 + spinning_premium + corr_noise(2.0)),
            "non_spinning": np.maximum(0, energy * 0.08 + 2.0 + corr_noise(1.5)),
        }

    def stress_scenario(
        self,
        n_hours: int = 168,
        scenario_type: str = "heat_wave",
    ) -> np.ndarray:
        """
        Generate stress price scenario.

        Types: "heat_wave", "cold_snap", "renewable_glut", "outage".
        """
        base = self.generate_hourly(n_hours)

        if scenario_type == "heat_wave":
            # Prices spike 3x during peak hours over 5 days
            multiplier = np.ones(n_hours)
            for h in range(min(n_hours, 120)):
                if 14 <= h % 24 <= 20:
                    multiplier[h] = 3.5
            return base * multiplier

        elif scenario_type == "cold_snap":
            return base * 2.5 + self.rng.exponential(50, n_hours)

        elif scenario_type == "renewable_glut":
            prices = base.copy()
            # Negative prices for 30% of hours
            neg_idx = self.rng.choice(n_hours, n_hours // 3, replace=False)
            prices[neg_idx] = self.rng.uniform(-50, 0, len(neg_idx))
            return prices

        elif scenario_type == "outage":
            prices = base.copy()
            outage_start = n_hours // 3
            prices[outage_start:outage_start + 24] *= 8.0
            return prices

        return base

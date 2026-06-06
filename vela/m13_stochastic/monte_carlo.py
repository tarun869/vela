"""
Monte Carlo simulation for revenue risk analysis of VPP dispatch strategies.

Simulates revenue distribution under uncertain prices, load, and renewable output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
import numpy as np
from numpy.random import default_rng


@dataclass
class StochasticInputs:
    """Probability distributions for key uncertain inputs."""
    price_mean_usd_mwh: float = 45.0
    price_std_usd_mwh: float = 15.0
    price_spike_probability: float = 0.02    # Probability of price spike per interval
    price_spike_multiplier: float = 5.0      # Spike magnitude multiplier
    load_mean_kw: float = 1000.0
    load_std_kw: float = 150.0
    solar_capacity_kw: float = 500.0
    solar_cf_mean: float = 0.20              # Mean capacity factor
    solar_cf_std: float = 0.08
    wind_capacity_kw: float = 300.0
    wind_cf_mean: float = 0.30
    wind_cf_std: float = 0.12


@dataclass
class SimulationResult:
    n_scenarios: int
    n_periods: int
    revenue_usd: np.ndarray          # Shape (n_scenarios,)
    price_paths: np.ndarray          # Shape (n_scenarios, n_periods)
    load_paths: np.ndarray
    solar_paths: np.ndarray
    wind_paths: np.ndarray
    percentile_10: float
    percentile_50: float
    percentile_90: float
    mean_revenue: float
    std_revenue: float


class MonteCarloSimulator:
    """
    Monte Carlo simulation engine for VPP revenue risk analysis.

    Supports:
      - Correlated price/load/renewable sampling
      - Jump-diffusion price process (price spikes)
      - Antithetic variates variance reduction
    """

    def __init__(
        self,
        inputs: StochasticInputs,
        dispatch_fn: Optional[Callable] = None,
        seed: int = 42,
    ) -> None:
        self.inputs = inputs
        self.dispatch_fn = dispatch_fn or self._default_dispatch
        self.rng = default_rng(seed)

    @staticmethod
    def _default_dispatch(
        price: np.ndarray,
        load: np.ndarray,
        solar: np.ndarray,
        wind: np.ndarray,
    ) -> np.ndarray:
        """
        Default dispatch: export excess renewable generation at spot price.
        Revenue = max(solar + wind - load, 0) * price
        """
        net_gen = np.maximum(solar + wind - load, 0.0)
        return net_gen * price / 1000.0  # $/kWh -> $/MWh conversion

    def _generate_price_path(self, n_periods: int) -> np.ndarray:
        """
        Jump-diffusion price process (Merton model).
        P_t = mu + sigma*Z + jump_component
        """
        z = self.rng.standard_normal(n_periods)
        prices = self.inputs.price_mean_usd_mwh + self.inputs.price_std_usd_mwh * z

        # Add price spikes (Poisson jumps)
        spikes = self.rng.random(n_periods) < self.inputs.price_spike_probability
        spike_sizes = self.rng.exponential(
            self.inputs.price_mean_usd_mwh * (self.inputs.price_spike_multiplier - 1),
            n_periods
        )
        prices = prices + spikes * spike_sizes
        return np.maximum(prices, -50.0)  # Allow negative prices

    def _generate_load_path(self, n_periods: int) -> np.ndarray:
        z = self.rng.standard_normal(n_periods)
        loads = self.inputs.load_mean_kw + self.inputs.load_std_kw * z
        return np.maximum(loads, 0.0)

    def _generate_solar_path(self, n_periods: int) -> np.ndarray:
        # Beta distribution for capacity factor (bounded 0–1)
        alpha = self.inputs.solar_cf_mean ** 2 * (1 - self.inputs.solar_cf_mean) / max(self.inputs.solar_cf_std**2, 1e-6) - self.inputs.solar_cf_mean
        beta = alpha * (1 - self.inputs.solar_cf_mean) / max(self.inputs.solar_cf_mean, 0.01)
        alpha, beta = max(0.5, alpha), max(0.5, beta)
        cf = self.rng.beta(alpha, beta, n_periods)
        return cf * self.inputs.solar_capacity_kw

    def _generate_wind_path(self, n_periods: int) -> np.ndarray:
        # Weibull distribution for wind
        k = 2.0  # Shape parameter (Rayleigh distribution)
        scale = self.inputs.wind_cf_mean * self.inputs.wind_capacity_kw
        wind = self.rng.weibull(k, n_periods) * scale
        return np.minimum(wind, self.inputs.wind_capacity_kw)

    def run(
        self,
        n_scenarios: int = 1000,
        n_periods: int = 8760,
        use_antithetic: bool = True,
    ) -> SimulationResult:
        """
        Run Monte Carlo simulation.

        Args:
            n_scenarios: Number of Monte Carlo scenarios.
            n_periods: Time steps per scenario (8760 = hourly annual).
            use_antithetic: Use antithetic variates for variance reduction.

        Returns:
            SimulationResult with revenue distribution.
        """
        actual_scenarios = n_scenarios // 2 if use_antithetic else n_scenarios
        revenues: List[float] = []
        price_paths = []
        load_paths = []
        solar_paths = []
        wind_paths = []

        for i in range(actual_scenarios):
            prices = self._generate_price_path(n_periods)
            loads = self._generate_load_path(n_periods)
            solar = self._generate_solar_path(n_periods)
            wind = self._generate_wind_path(n_periods)

            rev = float(self.dispatch_fn(prices, loads, solar, wind).sum())
            revenues.append(rev)
            price_paths.append(prices)
            load_paths.append(loads)
            solar_paths.append(solar)
            wind_paths.append(wind)

            if use_antithetic:
                # Antithetic: negate standard normal draws
                prices_a = 2 * self.inputs.price_mean_usd_mwh - prices
                loads_a = 2 * self.inputs.load_mean_kw - loads
                solar_a = self.inputs.solar_capacity_kw - solar
                wind_a = self.inputs.wind_capacity_kw - wind

                rev_a = float(self.dispatch_fn(prices_a, loads_a, solar_a, wind_a).sum())
                revenues.append(rev_a)
                price_paths.append(prices_a)
                load_paths.append(loads_a)
                solar_paths.append(solar_a)
                wind_paths.append(wind_a)

        rev_arr = np.array(revenues)
        return SimulationResult(
            n_scenarios=len(revenues),
            n_periods=n_periods,
            revenue_usd=rev_arr,
            price_paths=np.array(price_paths[:n_scenarios]),
            load_paths=np.array(load_paths[:n_scenarios]),
            solar_paths=np.array(solar_paths[:n_scenarios]),
            wind_paths=np.array(wind_paths[:n_scenarios]),
            percentile_10=float(np.percentile(rev_arr, 10)),
            percentile_50=float(np.percentile(rev_arr, 50)),
            percentile_90=float(np.percentile(rev_arr, 90)),
            mean_revenue=float(rev_arr.mean()),
            std_revenue=float(rev_arr.std()),
        )

    def sensitivity_analysis(
        self,
        param_name: str,
        param_values: List[float],
        n_scenarios: int = 500,
        n_periods: int = 8760,
    ) -> Dict[float, float]:
        """
        One-at-a-time sensitivity: vary one parameter and report mean revenue.

        Returns dict of param_value -> mean_revenue.
        """
        original_value = getattr(self.inputs, param_name)
        results: Dict[float, float] = {}

        for val in param_values:
            setattr(self.inputs, param_name, val)
            sim = self.run(n_scenarios=n_scenarios, n_periods=n_periods)
            results[val] = sim.mean_revenue

        setattr(self.inputs, param_name, original_value)
        return results

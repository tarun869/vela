"""Model Predictive Control (MPC) formulation for rolling-horizon battery dispatch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class MPCSolution(NamedTuple):
    status: str
    action_charge_mw: float      # Implemented first-period charge action
    action_discharge_mw: float   # Implemented first-period discharge action
    predicted_trajectory: dict[str, list[float]]
    objective_value: float
    solve_time_s: float


@dataclass
class MPCState:
    """Current state of the MPC controller."""
    soc: float          # State of charge (0-1)
    last_charge: float  # MW charged in last interval
    last_discharge: float  # MW discharged in last interval


@dataclass
class MPCController:
    """
    Model Predictive Control controller for single-asset battery dispatch.

    At each time step:
    1. Receive current SOC and updated price forecast
    2. Solve optimization over prediction horizon
    3. Apply only the first-period decision
    4. Re-solve at next time step (receding horizon)

    This receding horizon approach handles model mismatch and forecast uncertainty
    through continuous re-planning.

    Objective:
        max sum_{t=0}^{H-1} [ gamma^t * (p_dis[t]*lmp[t] - p_ch[t]*lmp[t]/rte)
                               - alpha * (soc[t] - soc_target)^2 ]

    where gamma is a discount factor (prioritize near-term certainty) and the
    quadratic SOC term penalizes deviations from a target SOC.
    """
    capacity_mwh: float = 10.0
    power_mw: float = 5.0
    rte: float = 0.92
    soc_min: float = 0.05
    soc_max: float = 0.95
    prediction_horizon: int = 24
    dt_hours: float = 1.0
    discount_factor: float = 0.98    # Prioritize near-term revenue
    soc_target: float = 0.5          # Target SOC (penalize deviations)
    soc_penalty: float = 0.5         # Quadratic SOC penalty weight $/MWh
    terminal_soc_weight: float = 5.0  # Strong terminal SOC penalty
    _current_soc: float = field(default=0.5, init=False, repr=False)

    @property
    def current_soc(self) -> float:
        return self._current_soc

    def reset(self, initial_soc: float = 0.5) -> None:
        self._current_soc = float(np.clip(initial_soc, self.soc_min, self.soc_max))

    def step(
        self,
        lmp_forecast: list[float],
        as_value: list[float] | None = None,
    ) -> MPCSolution:
        """
        Execute one MPC step.

        Solves the prediction horizon problem, extracts and applies the first action.
        Updates internal SOC.

        Parameters
        ----------
        lmp_forecast : list[float]
            Price forecast for next H intervals ($/MWh)
        as_value : list[float], optional
            Combined ancillary services value ($/MWh) per interval

        Returns
        -------
        MPCSolution
            First-period action + full predicted trajectory
        """
        import time
        t0 = time.perf_counter()

        H = min(self.prediction_horizon, len(lmp_forecast))
        lmp = np.array(lmp_forecast[:H])
        av = np.array(as_value[:H]) if as_value else np.zeros(H)

        try:
            import highspy
            sol = self._solve_highs(lmp, av, H)
        except ImportError:
            sol = self._solve_numpy(lmp, av, H)

        solve_time = time.perf_counter() - t0
        # Apply first action
        ch0 = sol["charge"][0]
        dis0 = sol["discharge"][0]
        self._current_soc = float(np.clip(
            self._current_soc + ch0 * self.rte * self.dt_hours / self.capacity_mwh
            - dis0 * self.dt_hours / self.capacity_mwh,
            self.soc_min, self.soc_max
        ))

        return MPCSolution(
            status=sol["status"],
            action_charge_mw=ch0,
            action_discharge_mw=dis0,
            predicted_trajectory={"charge": sol["charge"], "discharge": sol["discharge"], "soc": sol["soc"]},
            objective_value=sol["obj"],
            solve_time_s=solve_time,
        )

    def _solve_highs(self, lmp: np.ndarray, av: np.ndarray, H: int) -> dict:
        import highspy
        h = highspy.Highs()
        h.silent()

        var_count = 0
        ch_idx = {}
        dis_idx = {}
        soc_idx = {}

        for t in range(H):
            ch_idx[t] = var_count; h.addVar(0, self.power_mw); var_count += 1
        for t in range(H):
            dis_idx[t] = var_count; h.addVar(0, self.power_mw); var_count += 1
        for t in range(H):
            soc_idx[t] = var_count
            h.addVar(self.soc_min * self.capacity_mwh, self.soc_max * self.capacity_mwh)
            var_count += 1

        # Objective (linear part; quadratic SOC penalty linearized as abs deviation)
        obj = [0.0] * var_count
        for t in range(H):
            gamma_t = self.discount_factor ** t
            obj[dis_idx[t]] = gamma_t * (lmp[t] + av[t]) * self.dt_hours
            obj[ch_idx[t]] = -gamma_t * lmp[t] * self.dt_hours / self.rte

        h.changeColsCostByRange(0, var_count - 1, obj)
        h.changeObjectiveSense(highspy.ObjSense.kMaximize)

        # SOC dynamics
        for t in range(H):
            if t == 0:
                row_idx = [soc_idx[t], ch_idx[t], dis_idx[t]]
                coeffs = [1.0, -self.rte * self.dt_hours, self.dt_hours]
                rhs = self._current_soc * self.capacity_mwh
                h.addRow(rhs, rhs, 3, row_idx, coeffs)
            else:
                row_idx = [soc_idx[t], soc_idx[t-1], ch_idx[t], dis_idx[t]]
                coeffs = [1.0, -1.0, -self.rte * self.dt_hours, self.dt_hours]
                h.addRow(0.0, 0.0, 4, row_idx, coeffs)

        # Mutual exclusivity via total power bound
        for t in range(H):
            h.addRow(0, self.power_mw, 2, [ch_idx[t], dis_idx[t]], [1.0, 1.0])

        h.run()
        sol = h.getSolution()
        cv = sol.col_value

        charge = [cv[ch_idx[t]] for t in range(H)]
        discharge = [cv[dis_idx[t]] for t in range(H)]
        soc = [cv[soc_idx[t]] / self.capacity_mwh for t in range(H)]
        obj_val = sum(
            (discharge[t] * (lmp[t] + av[t]) - charge[t] * lmp[t] / self.rte) * self.dt_hours
            for t in range(H)
        )
        return {"status": "optimal", "charge": charge, "discharge": discharge, "soc": soc, "obj": obj_val}

    def _solve_numpy(self, lmp: np.ndarray, av: np.ndarray, H: int) -> dict:
        """Greedy MPC fallback."""
        soc = self._current_soc
        charge, discharge, soc_traj = [], [], []
        median_lmp = float(np.median(lmp))
        for t in range(H):
            if lmp[t] > median_lmp * 1.15 and soc > self.soc_min + 0.05:
                dis = min(self.power_mw, (soc - self.soc_min) * self.capacity_mwh / self.dt_hours)
                soc -= dis * self.dt_hours / self.capacity_mwh
                charge.append(0.0); discharge.append(dis)
            elif lmp[t] < median_lmp * 0.85 and soc < self.soc_max - 0.05:
                ch = min(self.power_mw, (self.soc_max - soc) * self.capacity_mwh / self.dt_hours)
                soc += ch * self.rte * self.dt_hours / self.capacity_mwh
                charge.append(ch); discharge.append(0.0)
            else:
                charge.append(0.0); discharge.append(0.0)
            soc = float(np.clip(soc, self.soc_min, self.soc_max))
            soc_traj.append(soc)
        obj = sum((discharge[t] * lmp[t] - charge[t] * lmp[t] / self.rte) * self.dt_hours for t in range(H))
        return {"status": "greedy", "charge": charge, "discharge": discharge, "soc": soc_traj, "obj": obj}

    def run_simulation(
        self,
        lmp_series: list[float],
        forecast_horizon: int | None = None,
    ) -> dict[str, list[float]]:
        """
        Run closed-loop MPC simulation over a full price series.

        Parameters
        ----------
        lmp_series : list[float]
            Full LMP time series (actual prices)
        forecast_horizon : int, optional
            How many periods ahead to use as forecast (defaults to prediction_horizon)

        Returns
        -------
        dict with keys: charge, discharge, soc, revenue
        """
        fh = forecast_horizon or self.prediction_horizon
        T = len(lmp_series)
        charges, discharges, socs, revenues = [], [], [], []
        self.reset()

        for t in range(T):
            # Perfect foresight forecast within horizon (or use actuals as proxy)
            forecast = lmp_series[t:t+fh] + [lmp_series[-1]] * max(0, fh - (T - t))
            sol = self.step(forecast)
            charges.append(sol.action_charge_mw)
            discharges.append(sol.action_discharge_mw)
            socs.append(self._current_soc)
            revenues.append(
                (sol.action_discharge_mw - sol.action_charge_mw) * lmp_series[t] * self.dt_hours
            )

        return {"charge": charges, "discharge": discharges, "soc": socs, "revenue": revenues}

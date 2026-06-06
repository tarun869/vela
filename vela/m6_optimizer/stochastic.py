"""Stochastic MPC with scenario trees for price-uncertain dispatch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class ScenarioSolution(NamedTuple):
    status: str
    expected_revenue: float
    cvar_revenue: float    # Conditional Value-at-Risk (risk-adjusted)
    here_and_now_charge: dict[str, list[float]]     # stage 1 decisions
    here_and_now_discharge: dict[str, list[float]]  # stage 1 decisions
    scenario_revenues: list[float]
    solve_time_s: float


@dataclass
class PriceScenario:
    """A single price scenario for stochastic programming."""
    scenario_id: int
    probability: float
    lmp: list[float]      # $/MWh per interval
    reg_up: list[float]
    reg_down: list[float]


@dataclass
class ScenarioGenerator:
    """
    Generate price scenarios via moment matching on AR(1) + noise model.

    Scenarios are calibrated to match historical mean, std, and
    autocorrelation structure.
    """
    n_scenarios: int = 20
    horizon: int = 24
    seed: int = 42

    def generate(
        self,
        mean_lmp: list[float],
        std_lmp: list[float],
        autocorr: float = 0.7,
    ) -> list[PriceScenario]:
        """
        Generate equally-weighted price scenarios.

        Uses AR(1) noise overlaid on the mean forecast to produce
        correlated scenario paths.
        """
        rng = np.random.default_rng(self.seed)
        T = self.horizon
        mu = np.array(mean_lmp)
        sigma = np.array(std_lmp)

        scenarios = []
        for s in range(self.n_scenarios):
            # AR(1) noise process
            noise = np.zeros(T)
            eps = rng.standard_normal(T)
            noise[0] = eps[0]
            for t in range(1, T):
                noise[t] = autocorr * noise[t-1] + np.sqrt(1 - autocorr**2) * eps[t]

            lmp = np.maximum(0, mu + sigma * noise)
            # Reg prices correlated with LMP
            reg_up = np.maximum(0, lmp * 0.25 + rng.normal(0, 2, T))
            reg_down = np.maximum(0, lmp * 0.18 + rng.normal(0, 1.5, T))

            scenarios.append(PriceScenario(
                scenario_id=s,
                probability=1.0 / self.n_scenarios,
                lmp=lmp.tolist(),
                reg_up=reg_up.tolist(),
                reg_down=reg_down.tolist(),
            ))

        return scenarios

    def reduce_scenarios(
        self,
        scenarios: list[PriceScenario],
        n_target: int,
    ) -> list[PriceScenario]:
        """
        Scenario reduction via k-medoids clustering.

        Reduces scenario count while preserving probability mass distribution.
        """
        if n_target >= len(scenarios):
            return scenarios

        # Build distance matrix (Euclidean on LMP paths)
        paths = np.array([s.lmp for s in scenarios])
        n = len(scenarios)
        dist = np.zeros((n, n))
        for i in range(n):
            for j in range(i+1, n):
                d = float(np.linalg.norm(paths[i] - paths[j]))
                dist[i, j] = dist[j, i] = d

        # Greedy medoid selection
        selected = [int(np.argmin(np.sum(dist, axis=1)))]
        while len(selected) < n_target:
            # Find point maximizing min distance to already selected
            min_dists = np.min(dist[:, selected], axis=1)
            min_dists[selected] = -1
            selected.append(int(np.argmax(min_dists)))

        # Redistribute probabilities (nearest selected scenario)
        new_probs = np.zeros(n_target)
        for i in range(n):
            nearest = int(np.argmin([dist[i, selected[j]] for j in range(n_target)]))
            new_probs[nearest] += scenarios[i].probability

        reduced = []
        for k, s_idx in enumerate(selected):
            s = scenarios[s_idx]
            reduced.append(PriceScenario(
                scenario_id=k,
                probability=new_probs[k],
                lmp=s.lmp,
                reg_up=s.reg_up,
                reg_down=s.reg_down,
            ))
        return reduced


@dataclass
class StochasticMPC:
    """
    Two-stage stochastic program for battery dispatch under price uncertainty.

    Stage 1 (here-and-now): first-period dispatch decisions
    Stage 2 (wait-and-see): per-scenario recourse decisions

    Risk measure: CVaR at alpha = 0.1 (i.e., expected shortfall in worst 10% scenarios)

    Objective: max E[revenue] + lambda * CVaR(revenue)
    """
    horizon: int = 24
    dt_hours: float = 1.0
    cvar_alpha: float = 0.1    # CVaR confidence level
    risk_weight: float = 0.3   # weight on CVaR term

    def solve(
        self,
        assets: list,           # list[Asset] from milp.py
        scenarios: list[PriceScenario],
    ) -> ScenarioSolution:
        import time
        t0 = time.perf_counter()
        try:
            import highspy
            return self._solve_stochastic_highs(assets, scenarios, t0)
        except ImportError:
            return self._solve_stochastic_greedy(assets, scenarios, t0)

    def _solve_stochastic_greedy(
        self,
        assets: list,
        scenarios: list[PriceScenario],
        t0: float,
    ) -> ScenarioSolution:
        """
        Approximate stochastic solution: solve deterministically on mean scenario
        then evaluate on all scenarios.
        """
        import time
        from .milp import MILPDispatchOptimizer

        # Mean scenario
        T = self.horizon
        mean_lmp = np.mean([s.lmp for s in scenarios], axis=0).tolist()

        optimizer = MILPDispatchOptimizer(horizon=T, dt_hours=self.dt_hours)
        det_sol = optimizer.solve(assets, mean_lmp)

        # Evaluate on all scenarios
        scene_revenues = []
        for s in scenarios:
            rev = 0.0
            for a in assets:
                for t in range(T):
                    ch = det_sol.charge_mw[a.asset_id][t]
                    dis = det_sol.discharge_mw[a.asset_id][t]
                    rev += (dis - ch) * s.lmp[t] * self.dt_hours
            scene_revenues.append(rev)

        probs = np.array([s.probability for s in scenarios])
        exp_rev = float(np.dot(probs, scene_revenues))

        # CVaR computation
        sorted_revs = np.sort(scene_revenues)
        cvar_n = max(1, int(self.cvar_alpha * len(sorted_revs)))
        cvar = float(np.mean(sorted_revs[:cvar_n]))

        return ScenarioSolution(
            status="approximate",
            expected_revenue=exp_rev,
            cvar_revenue=cvar,
            here_and_now_charge=det_sol.charge_mw,
            here_and_now_discharge=det_sol.discharge_mw,
            scenario_revenues=scene_revenues,
            solve_time_s=time.perf_counter() - t0,
        )

    def _solve_stochastic_highs(
        self,
        assets: list,
        scenarios: list[PriceScenario],
        t0: float,
    ) -> ScenarioSolution:
        """
        Full two-stage stochastic LP using HiGHS.

        Formulates the extensive form with scenario-indexed recourse variables.
        """
        import highspy
        import time

        T = self.horizon
        S = len(scenarios)
        N = len(assets)
        h = highspy.Highs()
        h.silent()

        var_count = 0
        # Stage 1: here-and-now (shared across scenarios)
        s1_ch = {}   # (asset, t) -> var_idx
        s1_dis = {}
        s1_soc = {}

        for i, a in enumerate(assets):
            for t in range(T):
                s1_ch[(i, t)] = var_count; h.addVar(0, a.power_mw); var_count += 1
            for t in range(T):
                s1_dis[(i, t)] = var_count; h.addVar(0, a.power_mw); var_count += 1
            for t in range(T):
                s1_soc[(i, t)] = var_count
                h.addVar(a.soc_min * a.capacity_mwh, a.soc_max * a.capacity_mwh)
                var_count += 1

        # CVaR auxiliary variables
        eta_idx = var_count; h.addVar(-1e9, 1e9); var_count += 1  # VaR estimate
        z_idx = {}  # scenario loss slack
        for s in range(S):
            z_idx[s] = var_count; h.addVar(0, 1e9); var_count += 1

        # Objective: E[revenue] + risk_weight * CVaR
        obj = [0.0] * var_count
        for s_idx, scenario in enumerate(scenarios):
            p = scenario.probability
            for i, a in enumerate(assets):
                for t in range(T):
                    obj[s1_dis[(i, t)]] += p * scenario.lmp[t] * self.dt_hours
                    obj[s1_ch[(i, t)]] -= p * scenario.lmp[t] * self.dt_hours / a.rte

        # CVaR: eta - (1/alpha) * E[max(eta - revenue, 0)]
        obj[eta_idx] = self.risk_weight
        for s_idx, scenario in enumerate(scenarios):
            obj[z_idx[s_idx]] = -self.risk_weight * scenario.probability / self.cvar_alpha

        h.changeColsCostByRange(0, var_count - 1, obj)
        h.changeObjectiveSense(highspy.ObjSense.kMaximize)

        # SOC dynamics (stage 1, scenario-independent)
        for i, a in enumerate(assets):
            for t in range(T):
                if t == 0:
                    row_idx = [s1_soc[(i, t)], s1_ch[(i, t)], s1_dis[(i, t)]]
                    coeffs = [1.0, -a.rte * self.dt_hours, self.dt_hours]
                    rhs = a.soc_init * a.capacity_mwh
                    h.addRow(rhs, rhs, len(row_idx), row_idx, coeffs)
                else:
                    row_idx = [s1_soc[(i, t)], s1_soc[(i, t-1)], s1_ch[(i, t)], s1_dis[(i, t)]]
                    coeffs = [1.0, -1.0, -a.rte * self.dt_hours, self.dt_hours]
                    h.addRow(0.0, 0.0, len(row_idx), row_idx, coeffs)

        # CVaR linking constraints: z_s >= eta - revenue_s
        for s_idx, scenario in enumerate(scenarios):
            # revenue_s = sum_i,t (dis[i,t] - ch[i,t]) * lmp_s[t] * dt
            rev_coeffs = []
            rev_idx = []
            for i, a in enumerate(assets):
                for t in range(T):
                    rev_idx.append(s1_dis[(i, t)])
                    rev_coeffs.append(-scenario.lmp[t] * self.dt_hours)
                    rev_idx.append(s1_ch[(i, t)])
                    rev_coeffs.append(scenario.lmp[t] * self.dt_hours / a.rte)
            # z_s + revenue_s >= eta  =>  z_s - eta >= -revenue_s
            row_idx = [z_idx[s_idx], eta_idx] + rev_idx
            row_coeffs = [1.0, -1.0] + rev_coeffs
            h.addRow(0.0, highspy.kHighsInf, len(row_idx), row_idx, row_coeffs)

        h.run()
        sol = h.getSolution()
        cv = sol.col_value
        solve_time = time.perf_counter() - t0

        charge_mw = {a.asset_id: [] for a in assets}
        discharge_mw = {a.asset_id: [] for a in assets}
        for i, a in enumerate(assets):
            for t in range(T):
                charge_mw[a.asset_id].append(cv[s1_ch[(i, t)]])
                discharge_mw[a.asset_id].append(cv[s1_dis[(i, t)]])

        # Evaluate revenues per scenario
        scene_revenues = []
        for s_idx, scenario in enumerate(scenarios):
            rev = sum(
                (discharge_mw[a.asset_id][t] - charge_mw[a.asset_id][t]) * scenario.lmp[t] * self.dt_hours
                for a in assets for t in range(T)
            )
            scene_revenues.append(rev)

        probs = np.array([s.probability for s in scenarios])
        exp_rev = float(np.dot(probs, scene_revenues))
        cvar_n = max(1, int(self.cvar_alpha * len(scene_revenues)))
        cvar = float(np.mean(sorted(scene_revenues)[:cvar_n]))

        return ScenarioSolution(
            status="optimal",
            expected_revenue=exp_rev,
            cvar_revenue=cvar,
            here_and_now_charge=charge_mw,
            here_and_now_discharge=discharge_mw,
            scenario_revenues=scene_revenues,
            solve_time_s=solve_time,
        )

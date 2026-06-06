"""
Agent-based simulation for VPP market dynamics.

Models multiple competing VPP operators and price-responsive loads
interacting in a simplified wholesale energy market to simulate
strategic behavior and market equilibria.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class VPPAgent:
    agent_id: str
    strategy: str           # "price_taker", "strategic", "conservative"
    capacity_mw: float
    storage_soc: float = 0.5    # Initial SOC
    cash_usd: float = 0.0
    risk_tolerance: float = 0.5


@dataclass
class MarketClearingResult:
    round_num: int
    clearing_price: float
    total_supply_mw: float
    total_demand_mw: float
    agent_revenues: Dict[str, float]


@dataclass
class SimulationResult:
    n_rounds: int
    price_history: List[float]
    agent_pnl: Dict[str, float]
    market_concentration_hhi: float
    average_clearing_price: float


class ABMMarket:
    """
    Agent-based electricity market model with learning agents.

    Each agent observes prices and updates their bidding strategy.
    Uses simplified Q-learning-style updating (moving average).
    """

    def __init__(
        self,
        agents: List[VPPAgent],
        base_load_mw: float = 500.0,
        load_volatility: float = 0.05,
        seed: int = 42,
    ) -> None:
        self.agents = agents
        self.base_load = base_load_mw
        self.load_vol = load_volatility
        self.rng = np.random.default_rng(seed)
        self._price_history: List[float] = []

    def _generate_demand(self, hour: int) -> float:
        """Generate demand with diurnal pattern and noise."""
        diurnal = 1.0 + 0.3 * np.sin(2 * np.pi * (hour - 6) / 24)
        noise = self.rng.normal(1.0, self.load_vol)
        return self.base_load * diurnal * noise

    def _agent_offer(self, agent: VPPAgent, avg_price: float) -> Tuple[float, float]:
        """Return (offer_mw, offer_price) for one agent."""
        if agent.strategy == "price_taker":
            price = avg_price * (1 + self.rng.normal(0, 0.05))
        elif agent.strategy == "strategic":
            # Mark up above marginal cost based on market share
            share = agent.capacity_mw / max(sum(a.capacity_mw for a in self.agents), 1.0)
            price = avg_price * (1.0 + share * 0.5)
        else:  # conservative
            price = avg_price * 0.95

        offer_mw = agent.capacity_mw * (0.8 + 0.2 * agent.storage_soc)
        return offer_mw, max(price, 5.0)

    def run(self, n_rounds: int = 168) -> SimulationResult:
        """Run agent-based simulation for n_rounds (hours)."""
        agent_pnl: Dict[str, float] = {a.agent_id: 0.0 for a in self.agents}
        avg_price = 40.0
        prices: List[float] = []

        for r in range(n_rounds):
            demand = self._generate_demand(r % 24)
            offers = [(agent, *self._agent_offer(agent, avg_price)) for agent in self.agents]
            offers.sort(key=lambda x: x[2])  # Sort by price

            remaining = demand
            clearing_price = avg_price
            dispatched: Dict[str, float] = {}

            for agent, mw, price in offers:
                if remaining <= 0:
                    break
                cleared = min(mw, remaining)
                dispatched[agent.agent_id] = cleared
                clearing_price = price
                remaining -= cleared

            # Update revenues
            for agent in self.agents:
                rev = dispatched.get(agent.agent_id, 0.0) * clearing_price
                agent_pnl[agent.agent_id] = agent_pnl.get(agent.agent_id, 0.0) + rev
                agent.cash_usd += rev

            prices.append(clearing_price)
            avg_price = 0.9 * avg_price + 0.1 * clearing_price

        # HHI market concentration
        total_rev = max(sum(agent_pnl.values()), 1.0)
        hhi = sum((v / total_rev) ** 2 for v in agent_pnl.values()) * 10000

        return SimulationResult(
            n_rounds=n_rounds,
            price_history=prices,
            agent_pnl=agent_pnl,
            market_concentration_hhi=hhi,
            average_clearing_price=float(np.mean(prices)),
        )

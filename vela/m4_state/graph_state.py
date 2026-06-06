"""Asset topology graph — models electrical connectivity between assets and buses."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator

logger = logging.getLogger(__name__)


class BusType(Enum):
    """Electrical bus types in the VPP network."""
    SLACK = "slack"         # Reference bus (typically grid connection point)
    PV = "pv"               # Voltage-controlled bus (generator)
    PQ = "pq"               # Load bus (known P and Q)
    MICROGRID = "microgrid" # Microgrid bus (can island)


class ConnectionType(Enum):
    """Type of electrical connection."""
    TRANSFORMER = "transformer"
    CABLE = "cable"
    OVERHEAD_LINE = "overhead_line"
    BUSBAR = "busbar"
    SWITCH = "switch"
    BREAKER = "breaker"


@dataclass
class ElectricalBus:
    """A node in the electrical network topology."""
    bus_id: str
    bus_type: BusType
    voltage_kv: float
    latitude: float = 0.0
    longitude: float = 0.0
    zone: str = ""

    # Power flow state
    voltage_pu: float = 1.0
    angle_deg: float = 0.0
    net_injection_mw: float = 0.0
    net_injection_mvar: float = 0.0

    def __hash__(self) -> int:
        return hash(self.bus_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ElectricalBus):
            return self.bus_id == other.bus_id
        return False


@dataclass
class ElectricalBranch:
    """An edge in the electrical network topology (line or transformer)."""
    branch_id: str
    from_bus: str
    to_bus: str
    connection_type: ConnectionType
    # Impedance parameters (per-unit on system base)
    r_pu: float = 0.01      # Resistance
    x_pu: float = 0.10      # Reactance
    b_pu: float = 0.0       # Susceptance (charging)
    thermal_limit_mva: float = 100.0
    tap_ratio: float = 1.0  # Transformer tap (1.0 = nominal)
    is_open: bool = False

    @property
    def z_magnitude_pu(self) -> float:
        return (self.r_pu ** 2 + self.x_pu ** 2) ** 0.5

    @property
    def y_series(self) -> complex:
        """Series admittance."""
        z = complex(self.r_pu, self.x_pu)
        return 1.0 / z if abs(z) > 0 else complex(0, 0)


@dataclass
class AssetNode:
    """Represents an asset attached to an electrical bus in the topology."""
    asset_id: str
    bus_id: str
    asset_type: str
    connection_capacity_mw: float
    is_generation: bool = True  # True = generator/storage, False = load-only


class TopologyGraph:
    """
    Electrical network topology graph for the VPP.

    Represents the physical connections between buses, assets, and the grid.
    Used for:
    - Power flow analysis (simplified DC load flow)
    - Constraint checking (line thermal limits, voltage bounds)
    - Island detection (connectivity analysis)
    - Asset grouping by electrical zone/feeder
    """

    def __init__(self) -> None:
        self._buses: dict[str, ElectricalBus] = {}
        self._branches: dict[str, ElectricalBranch] = {}
        self._assets: dict[str, AssetNode] = {}
        # Adjacency list: bus_id → {branch_id: neighbor_bus_id}
        self._adj: dict[str, dict[str, str]] = {}
        logger.info("TopologyGraph initialized")

    def add_bus(self, bus: ElectricalBus) -> None:
        self._buses[bus.bus_id] = bus
        if bus.bus_id not in self._adj:
            self._adj[bus.bus_id] = {}

    def add_branch(self, branch: ElectricalBranch) -> None:
        self._branches[branch.branch_id] = branch
        # Update adjacency
        if branch.from_bus not in self._adj:
            self._adj[branch.from_bus] = {}
        if branch.to_bus not in self._adj:
            self._adj[branch.to_bus] = {}
        if not branch.is_open:
            self._adj[branch.from_bus][branch.branch_id] = branch.to_bus
            self._adj[branch.to_bus][branch.branch_id] = branch.from_bus

    def add_asset(self, asset: AssetNode) -> None:
        self._assets[asset.asset_id] = asset

    def get_bus(self, bus_id: str) -> ElectricalBus | None:
        return self._buses.get(bus_id)

    def get_assets_at_bus(self, bus_id: str) -> list[AssetNode]:
        return [a for a in self._assets.values() if a.bus_id == bus_id]

    def get_branches_at_bus(self, bus_id: str) -> list[ElectricalBranch]:
        return [
            b for b in self._branches.values()
            if b.from_bus == bus_id or b.to_bus == bus_id
        ]

    def neighbors(self, bus_id: str) -> list[str]:
        """Return bus IDs connected to bus_id via closed branches."""
        return list(self._adj.get(bus_id, {}).values())

    def connected_component(self, start_bus: str) -> set[str]:
        """
        BFS to find all buses reachable from start_bus.

        Used for island detection when a breaker opens.
        """
        visited: set[str] = set()
        queue = [start_bus]
        while queue:
            bus_id = queue.pop(0)
            if bus_id in visited:
                continue
            visited.add(bus_id)
            for neighbor in self.neighbors(bus_id):
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited

    def is_islanded(self, bus_id: str, grid_bus_id: str) -> bool:
        """Check if bus_id can reach the grid connection bus."""
        return grid_bus_id not in self.connected_component(bus_id)

    def dc_load_flow(
        self, injections_mw: dict[str, float]
    ) -> dict[str, float]:
        """
        Simplified DC load flow to estimate branch power flows.

        Uses the B-matrix (susceptance) approximation.
        Returns dict of branch_id → power flow (MW), positive = from→to.

        Assumptions: voltage magnitudes = 1.0 pu, losses neglected.
        """
        bus_ids = list(self._buses.keys())
        n = len(bus_ids)
        if n == 0:
            return {}
        idx = {bid: i for i, bid in enumerate(bus_ids)}

        # Build B-matrix (susceptance matrix)
        B = [[0.0] * n for _ in range(n)]
        for branch in self._branches.values():
            if branch.is_open:
                continue
            fi = idx.get(branch.from_bus, -1)
            ti = idx.get(branch.to_bus, -1)
            if fi < 0 or ti < 0:
                continue
            b = 1.0 / branch.x_pu if abs(branch.x_pu) > 1e-9 else 0.0
            B[fi][fi] += b
            B[ti][ti] += b
            B[fi][ti] -= b
            B[ti][fi] -= b

        # Build injection vector
        P = [injections_mw.get(bid, 0.0) for bid in bus_ids]

        # Solve B * θ = P (using Gauss-Seidel, simplified)
        theta = [0.0] * n
        slack_idx = next(
            (i for i, bid in enumerate(bus_ids) if self._buses[bid].bus_type == BusType.SLACK),
            0,
        )
        for _ in range(100):  # iterations
            for i in range(n):
                if i == slack_idx:
                    theta[i] = 0.0
                    continue
                s = P[i] - sum(B[i][j] * theta[j] for j in range(n) if j != i)
                if abs(B[i][i]) > 1e-9:
                    theta[i] = s / B[i][i]

        # Compute branch flows
        flows: dict[str, float] = {}
        for branch in self._branches.values():
            if branch.is_open:
                flows[branch.branch_id] = 0.0
                continue
            fi = idx.get(branch.from_bus, -1)
            ti = idx.get(branch.to_bus, -1)
            if fi < 0 or ti < 0:
                flows[branch.branch_id] = 0.0
                continue
            b = 1.0 / branch.x_pu if abs(branch.x_pu) > 1e-9 else 0.0
            flows[branch.branch_id] = b * (theta[fi] - theta[ti])
        return flows

    def overloaded_branches(
        self,
        flows_mw: dict[str, float],
        margin_pct: float = 0.0,
    ) -> list[tuple[str, float, float]]:
        """
        Return branches where |flow| > (1+margin/100) * thermal limit.

        Returns list of (branch_id, flow_mw, thermal_limit_mva).
        """
        overloaded = []
        for bid, flow in flows_mw.items():
            branch = self._branches.get(bid)
            if branch and abs(flow) > branch.thermal_limit_mva * (1.0 + margin_pct / 100.0):
                overloaded.append((bid, flow, branch.thermal_limit_mva))
        return overloaded

    def open_switch(self, branch_id: str) -> bool:
        """Open a switch/breaker, updating adjacency."""
        branch = self._branches.get(branch_id)
        if not branch:
            return False
        branch.is_open = True
        # Remove from adjacency
        self._adj.get(branch.from_bus, {}).pop(branch_id, None)
        self._adj.get(branch.to_bus, {}).pop(branch_id, None)
        logger.info("Opened branch %s (%s → %s)", branch_id, branch.from_bus, branch.to_bus)
        return True

    def close_switch(self, branch_id: str) -> bool:
        """Close a switch/breaker, updating adjacency."""
        branch = self._branches.get(branch_id)
        if not branch:
            return False
        branch.is_open = False
        if branch.from_bus not in self._adj:
            self._adj[branch.from_bus] = {}
        if branch.to_bus not in self._adj:
            self._adj[branch.to_bus] = {}
        self._adj[branch.from_bus][branch_id] = branch.to_bus
        self._adj[branch.to_bus][branch_id] = branch.from_bus
        logger.info("Closed branch %s (%s → %s)", branch_id, branch.from_bus, branch.to_bus)
        return True

    def assets_by_zone(self, zone: str) -> list[AssetNode]:
        """Return all assets whose bus is in the specified zone."""
        zone_buses = {bid for bid, bus in self._buses.items() if bus.zone == zone}
        return [a for a in self._assets.values() if a.bus_id in zone_buses]

    @property
    def bus_count(self) -> int:
        return len(self._buses)

    @property
    def branch_count(self) -> int:
        return len(self._branches)

    @property
    def asset_count(self) -> int:
        return len(self._assets)

    def summary(self) -> dict[str, Any]:
        return {
            "buses": self.bus_count,
            "branches": self.branch_count,
            "assets": self.asset_count,
            "open_branches": sum(1 for b in self._branches.values() if b.is_open),
        }

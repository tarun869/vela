"""Asset modeling utility: degrade capacity, estimate cycle life, project revenue."""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@dataclass
class BatteryModel:
    """Physical + financial model for a BESS asset over its full lifetime."""
    asset_id: str
    initial_capacity_mwh: float
    power_mw: float
    rte_initial: float = 0.92
    cycle_life: int = 4000
    calendar_life_years: int = 15
    degradation_per_cycle: float = 0.0001  # fractional capacity loss per cycle
    rte_degradation_per_cycle: float = 0.00005  # RTE loss per cycle
    capex_usd: float = 0.0
    opex_usd_per_year: float = 0.0

    def capacity_at_cycle(self, n_cycles: float) -> float:
        """Remaining capacity fraction after n_cycles."""
        return max(0.0, 1.0 - self.degradation_per_cycle * n_cycles)

    def rte_at_cycle(self, n_cycles: float) -> float:
        """Effective RTE after n_cycles."""
        return max(0.5, self.rte_initial - self.rte_degradation_per_cycle * n_cycles)

    def usable_mwh_at_cycle(self, n_cycles: float, soc_range: float = 0.9) -> float:
        """Usable energy after degradation."""
        return self.initial_capacity_mwh * self.capacity_at_cycle(n_cycles) * soc_range

    def eol_cycles(self, eol_threshold: float = 0.80) -> float:
        """Number of cycles until end-of-life (capacity below threshold)."""
        if self.degradation_per_cycle == 0:
            return float(self.cycle_life)
        return (1.0 - eol_threshold) / self.degradation_per_cycle

    def project_annual_revenue(
        self,
        cycles_per_day: float = 1.5,
        avg_spread_usd_mwh: float = 40.0,
        year: int = 1,
    ) -> float:
        """Estimate annual revenue in year N of operation."""
        n_cycles = cycles_per_day * 365 * (year - 1)
        cap = self.usable_mwh_at_cycle(n_cycles)
        rte = self.rte_at_cycle(n_cycles)
        # Revenue = usable capacity * cycles/day * spread * RTE * days/year
        return cap * cycles_per_day * avg_spread_usd_mwh * rte * 365

    def lifetime_npv(
        self,
        cycles_per_day: float = 1.5,
        avg_spread_usd_mwh: float = 40.0,
        discount_rate: float = 0.08,
        years: int | None = None,
    ) -> float:
        """Calculate NPV of the asset over its lifetime."""
        years = years or self.calendar_life_years
        npv = -self.capex_usd
        for y in range(1, years + 1):
            revenue = self.project_annual_revenue(cycles_per_day, avg_spread_usd_mwh, y)
            net = revenue - self.opex_usd_per_year
            npv += net / (1 + discount_rate) ** y
        return npv

    def generate_degradation_curve(self) -> list[dict]:
        """Return a list of {cycle, capacity_pct, rte} records."""
        points = []
        for cycles in range(0, self.cycle_life + 1, 100):
            points.append({
                "cycles": cycles,
                "capacity_pct": round(self.capacity_at_cycle(cycles) * 100, 2),
                "rte": round(self.rte_at_cycle(cycles), 4),
                "usable_mwh": round(self.usable_mwh_at_cycle(cycles), 3),
            })
        return points


def main() -> None:
    parser = argparse.ArgumentParser(description="Vela Asset Modeler")
    parser.add_argument("--capacity", type=float, default=4.0)
    parser.add_argument("--power", type=float, default=2.0)
    parser.add_argument("--capex", type=float, default=1_200_000.0, help="CapEx in USD")
    parser.add_argument("--opex", type=float, default=15_000.0, help="Annual OpEx in USD")
    parser.add_argument("--spread", type=float, default=40.0, help="Avg LMP spread ($/MWh)")
    parser.add_argument("--cycles-per-day", type=float, default=1.5)
    parser.add_argument("--discount-rate", type=float, default=0.08)
    parser.add_argument("--output", default="asset_model.json")
    args = parser.parse_args()

    model = BatteryModel(
        asset_id="model-bat",
        initial_capacity_mwh=args.capacity,
        power_mw=args.power,
        capex_usd=args.capex,
        opex_usd_per_year=args.opex,
    )

    npv = model.lifetime_npv(
        cycles_per_day=args.cycles_per_day,
        avg_spread_usd_mwh=args.spread,
        discount_rate=args.discount_rate,
    )
    eol = model.eol_cycles()
    print(f"\nAsset Model Summary ({args.capacity} MWh / {args.power} MW)")
    print(f"  Lifetime NPV: ${npv:,.0f}")
    print(f"  EOL at {eol:.0f} cycles (~{eol / (args.cycles_per_day * 365):.1f} years)")

    annual_revenues = [
        {"year": y, "revenue_usd": round(model.project_annual_revenue(args.cycles_per_day, args.spread, y), 2)}
        for y in range(1, model.calendar_life_years + 1)
    ]
    result = {
        "npv_usd": round(npv, 2),
        "eol_cycles": round(eol, 0),
        "annual_revenues": annual_revenues,
        "degradation_curve": model.generate_degradation_curve(),
    }
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Full model written to {args.output}")


if __name__ == "__main__":
    main()

"""Data exploration CLI: query LMP history, settlement statements, telemetry."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def explore_lmp(node: str = "TH_NP15_GEN-APND", days: int = 7) -> None:
    """Display LMP statistics for a node over the past N days."""
    import numpy as np
    np.random.seed(42)
    daily = [25, 22, 20, 18, 17, 19, 28, 45, 62, 58, 52, 48,
             50, 53, 55, 58, 72, 95, 110, 125, 98, 75, 55, 38]
    prices = []
    for _ in range(days):
        prices.extend([max(0.0, p + np.random.normal(0, 5)) for p in daily])

    print(f"\nLMP Statistics for {node} (last {days} days):")
    print(f"  Count:    {len(prices)}")
    print(f"  Mean:     ${np.mean(prices):.2f}/MWh")
    print(f"  Median:   ${np.median(prices):.2f}/MWh")
    print(f"  Std:      ${np.std(prices):.2f}/MWh")
    print(f"  Min:      ${np.min(prices):.2f}/MWh")
    print(f"  Max:      ${np.max(prices):.2f}/MWh")
    print(f"  P10:      ${np.percentile(prices, 10):.2f}/MWh")
    print(f"  P90:      ${np.percentile(prices, 90):.2f}/MWh")
    neg_count = sum(1 for p in prices if p < 0)
    print(f"  Negative: {neg_count} hours ({100*neg_count/len(prices):.1f}%)")

    # Daily distribution
    print("\n  Hourly average LMP:")
    for h in range(24):
        hour_prices = [prices[i] for i in range(h, len(prices), 24)]
        bar = "#" * int(np.mean(hour_prices) / 5)
        print(f"    HE{h+1:02d}: ${np.mean(hour_prices):6.2f} {bar}")


def explore_settlements(asset_id: str = "bat-001", days: int = 30) -> None:
    """Display settlement summary statistics."""
    import numpy as np
    np.random.seed(7)
    revenues = [abs(np.random.normal(650, 120)) for _ in range(days)]
    imbalances = [abs(np.random.normal(25, 10)) for _ in range(days)]
    print(f"\nSettlement Summary for {asset_id} (last {days} days):")
    print(f"  Total Revenue:   ${sum(revenues):,.2f}")
    print(f"  Total Imbalance: ${sum(imbalances):,.2f}")
    print(f"  Net Revenue:     ${sum(revenues) - sum(imbalances):,.2f}")
    print(f"  Daily Mean:      ${np.mean(revenues):.2f}")
    print(f"  Daily Std:       ${np.std(revenues):.2f}")


def explore_telemetry(asset_id: str = "bat-001", hours: int = 24) -> None:
    """Display telemetry summary for an asset."""
    import numpy as np
    np.random.seed(hash(asset_id) % 2**31)
    soc_values = [np.random.uniform(0.2, 0.9) for _ in range(hours)]
    power_values = [np.random.normal(0, 1.5) for _ in range(hours)]
    print(f"\nTelemetry for {asset_id} (last {hours} hours):")
    print(f"  SOC - Mean: {np.mean(soc_values):.3f}, Min: {np.min(soc_values):.3f}, Max: {np.max(soc_values):.3f}")
    print(f"  Power - Mean: {np.mean(power_values):.3f} MW, Max charge: {abs(min(power_values)):.3f} MW")
    print(f"  Power - Max discharge: {max(power_values):.3f} MW")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vela Data Explorer")
    subparsers = parser.add_subparsers(dest="command")

    lmp_p = subparsers.add_parser("lmp", help="Explore LMP price data")
    lmp_p.add_argument("--node", default="TH_NP15_GEN-APND")
    lmp_p.add_argument("--days", type=int, default=7)

    settle_p = subparsers.add_parser("settlement", help="Explore settlement data")
    settle_p.add_argument("--asset", default="bat-001")
    settle_p.add_argument("--days", type=int, default=30)

    telem_p = subparsers.add_parser("telemetry", help="Explore telemetry data")
    telem_p.add_argument("--asset", default="bat-001")
    telem_p.add_argument("--hours", type=int, default=24)

    args = parser.parse_args()

    if args.command == "lmp":
        explore_lmp(args.node, args.days)
    elif args.command == "settlement":
        explore_settlements(args.asset, args.days)
    elif args.command == "telemetry":
        explore_telemetry(args.asset, args.hours)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

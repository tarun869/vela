"""Generate the two bundled ERCOT RT LMP replay fixtures (96 x 15-min rows each).

Deterministic (seeded) so the fixtures are reproducible. Matches the ERCOT public
RT_LMP_HOURLY-style export columns used by ERCOTHistoricalReplay.
Re-run: python -m tests.fixtures.ercot_lmp._make_ercot_fixtures
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path

NODE = "HB_HUBZONE"
OUT_DIR = Path(__file__).parent
HEADER = ["interval_start", "settlement_point", "lmp", "energy", "congestion", "loss"]


def _diurnal_energy(hour: float) -> float:
    """Base energy price with a morning and evening ramp, floor ~$22."""
    shape = 0.5 * (1 + math.sin(math.pi * (hour - 9) / 12))
    return 22.0 + 38.0 * shape


def _spike_day_rows(rng: random.Random) -> list[list[str]]:
    """2023-08-10: hot summer scarcity day, ~$892/MWh peak at 17:00."""
    rows: list[list[str]] = []
    for i in range(96):
        hour = i * 0.25
        energy = _diurnal_energy(hour) + rng.uniform(-3, 3)
        congestion = rng.uniform(-2, 4)
        # Scarcity ramp 16:00 -> peak 17:00 -> decay by 18:30.
        spike = 0.0
        if 16.0 <= hour < 18.5:
            t = (hour - 16.0) / 1.0  # 0 at 16:00, 1 at 17:00
            spike = 850.0 * math.exp(-((t - 1.0) ** 2) / 0.18)
        energy += spike
        loss = round(0.015 * energy + rng.uniform(-0.3, 0.3), 2)
        lmp = round(energy + congestion + loss, 2)
        ts = f"2023-08-10T{i // 4:02d}:{(i % 4) * 15:02d}:00-05:00"
        rows.append([ts, NODE, f"{lmp:.2f}", f"{energy:.2f}", f"{congestion:.2f}", f"{loss:.2f}"])
    return rows


def _negative_and_spike_rows(rng: random.Random) -> list[list[str]]:
    """2024-02-15: midday negative prices (solar glut) + afternoon spike ~$650."""
    rows: list[list[str]] = []
    for i in range(96):
        hour = i * 0.25
        energy = _diurnal_energy(hour) + rng.uniform(-3, 3)
        congestion = rng.uniform(-2, 3)
        # Midday solar glut drives negative prices 11:00-14:00.
        if 11.0 <= hour < 14.0:
            energy = -18.0 + rng.uniform(-4, 4)
        # Evening ramp scarcity spike 17:30 -> peak 18:30 -> decay.
        if 17.5 <= hour < 19.5:
            t = (hour - 17.5) / 1.0
            energy += 620.0 * math.exp(-((t - 1.0) ** 2) / 0.16)
        loss = round(0.015 * abs(energy) + rng.uniform(-0.3, 0.3), 2)
        lmp = round(energy + congestion + loss, 2)
        ts = f"2024-02-15T{i // 4:02d}:{(i % 4) * 15:02d}:00-06:00"
        rows.append([ts, NODE, f"{lmp:.2f}", f"{energy:.2f}", f"{congestion:.2f}", f"{loss:.2f}"])
    return rows


def _write(filename: str, rows: list[list[str]]) -> None:
    path = OUT_DIR / filename
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)
    peak = max(float(r[2]) for r in rows)
    print(f"wrote {path} ({len(rows)} rows, peak lmp ${peak:.2f})")


def main() -> None:
    _write("ercot_2023_08_10_HB_HUBZONE.csv", _spike_day_rows(random.Random(810)))
    _write("ercot_2024_02_15_HB_HUBZONE.csv", _negative_and_spike_rows(random.Random(215)))


if __name__ == "__main__":
    main()

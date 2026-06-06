"""Asset management CLI commands."""
from __future__ import annotations

import json
import os


def cmd_list_assets() -> None:
    from tools.api_client import VelaClient
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        assets = client.list_assets()
        if not assets:
            print("No assets registered.")
            return
        print(f"{'ID':<20} {'Type':<12} {'Capacity':>10} {'Power':>8} {'Status':<10} {'SOC':>6}")
        print("-" * 75)
        for a in assets:
            cap = f"{a.get('capacity_mwh', '-'):.1f}" if a.get("capacity_mwh") else "-"
            soc = f"{a.get('soc', 0):.3f}" if a.get("soc") is not None else "-"
            print(f"{a['asset_id']:<20} {a['asset_type']:<12} {cap:>10} {a['power_mw']:>8.2f} {a['status']:<10} {soc:>6}")


def cmd_get_asset(asset_id: str) -> None:
    from tools.api_client import VelaClient, VelaAPIError
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        try:
            asset = client.get_asset(asset_id)
            print(json.dumps(asset, indent=2, default=str))
        except VelaAPIError as e:
            print(f"Error: {e}")

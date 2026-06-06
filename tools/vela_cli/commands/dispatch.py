"""Dispatch CLI commands."""
from __future__ import annotations

import json
import os


def cmd_run_dispatch(asset_ids: list[str], horizon: int = 24, market: str = "CAISO") -> None:
    """Run dispatch optimization via the API."""
    from tools.api_client import VelaClient, VelaAPIError
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        try:
            plan = client.run_dispatch(asset_ids=asset_ids, horizon_hours=horizon, market=market)
            print(json.dumps(plan, indent=2, default=str))
        except VelaAPIError as e:
            print(f"Error: {e}")


def cmd_get_plan(plan_id: str) -> None:
    """Retrieve a dispatch plan by ID."""
    from tools.api_client import VelaClient, VelaAPIError
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        try:
            plan = client.get_plan(plan_id)
            print(json.dumps(plan, indent=2, default=str))
        except VelaAPIError as e:
            print(f"Error: {e}")


def cmd_approve_plan(plan_id: str, comment: str = "") -> None:
    """Approve a dispatch plan."""
    from tools.api_client import VelaClient, VelaAPIError
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    with VelaClient(base_url=base_url) as client:
        try:
            result = client.approve_plan(plan_id, comment=comment)
            print(f"Plan {plan_id} status: {result['status']}")
        except VelaAPIError as e:
            print(f"Error: {e}")

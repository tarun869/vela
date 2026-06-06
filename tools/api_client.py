"""Python client for the Vela REST API."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


class VelaAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class VelaClient:
    """
    Synchronous Python client for the Vela VPP REST API.

    Usage:
        client = VelaClient(base_url="http://localhost:8000", api_key="vela_...")
        assets = client.list_assets()
        plan = client.run_dispatch(asset_ids=["bat-001"], horizon_hours=24)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        jwt_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-Api-Key"] = api_key
        elif jwt_token:
            self._headers["Authorization"] = f"Bearer {jwt_token}"
        self._client = httpx.Client(headers=self._headers, timeout=timeout) if _HAS_HTTPX else None

    def _get(self, path: str, params: dict | None = None) -> Any:
        if not self._client:
            raise RuntimeError("httpx not installed: pip install httpx")
        resp = self._client.get(f"{self.base_url}{path}", params=params)
        if resp.is_error:
            raise VelaAPIError(resp.status_code, resp.text)
        return resp.json()

    def _post(self, path: str, json: dict) -> Any:
        if not self._client:
            raise RuntimeError("httpx not installed: pip install httpx")
        resp = self._client.post(f"{self.base_url}{path}", json=json)
        if resp.is_error:
            raise VelaAPIError(resp.status_code, resp.text)
        return resp.json()

    # --- Assets ---
    def list_assets(self) -> list[dict]:
        return self._get("/v1/assets/")

    def get_asset(self, asset_id: str) -> dict:
        return self._get(f"/v1/assets/{asset_id}")

    # --- Dispatch ---
    def run_dispatch(
        self,
        asset_ids: list[str],
        horizon_hours: int = 24,
        market: str = "CAISO",
        objective: str = "revenue",
    ) -> dict:
        return self._post("/v1/dispatch/run", {
            "asset_ids": asset_ids,
            "horizon_hours": horizon_hours,
            "market": market,
            "objective": objective,
        })

    def get_plan(self, plan_id: str) -> dict:
        return self._get(f"/v1/dispatch/plans/{plan_id}")

    def approve_plan(self, plan_id: str, comment: str = "") -> dict:
        return self._post(f"/v1/dispatch/plans/{plan_id}/approval", {"action": "approve", "comment": comment})

    # --- Forecasts ---
    def forecast_price(self, node: str, horizon_hours: int = 24, model: str = "ar") -> dict:
        return self._post("/v1/forecasts/price", {"node": node, "horizon_hours": horizon_hours, "model": model})

    def get_market_prices(self, node: str = "TH_NP15_GEN-APND", hours: int = 24) -> list[dict]:
        return self._get("/v1/market/prices", params={"node": node, "hours": hours})

    # --- Settlements ---
    def reconcile(
        self,
        asset_id: str,
        market: str,
        settlement_date: str,
        scheduled_mwh: list[float],
        metered_mwh: list[float],
        lmp: list[float],
    ) -> dict:
        return self._post("/v1/settlements/reconcile", {
            "asset_id": asset_id,
            "market": market,
            "settlement_date": settlement_date,
            "scheduled_mwh": scheduled_mwh,
            "metered_mwh": metered_mwh,
            "lmp": lmp,
        })

    # --- Health ---
    def health(self) -> dict:
        return self._get("/health")

    def close(self) -> None:
        if self._client:
            self._client.close()

    def __enter__(self) -> "VelaClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


if __name__ == "__main__":
    import json
    base_url = os.getenv("VELA_API_URL", "http://localhost:8000")
    api_key = os.getenv("VELA_API_KEY", "")
    client = VelaClient(base_url=base_url, api_key=api_key)
    try:
        assets = client.list_assets()
        print(f"Assets ({len(assets)}): {json.dumps(assets, indent=2, default=str)}")
    except VelaAPIError as e:
        print(f"API error: {e}")
    except RuntimeError as e:
        print(f"Client error: {e}")

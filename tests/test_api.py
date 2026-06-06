"""API endpoint tests using FastAPI TestClient."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from vela.api.app import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


class TestAssetsEndpoints:
    def test_list_assets_returns_200(self, client):
        response = client.get("/v1/assets/")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_nonexistent_asset_returns_404(self, client):
        response = client.get("/v1/assets/nonexistent-id")
        assert response.status_code == 404

    def test_create_asset_returns_201(self, client):
        payload = {
            "asset_id": "bat-test-001",
            "asset_type": "battery",
            "capacity_mwh": 4.0,
            "power_mw": 2.0,
            "status": "online",
            "soc": 0.5,
        }
        response = client.post("/v1/assets/", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["asset_id"] == "bat-test-001"


class TestDispatchEndpoints:
    def test_run_dispatch_returns_202(self, client):
        payload = {
            "asset_ids": ["bat-001"],
            "horizon_hours": 4,
            "market": "CAISO",
        }
        response = client.post("/v1/dispatch/run", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert "plan_id" in data
        assert data["status"] in ("pending", "running", "complete", "failed")

    def test_list_plans_returns_200(self, client):
        response = client.get("/v1/dispatch/plans")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_nonexistent_plan_returns_404(self, client):
        response = client.get("/v1/dispatch/plans/does-not-exist")
        assert response.status_code == 404


class TestForecastEndpoints:
    def test_forecast_price_returns_200(self, client):
        payload = {"node": "TH_NP15_GEN-APND", "horizon_hours": 6, "model": "ar"}
        response = client.post("/v1/forecasts/price", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "points" in data
        assert len(data["points"]) == 6

    def test_forecast_points_have_required_fields(self, client):
        payload = {"node": "TH_NP15_GEN-APND", "horizon_hours": 4}
        response = client.post("/v1/forecasts/price", json=payload)
        assert response.status_code == 200
        for point in response.json()["points"]:
            assert "timestamp" in point
            assert "mean" in point
            assert "p10" in point
            assert "p90" in point

    def test_forecast_p90_gte_p10(self, client):
        payload = {"node": "TH_NP15_GEN-APND", "horizon_hours": 12}
        response = client.post("/v1/forecasts/price", json=payload)
        assert response.status_code == 200
        for point in response.json()["points"]:
            assert point["p90"] >= point["p10"]

    def test_get_latest_price_forecast_returns_200(self, client):
        response = client.get("/v1/forecasts/price/TH_NP15_GEN-APND?horizon_hours=6")
        assert response.status_code == 200


class TestMarketEndpoints:
    def test_get_market_prices_returns_200(self, client):
        response = client.get("/v1/market/prices?node=TH_NP15_GEN-APND&hours=6")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) == 6

    def test_create_bid_returns_201(self, client):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        payload = {
            "asset_id": "bat-001",
            "market": "CAISO",
            "service": "energy",
            "quantity_mw": 2.0,
            "price_usd_mwh": 55.0,
            "interval_start": now.isoformat(),
            "interval_end": (now + timedelta(hours=1)).isoformat(),
        }
        response = client.post("/v1/market/bids", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "draft"

    def test_list_bids_returns_200(self, client):
        response = client.get("/v1/market/bids")
        assert response.status_code == 200

    def test_submit_nonexistent_bid_returns_404(self, client):
        response = client.post("/v1/market/bids/does-not-exist/submit")
        assert response.status_code == 404


class TestSettlementEndpoints:
    def test_reconcile_returns_201(self, client):
        from datetime import datetime, timezone
        payload = {
            "asset_id": "bat-001",
            "market": "CAISO",
            "settlement_date": datetime(2024, 7, 15, tzinfo=timezone.utc).isoformat(),
            "scheduled_mwh": [1.5] * 24,
            "metered_mwh": [1.5] * 24,
            "lmp": [55.0] * 24,
        }
        response = client.post("/v1/settlements/reconcile", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "statement_id" in data
        assert data["total_energy_mwh"] == pytest.approx(36.0, abs=0.01)

    def test_list_statements_returns_200(self, client):
        response = client.get("/v1/settlements/statements")
        assert response.status_code == 200

    def test_get_nonexistent_statement_returns_404(self, client):
        response = client.get("/v1/settlements/statements/does-not-exist")
        assert response.status_code == 404

"""Ingestion pipeline tests: LMP parsing, telemetry normalization, ETL transforms."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from vela.data.etl import (
    caiso_lmp_transform,
    ercot_spp_transform,
    telemetry_transform,
    settlement_transform,
    ETLJob,
    run_job,
)


class TestCaisoTransform:
    def test_parses_oasis_row(self):
        raw = {
            "INTERVALSTARTTIME_GMT": "2024-07-15T00:00:00Z",
            "NODE": "TH_NP15_GEN-APND",
            "MW": 58.42,
            "ENERGY_MW": 50.12,
            "CONGESTION_MW": 5.88,
            "LOSS_MW": 2.42,
        }
        result = caiso_lmp_transform(raw)
        assert result["node"] == "TH_NP15_GEN-APND"
        assert result["lmp"] == pytest.approx(58.42)
        assert result["market"] == "CAISO"

    def test_falls_back_to_lowercase_keys(self):
        raw = {"timestamp": "2024-07-15T00:00:00Z", "node": "HB_NORTH", "lmp": 45.0, "energy": 40.0, "congestion": 3.0, "loss": 2.0}
        result = caiso_lmp_transform(raw)
        assert result["lmp"] == pytest.approx(45.0)

    def test_zero_values_are_valid(self):
        raw = {"node": "TH_NP15_GEN-APND", "MW": 0.0, "ENERGY_MW": 0.0, "CONGESTION_MW": 0.0, "LOSS_MW": 0.0}
        result = caiso_lmp_transform(raw)
        assert result["lmp"] == 0.0


class TestErcotTransform:
    def test_parses_ercot_row(self):
        raw = {
            "SettlementPoint": "HB_NORTH",
            "DeliveryDate": "2024-07-15",
            "SettlementPointPrice": 72.35,
        }
        result = ercot_spp_transform(raw)
        assert result["node"] == "HB_NORTH"
        assert result["lmp"] == pytest.approx(72.35)
        assert result["market"] == "ERCOT"

    def test_congestion_and_loss_default_to_zero(self):
        raw = {"SettlementPoint": "HB_NORTH", "SettlementPointPrice": 50.0}
        result = ercot_spp_transform(raw)
        assert result["congestion"] == 0.0
        assert result["loss"] == 0.0


class TestTelemetryTransform:
    def test_clamps_soc_above_one(self):
        raw = {"asset_id": "bat-001", "timestamp": "2024-07-15T00:00:00Z", "soc": 1.5, "power_mw": 0.0}
        result = telemetry_transform(raw)
        assert result["soc"] <= 1.0

    def test_clamps_soc_below_zero(self):
        raw = {"asset_id": "bat-001", "timestamp": "2024-07-15T00:00:00Z", "soc": -0.1, "power_mw": 0.0}
        result = telemetry_transform(raw)
        assert result["soc"] >= 0.0

    def test_valid_soc_passthrough(self):
        raw = {"asset_id": "bat-001", "timestamp": "2024-07-15T00:00:00Z", "soc": 0.65, "power_mw": 1.5}
        result = telemetry_transform(raw)
        assert result["soc"] == pytest.approx(0.65)
        assert result["power_mw"] == pytest.approx(1.5)

    def test_missing_soc_gives_none(self):
        raw = {"asset_id": "bat-001", "timestamp": "2024-07-15T00:00:00Z", "power_mw": 0.0}
        result = telemetry_transform(raw)
        assert result["soc"] is None

    def test_status_defaults_to_unknown(self):
        raw = {"asset_id": "bat-001", "timestamp": "2024-07-15T00:00:00Z"}
        result = telemetry_transform(raw)
        assert result["status"] == "unknown"


class TestSettlementTransform:
    def test_normalizes_fields(self):
        raw = {
            "asset_id": "bat-001",
            "market": "CAISO",
            "interval_start": "2024-07-15T00:00:00Z",
            "scheduled_mwh": 1.5,
            "metered_mwh": 1.48,
            "lmp": 58.0,
        }
        result = settlement_transform(raw)
        assert result["scheduled_mwh"] == pytest.approx(1.5)
        assert result["metered_mwh"] == pytest.approx(1.48)
        assert result["lmp"] == pytest.approx(58.0)


class TestETLJob:
    def test_etl_job_counts_records(self):
        job = ETLJob(job_id="j1", name="test", source="raw", destination="db")
        records = [{"lmp": float(i)} for i in range(50)]
        result = run_job(job, records)
        assert result.records_read == 50
        assert result.records_written == 50
        assert result.records_failed == 0

    def test_etl_job_applies_transform(self):
        records = [{"NODE": "TH_NP15_GEN-APND", "MW": float(i)} for i in range(10)]
        job = ETLJob(
            job_id="j2",
            name="caiso",
            source="oasis",
            destination="db",
            transform_fn=caiso_lmp_transform,
        )
        result = run_job(job, records)
        assert result.records_written == 10

    def test_etl_dry_run_does_not_write(self):
        records = [{"lmp": 50.0}] * 20
        job = ETLJob(job_id="j3", name="dry", source="s", destination="d", dry_run=True)
        result = run_job(job, records)
        assert result.records_written == 0

    def test_transform_exception_counts_as_failure(self):
        def bad_transform(r):
            raise ValueError("intentional error")

        records = [{"x": i} for i in range(5)]
        job = ETLJob(job_id="j4", name="bad", source="s", destination="d", transform_fn=bad_transform)
        result = run_job(job, records)
        assert result.records_failed == 5

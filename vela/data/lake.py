"""Data lake interface: S3 read/write for time-series data and parquet files."""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_S3_BUCKET = os.getenv("DATA_LAKE_BUCKET", "vela-data")
_S3_PREFIX = os.getenv("DATA_LAKE_PREFIX", "")


class DataLake:
    """
    S3-backed data lake client.
    Falls back to local filesystem if S3 is unavailable (dev mode).
    """

    def __init__(self, bucket: str = _S3_BUCKET, prefix: str = _S3_PREFIX) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client("s3")
            except ImportError:
                logger.warning("boto3 not installed; DataLake will operate in local-only mode")
        return self._client

    def _key(self, path: str) -> str:
        if self.prefix:
            return f"{self.prefix.rstrip('/')}/{path.lstrip('/')}"
        return path.lstrip("/")

    def write_json(self, path: str, data: Any) -> str:
        """Write a JSON-serializable object to S3."""
        key = self._key(path)
        body = json.dumps(data, default=str).encode()
        client = self._get_client()
        if client:
            client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType="application/json")
            uri = f"s3://{self.bucket}/{key}"
        else:
            # Local fallback
            import pathlib
            local_path = pathlib.Path(f"/tmp/vela_lake/{key}")
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(body)
            uri = str(local_path)
        logger.debug("DataLake write: %s", uri)
        return uri

    def read_json(self, path: str) -> Any:
        """Read a JSON object from S3."""
        key = self._key(path)
        client = self._get_client()
        if client:
            response = client.get_object(Bucket=self.bucket, Key=key)
            return json.loads(response["Body"].read())
        else:
            import pathlib
            local_path = pathlib.Path(f"/tmp/vela_lake/{key}")
            return json.loads(local_path.read_text())

    def write_parquet(self, path: str, records: list[dict]) -> str:
        """Write a list of dicts as a Parquet file to S3."""
        try:
            import pandas as pd
            df = pd.DataFrame(records)
            buf = io.BytesIO()
            df.to_parquet(buf, index=False, engine="pyarrow")
            buf.seek(0)
            key = self._key(path)
            client = self._get_client()
            if client:
                client.put_object(Bucket=self.bucket, Key=key, Body=buf.read())
                uri = f"s3://{self.bucket}/{key}"
            else:
                import pathlib
                local_path = pathlib.Path(f"/tmp/vela_lake/{key}")
                local_path.parent.mkdir(parents=True, exist_ok=True)
                buf.seek(0)
                local_path.write_bytes(buf.read())
                uri = str(local_path)
            logger.debug("DataLake parquet write: %s rows -> %s", len(records), uri)
            return uri
        except ImportError:
            # Fall back to JSON if pandas/pyarrow not available
            return self.write_json(path.replace(".parquet", ".json"), records)

    def list_objects(self, prefix: str, max_keys: int = 1000) -> list[str]:
        """List object keys under a prefix."""
        full_prefix = self._key(prefix)
        client = self._get_client()
        if client:
            response = client.list_objects_v2(Bucket=self.bucket, Prefix=full_prefix, MaxKeys=max_keys)
            return [obj["Key"] for obj in response.get("Contents", [])]
        return []

    def lmp_path(self, market: str, node: str, dt: datetime, granularity: str = "hourly") -> str:
        """Construct the canonical S3 path for an LMP dataset partition."""
        date_str = dt.strftime("%Y/%m/%d")
        return f"market_prices/{market.lower()}/lmp/{granularity}/{date_str}/{node}.parquet"

    def telemetry_path(self, asset_id: str, dt: datetime) -> str:
        """Construct the canonical S3 path for telemetry data."""
        date_str = dt.strftime("%Y/%m/%d")
        return f"telemetry/{asset_id}/{date_str}/data.parquet"


lake = DataLake()

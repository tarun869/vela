"""YAML configuration loader and manager for the Vela VPP engine."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    url: str = "postgresql+asyncpg://vela:vela@localhost:5432/vela"
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False


@dataclass
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""


@dataclass
class MarketConfig:
    enabled_markets: list[str] = field(default_factory=lambda: ["CAISO", "ERCOT"])
    caiso_node: str = "TH_NP15_GEN-APND"
    ercot_node: str = "HB_NORTH"
    bid_lead_time_hours: int = 1
    min_bid_mw: float = 0.1
    max_bid_fraction: float = 0.90   # Max fraction of rated capacity to bid


@dataclass
class OptimizerConfig:
    horizon_hours: int = 24
    interval_minutes: int = 60
    solver: str = "highs"
    solve_time_limit_seconds: float = 30.0
    mip_gap: float = 0.005
    risk_aversion: float = 0.0      # 0.0 = risk-neutral, 1.0 = risk-averse
    reserve_margin_pct: float = 5.0


@dataclass
class ForecastConfig:
    model: str = "ensemble"         # "xgb", "lstm", "ensemble"
    retrain_interval_hours: int = 24
    feature_lag_hours: int = 168    # 1 week of historical features
    price_spike_threshold_usd: float = 150.0


@dataclass
class ControlConfig:
    dispatch_interval_seconds: int = 300   # How often to run dispatch
    telemetry_interval_seconds: int = 30   # How often to poll telemetry
    health_check_interval_seconds: int = 60
    max_ramp_rate_pct_per_min: float = 20.0  # % of rated power per minute
    deadband_hz: float = 0.03               # Frequency deadband for response


@dataclass
class VelaConfig:
    """Top-level Vela configuration."""
    environment: str = "development"       # "development", "staging", "production"
    log_level: str = "INFO"
    site_id: str = "default"
    operator_id: str = ""
    timezone: str = "America/Los_Angeles"

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    forecast: ForecastConfig = field(default_factory=ForecastConfig)
    control: ControlConfig = field(default_factory=ControlConfig)

    # Raw extra config for extension
    extra: dict[str, Any] = field(default_factory=dict)


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base, modifying base in place."""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _merge_dicts(base[key], val)
        else:
            base[key] = val
    return base


def _apply_env_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Apply environment variable overrides.

    Variables follow the pattern: VELA_SECTION_KEY=value
    e.g., VELA_OPTIMIZER_HORIZON_HOURS=48
    """
    for env_key, env_val in os.environ.items():
        if not env_key.startswith("VELA_"):
            continue
        parts = env_key[5:].lower().split("_", 1)
        if len(parts) == 1:
            config_dict[parts[0]] = env_val
        else:
            section, key = parts[0], parts[1]
            if section in config_dict and isinstance(config_dict[section], dict):
                # Try to cast to int/float/bool
                config_dict[section][key] = _cast_env_value(env_val)
    return config_dict


def _cast_env_value(value: str) -> Any:
    """Attempt to cast an environment variable string to a Python type."""
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _dict_to_config(d: dict[str, Any]) -> VelaConfig:
    """Construct a VelaConfig from a nested dict."""
    cfg = VelaConfig(
        environment=d.get("environment", "development"),
        log_level=d.get("log_level", "INFO"),
        site_id=d.get("site_id", "default"),
        operator_id=d.get("operator_id", ""),
        timezone=d.get("timezone", "America/Los_Angeles"),
        extra=d.get("extra", {}),
    )
    if "database" in d:
        db = d["database"]
        cfg.database = DatabaseConfig(
            url=db.get("url", cfg.database.url),
            pool_size=int(db.get("pool_size", cfg.database.pool_size)),
            max_overflow=int(db.get("max_overflow", cfg.database.max_overflow)),
            echo=bool(db.get("echo", cfg.database.echo)),
        )
    if "redis" in d:
        r = d["redis"]
        cfg.redis = RedisConfig(
            host=r.get("host", cfg.redis.host),
            port=int(r.get("port", cfg.redis.port)),
            db=int(r.get("db", cfg.redis.db)),
            password=r.get("password", cfg.redis.password),
        )
    if "market" in d:
        m = d["market"]
        cfg.market = MarketConfig(
            enabled_markets=m.get("enabled_markets", cfg.market.enabled_markets),
            caiso_node=m.get("caiso_node", cfg.market.caiso_node),
            ercot_node=m.get("ercot_node", cfg.market.ercot_node),
            bid_lead_time_hours=int(m.get("bid_lead_time_hours", cfg.market.bid_lead_time_hours)),
            min_bid_mw=float(m.get("min_bid_mw", cfg.market.min_bid_mw)),
            max_bid_fraction=float(m.get("max_bid_fraction", cfg.market.max_bid_fraction)),
        )
    if "optimizer" in d:
        o = d["optimizer"]
        cfg.optimizer = OptimizerConfig(
            horizon_hours=int(o.get("horizon_hours", cfg.optimizer.horizon_hours)),
            interval_minutes=int(o.get("interval_minutes", cfg.optimizer.interval_minutes)),
            solver=o.get("solver", cfg.optimizer.solver),
            solve_time_limit_seconds=float(
                o.get("solve_time_limit_seconds", cfg.optimizer.solve_time_limit_seconds)
            ),
            mip_gap=float(o.get("mip_gap", cfg.optimizer.mip_gap)),
            risk_aversion=float(o.get("risk_aversion", cfg.optimizer.risk_aversion)),
            reserve_margin_pct=float(
                o.get("reserve_margin_pct", cfg.optimizer.reserve_margin_pct)
            ),
        )
    if "forecast" in d:
        f = d["forecast"]
        cfg.forecast = ForecastConfig(
            model=f.get("model", cfg.forecast.model),
            retrain_interval_hours=int(
                f.get("retrain_interval_hours", cfg.forecast.retrain_interval_hours)
            ),
            feature_lag_hours=int(f.get("feature_lag_hours", cfg.forecast.feature_lag_hours)),
            price_spike_threshold_usd=float(
                f.get("price_spike_threshold_usd", cfg.forecast.price_spike_threshold_usd)
            ),
        )
    if "control" in d:
        c = d["control"]
        cfg.control = ControlConfig(
            dispatch_interval_seconds=int(
                c.get("dispatch_interval_seconds", cfg.control.dispatch_interval_seconds)
            ),
            telemetry_interval_seconds=int(
                c.get("telemetry_interval_seconds", cfg.control.telemetry_interval_seconds)
            ),
            health_check_interval_seconds=int(
                c.get("health_check_interval_seconds", cfg.control.health_check_interval_seconds)
            ),
            max_ramp_rate_pct_per_min=float(
                c.get("max_ramp_rate_pct_per_min", cfg.control.max_ramp_rate_pct_per_min)
            ),
            deadband_hz=float(c.get("deadband_hz", cfg.control.deadband_hz)),
        )
    return cfg


class ConfigManager:
    """
    Loads and manages Vela configuration from YAML files.

    Supports layered config:
    1. Base defaults (hardcoded)
    2. config.yaml (committed defaults)
    3. config.local.yaml (developer overrides, gitignored)
    4. Environment variables (VELA_SECTION_KEY=value)

    Each layer overrides the previous one.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._config_path = Path(config_path) if config_path else None
        self._config: VelaConfig | None = None

    def load(self) -> VelaConfig:
        """Load and return the merged configuration."""
        raw: dict[str, Any] = {}

        # Load base config file
        if self._config_path and self._config_path.exists():
            with open(self._config_path) as f:
                base = yaml.safe_load(f) or {}
            raw = _merge_dicts(raw, base)
            logger.info("Loaded config from %s", self._config_path)

        # Load local override file
        if self._config_path:
            local_path = self._config_path.parent / (
                self._config_path.stem + ".local" + self._config_path.suffix
            )
            if local_path.exists():
                with open(local_path) as f:
                    local = yaml.safe_load(f) or {}
                raw = _merge_dicts(raw, local)
                logger.info("Loaded local config overrides from %s", local_path)

        # Apply environment variable overrides
        raw = _apply_env_overrides(raw)

        self._config = _dict_to_config(raw)
        return self._config

    @property
    def config(self) -> VelaConfig:
        if self._config is None:
            return self.load()
        return self._config

    def reload(self) -> VelaConfig:
        """Reload configuration from disk."""
        self._config = None
        return self.load()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VelaConfig:
        """Create a VelaConfig directly from a dictionary (for testing)."""
        return _dict_to_config(d)

    @classmethod
    def default(cls) -> VelaConfig:
        """Return default VelaConfig with no file loading."""
        return VelaConfig()

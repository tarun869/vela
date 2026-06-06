"""Prometheus metrics for the Vela VPP Dispatch Optimization Engine."""
from prometheus_client import Counter, Gauge, Histogram, Summary

dispatch_cycles_total = Counter(
    "vela_dispatch_cycles_total",
    "Number of dispatch optimization cycles completed",
    ["status", "market"],
)

optimizer_solve_seconds = Histogram(
    "vela_optimizer_solve_seconds",
    "Time taken to solve the dispatch MILP",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

asset_soc_gauge = Gauge(
    "vela_asset_soc_ratio",
    "Current state of charge as a ratio 0-1",
    ["asset_id", "asset_type"],
)

market_bid_revenue_dollars = Counter(
    "vela_market_bid_revenue_dollars_total",
    "Cumulative revenue from market bids",
    ["market", "service"],
)

settlement_discrepancy_mwh = Histogram(
    "vela_settlement_discrepancy_mwh",
    "Difference between scheduled and metered energy in MWh",
    buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

forecast_mae_mw = Gauge(
    "vela_forecast_mae_mw",
    "Mean absolute error of the latest forecast in MW",
    ["model", "horizon_hours"],
)

active_assets_gauge = Gauge(
    "vela_active_assets_total",
    "Number of assets currently online",
    ["asset_type"],
)

telemetry_ingest_rate = Counter(
    "vela_telemetry_ingest_total",
    "Number of telemetry data points ingested",
    ["asset_type", "protocol"],
)

protocol_errors_total = Counter(
    "vela_protocol_errors_total",
    "Number of protocol communication errors",
    ["protocol", "error_type"],
)

optimization_objective_dollars = Gauge(
    "vela_optimization_objective_dollars",
    "Latest optimization objective value in dollars",
    ["market"],
)

grid_frequency_hz = Gauge(
    "vela_grid_frequency_hz",
    "Current grid frequency in Hz",
    ["region"],
)

imbalance_penalty_dollars = Counter(
    "vela_imbalance_penalty_dollars_total",
    "Cumulative imbalance penalty charges",
    ["market"],
)

regulation_performance_score = Gauge(
    "vela_regulation_performance_score",
    "Regulation performance score (0-1) for the last evaluation period",
    ["asset_id"],
)

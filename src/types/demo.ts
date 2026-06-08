// TypeScript types for Vela demo backend modules (m39–m42).
// Field names match Python snake_case exactly.

// ── m39_extraction ────────────────────────────────────────────────────────────

export type DemoAssetType = 'BESS' | 'Solar' | 'Wind' | 'EV_Fleet' | 'Flex_Load'
export type Chemistry = 'LFP' | 'NMC' | 'NCA'
export type ObligationType =
  | 'capacity'
  | 'dr_event'
  | 'offtake'
  | 'reliability_reserve'
  | 'demand_charge'

export type DeliveryWindow = {
  days: string[]
  start_hour: number
  end_hour: number
}

export type ExtractedAsset = {
  asset_id: string
  asset_type: DemoAssetType
  rated_mw: number
  rated_mwh: number | null
  iso_node: string | null
  qse_name: string | null
  chemistry: Chemistry | null
  warranty_cycles: number | null
  warranty_years: number | null
  capacity_guarantee_pct: number | null
  commissioned_date: string | null
  confidence: number
  source_text: string | null
}

export type ExtractedObligation = {
  obligation_type: ObligationType
  committed_mw: number
  delivery_windows: DeliveryWindow[]
  penalty_linear_per_mwh: number | null
  penalty_escalation_threshold_mwh: number | null
  penalty_escalation_multiplier: number | null
  contract_start: string | null
  contract_end: string | null
  confidence: number
  ambiguous_language: string | null
  source_text: string | null
}

export type ExtractionResult = {
  assets: ExtractedAsset[]
  obligations: ExtractedObligation[]
  low_confidence_fields: Record<string, unknown>[]
  extraction_warnings: string[]
  raw_claude_reasoning: string | null
}

export type ExtractionReview = {
  result: ExtractionResult
  requires_human_review: boolean
  review_items: Record<string, unknown>[]
}

// ── m40_telemetry ─────────────────────────────────────────────────────────────

export type ConnectionStatus = 'connected' | 'simulated' | 'error'
export type IntervalType = 'real_time' | 'day_ahead' | 'historical_replay'

export type AssetTelemetry = {
  asset_id: string
  asset_type: DemoAssetType
  timestamp: string
  soc_pct: number
  power_mw: number
  temperature_c: number
  voltage_v: number
  soh_pct: number
  alarm: string | null
  connection_status: ConnectionStatus
}

export type PriceTick = {
  timestamp: string
  node: string
  lmp_per_mwh: number
  energy_component: number
  congestion_component: number
  loss_component: number
  interval_type: IntervalType
}

export type DemoAssetIn = {
  asset_id: string
  asset_type: DemoAssetType
  rated_mw: number
  rated_mwh: number | null
  chemistry: Chemistry | null
}

// ── m41_optimizer ─────────────────────────────────────────────────────────────

export type BindingConstraint =
  | 'CAPACITY_OBLIGATION'
  | 'THERMAL_LIMIT'
  | 'SOC_FLOOR'
  | 'DEGRADATION_COST'

export type ObligationState = 'COVERED' | 'AT_RISK' | 'BREACHED'

export type DispatchDecision = {
  asset_id: string
  recommended_mw: number
  reasoning: string
  binding_constraint: BindingConstraint | null
  constraint_cost_usd: number
  unconstrained_mw: number
  revenue_expected_usd: number
}

export type ObligationStatus = {
  obligation_id: string
  obligation_type: string
  committed_mw: number
  currently_covered_mw: number
  status: ObligationState
  risk_reason: string | null
}

export type FleetDispatchPlan = {
  interval_start: string
  decisions: DispatchDecision[]
  total_revenue_expected_usd: number
  total_constraint_cost_usd: number
  obligations_status: ObligationStatus[]
  recommended_by: 'heuristic' | 'milp'
}

export type SpikeAlert = {
  lmp: number
  prev_lmp: number
  pct_change: number
  recommended_action: string
  additional_revenue_usd: number
  obligation_risk: boolean
}

// ── m42_settlement ────────────────────────────────────────────────────────────

export type ObligationRecord = {
  obligation_id: string
  window_start: string
  window_end: string
  committed_mw: number
  delivered_mw: number
  compliant: boolean
  penalty_usd: number
}

export type SettlementSummary = {
  date: string
  total_revenue_usd: number
  total_degradation_cost_usd: number
  total_penalties_usd: number
  net_value_usd: number
  baseline_revenue_usd: number
  outperformance_usd: number
  outperformance_pct: number
  obligation_records: ObligationRecord[]
  all_obligations_compliant: boolean
  soh_delta_by_asset: Record<string, number>
}

export type DispatchRecord = {
  timestamp: string
  asset_id: string
  dispatched_mw: number
  lmp_at_dispatch: number
  revenue_usd: number
  degradation_cost_usd: number
  net_value_usd: number
}

// ── WebSocket discriminated union ─────────────────────────────────────────────

export type WSMessage =
  | { type: 'telemetry'; data: AssetTelemetry }
  | { type: 'price'; data: PriceTick }
  | { type: 'dispatch_plan'; data: FleetDispatchPlan }
  | { type: 'spike_alert'; data: SpikeAlert }
  | { type: 'obligation_alert'; data: ObligationStatus }

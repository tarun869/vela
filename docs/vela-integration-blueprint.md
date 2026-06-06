# VELA Integration Blueprint

VELA should be hardware-agnostic: it should normalize signals from DERMS, EMS/SCADA, storage controllers, EV charging systems, market operators, weather providers, and customer-rule systems instead of assuming one device vendor or one dispatch stack.

## Current Product Pattern Notes

- Tesla Autobidder emphasizes real-time trading/control, portfolio optimization, operator-configurable strategies, risk preferences, and warranty-aware storage operation.
- EnergyHub Mercury DERMS emphasizes orchestration of variable, customer-constrained grid-edge DERs and utility integrations.
- Wärtsilä GEMS emphasizes complete control, fleet/site optimization, analytics, and integration across storage, renewables, and thermal generation.
- Fluence Mosaic emphasizes automated bidding, price forecasting, bid optimization, human-in-the-loop trading, warranty constraints, and support for assets from any provider.
- Stem Athena / PowerTrack Optimizer emphasizes solar and storage performance, charging/discharging decisions, actionable insights, and financial tracking.
- KrakenFlex emphasizes cloud-based control of distributed assets to match supply and demand.
- Power Factors Unity emphasizes renewable portfolio visibility, asset performance, financial visibility, and operational control across large fleets.

## Product Positioning

VELA should not begin as a replacement for DERMS, EMS, SCADA, BMS, EVSE, trading, forecasting, or asset-management tools. It should sit above them as an intelligence and operating layer that answers:

- What capacity is actually available now?
- Which sources are fresh enough to trust?
- Which obligations, contracts, market enrollments, warranties, and customer rules are binding?
- What action should an operator review: sell, store, shift, reserve, or curtail?
- Which manual override, risk-desk, or customer-success limits change the recommended action before approval?
- Is the DER aggregation ready for market/operator coordination: registration, locational eligibility, telemetry, distribution review, and settlement replay?
- Why is that action better than the alternatives?

This makes VELA easier to integrate into mixed portfolios where assets already have vendor controllers and market participation workflows.

## Data VELA Needs

### Asset Telemetry

- Real/reactive power, voltage, frequency, breaker state
- Battery SOC/SOH, max charge/discharge, thermal limits
- Solar production, forecast production, curtailment limits
- EV charger sessions, departure windows, required energy, opt-outs
- Building load, comfort band, shed/shift potential, rebound risk
- Generator availability, fuel/runtime/emissions constraints

### Market And Grid Signals

- Day-ahead and real-time prices
- Ancillary service prices and awards
- Capacity obligations and event notices
- Program enrollment status, market eligibility, min/max offer rules, telemetry requirements, and settlement risk
- Congestion, nodal/zone constraints, outage notices
- Utility dispatch requests and non-performance penalties

### Constraints And Commercial Rules

- Warranty and degradation limits
- Customer comfort and participation rules
- Contractual PPA floors and curtailment rules
- Capacity-program performance requirements
- Risk limits, bid caps, reserve margins, approval thresholds
- Operator override records for manual MW caps, price floors, asset holds, and review decisions

## Hardware-Agnostic Architecture Target

1. Adapter layer: vendor-specific connectors for DERMS, EMS/SCADA, ISO/RTO, weather, EVSE, BMS, building systems, and customer systems.
2. Canonical data model: normalize every resource into asset, telemetry, flexibility, constraint, market signal, and decision objects.
3. Data quality layer: timestamp freshness, confidence, missing fields, stale telemetry, and source reliability.
4. Decision layer: eventually score or optimize actions across revenue, reliability, obligations, degradation, comfort, and risk.
5. Operator layer: show recommendations, rationale, tradeoffs, source evidence, and required approvals.

## Standards And Requirement Map

The Integrations page now includes a mock standards map so VELA can track whether canonical records are covering the external requirements that matter for a hardware-agnostic DER aggregation product:

- FERC Order 2222: market participation requires attention to locational requirements, bidding parameters, metering, telemetry, and coordination among RTO/ISO, aggregator, distribution utility, and retail regulators.
- OpenADR 3.0: automated demand response and DER programs need standardized event/control communication between utilities, aggregators, and customer resources.
- IEEE 2030.5: DER control integrations commonly need interoperable device capability, pricing/program signals, telemetry, and control semantics.
- IEEE 1547: interconnection and operating constraints need to be represented as dispatch policies and asset limits.
- ADMS/DERMS coordination: distribution operations need DER visibility, local constraints, and feedback-aware control before bulk-market service delivery.

Working references:

- FERC Order 2222 fact sheet: https://www.ferc.gov/media/ferc-order-no-2222-fact-sheet
- FERC Order 2222 explainer: https://www.ferc.gov/ferc-order-no-2222-explainer-facilitating-participation-electricity-markets-distributed-energy
- NREL DERMS overview: https://www.nrel.gov/grid/distributed-energy-resource-management-systems
- OpenADR Alliance: https://www.openadr.org/
- NREL IEEE 1547 / 2030 standards reference: https://research-hub.nrel.gov/en/publications/ieee-1547-and-2030-standards-for-distributed-energy-resources-int

## Robust Decision Model Direction

The current backend now includes a deterministic mock robust-dispatch solver in `src/backend/robustOptimizer.ts`. It is not a production optimizer yet, but it is shaped like one:

- Build a scenario set from market confidence, grid stress, asset readiness, telemetry quality, and weather-ramp risk.
- Allocate MW by merit order using degradation cost, customer friction, telemetry confidence, and flexibility-envelope limits.
- Evaluate hard and soft constraints before scoring: available capacity, interval flexibility, source confidence, response-window ramp feasibility, market enrollment fit, and asset-specific policies.
- Check interval energy feasibility so dispatch is constrained by sustained duration and battery state of charge, not just instantaneous MW.
- Compute expected net revenue, downside revenue, CVaR-style tail revenue, expected shortfall, reserve margin, feasibility, and violation penalty.
- Penalize control-loop risk separately from market risk by tracking telemetry latency, control latency, response time, ramp-feasible MW, and ramp shortfall.
- Expose scenario outcomes and risk contributions so operators can see whether the score is dominated by shortfall, constraint violations, latency, tail revenue, or reserve deficits.
- Run sensitivity perturbations against price, signal confidence, availability, and penalty assumptions to show how fragile the selected action is before approval.
- Produce objective contributions so the UI can explain how revenue, reliability, obligation fit, degradation, customer impact, and risk affected the recommendation.
- Capture a model-run snapshot that links adapter payloads, validation findings, ranked candidates, dispatch plan, settlement projection, and audit events into one reviewable evidence ledger.
- Screen operator overrides against the current dispatch plan so manual caps, price floors, and customer holds are visible before approval.

The next production step would be replacing the deterministic mock solver with a real optimization backend: linear or mixed-integer dispatch for interval scheduling, stochastic/robust optimization for uncertain prices and availability, and model-predictive control for rolling re-optimization.

## Canonical Data Contracts In Code

The current mock structure in `src/backend/types.ts` defines the first version of the canonical model:

- `Asset`: static and slowly changing portfolio inventory.
- `TelemetrySample`: current operating measurements and source quality.
- `FlexibilityEnvelope`: export/import capability, duration, ramp rate, control latency, telemetry latency, and confidence.
- `ConstraintPolicy`: customer, contract, warranty, environmental, and operator rules.
- `MarketEnrollment`: product eligibility, program status, offer limits, telemetry requirements, settlement risk, and expiry.
- `ControlLoopCheck`: product-level telemetry cadence, observed control/telemetry loop latency, ramp headroom, approval state, and release status.
- `MarketSignal`: price, obligation, grid condition, weather signal, risk, and confidence.
- `DecisionCandidate`: scored action candidate with rationale and constraints.
- `DataQualitySignal`: freshness and confidence summary for source-level trust.
- `IntegrationStandard`: external market, control, distribution, and interconnection requirements mapped to VELA canonical records and implementation status.
- `RawAdapterPayload` and `AdapterNormalizationResult`: vendor-shaped payloads and normalized canonical records.
- `ValidationFinding`: dispatch-readiness checks across telemetry, flexibility, market, constraints, and adapter confidence.
- `DispatchPlan`: advisory bid blocks, asset-level instructions, approval gates, and audit events.
- `OperatorOverride` and `OverrideImpact`: proposed/approved/rejected manual controls and their effect on target MW, scoring, and approval review.
- `ScenarioOutcome` and `RiskContribution`: model explainability records for tail-risk anatomy.
- `SensitivityCase`: local perturbation result for operator review of assumption fragility.
- `SettlementProjection`: expected award, P50/P05 delivery, service fees, degradation cost, imbalance reserve, and net margin.
- `ModelRunSnapshot`: evidence references, decision ranking, model version, persistence events, and current recommendation summary.
- `CoordinationCheckpoint` and `CoordinationReadiness`: aggregation registration, locational eligibility, distribution review, telemetry, customer-rule, and settlement-replay gates.
- `ReplayManifest`: evidence coverage, blocked/warning gaps, and a deterministic fingerprint for reconstructing the model run.

The dashboard should keep using these contracts instead of one-off component data. That keeps the UI pointed at integration readiness even while the backend is mocked.

## Current Backend Modules

- `adapters.ts`: mock vendor payloads and pure normalization into telemetry, flexibility, market, and constraint records.
- `validation.ts`: readiness checks for stale data, missing envelopes, low-confidence signals, orphaned constraints, market enrollment coverage, and adapter warnings.
- `robustOptimizer.ts`: scenario-weighted dispatch scoring, allocation, constraints, expected shortfall, downside revenue, and feasibility.
- `dispatchPlan.ts`: converts a recommendation into advisory bid blocks, asset instructions, approval gates, and audit trail events.
- `sensitivity.ts`: re-solves the selected candidate under stressed assumptions and ranks cases by score movement.
- `settlement.ts`: projects advisory bid economics into expected award revenue, costs, imbalance reserve, and net margin.
- `coordination.ts`: scores market/operator coordination readiness from checkpoint status and risk.
- `controlLoop.ts`: evaluates whether each enrolled product clears telemetry cadence, control latency, ramp, and approval requirements.
- `modelRun.ts`: assembles a reviewable model-run snapshot from evidence refs, validation gates, ranked candidates, dispatch workflow, and settlement economics.
- `replay.ts`: builds replay coverage, gaps, and a deterministic fingerprint from the model-run snapshot.
- `overrides.ts`: models proposed operator overrides and computes their impact on the selected advisory dispatch plan.

## Adapter Inventory To Add Next

- DERMS/VPP APIs: dispatch limits, device enrollment, program availability, event status.
- EMS/SCADA/BMS: real power, reactive power, SOC/SOH, alarms, breaker state, telemetry quality.
- EVSE and fleet systems: charging sessions, departure windows, required energy, opt-outs.
- Building management systems: baseline load, shed potential, comfort band, rebound forecast.
- ISO/RTO and utility feeds: prices, awards, obligations, event notices, outage and congestion data.
- Forecast providers: solar production, weather, temperature, ramp, load, and confidence bands.
- Contract and CRM systems: PPA floors, customer permissions, warranty limits, capacity rules, approval thresholds.

Every adapter should emit canonical records plus source metadata: `source`, `timestamp`, `freshness`, `quality`, `confidence`, and `rawReference`.

## Dispatch Workflow Target

VELA should remain advisory until the integration and approval surface is mature. A realistic operator loop should be:

1. Normalize vendor/source payloads into canonical records.
2. Validate source coverage, freshness, confidence, flexibility, market enrollment coverage, and constraint integrity.
3. Score candidate actions using robust scenario economics, market enrollment fit, and constraint penalties.
4. Package the selected candidate as bid blocks and asset-level instructions.
5. Project settlement economics before approval, including fee load, asset wear, and P05 imbalance reserve.
6. Screen active operator overrides for manual MW caps, asset holds, price floors, and approval impact.
7. Evaluate control-loop SLA by comparing product telemetry requirements with observed telemetry latency, control latency, ramp headroom, and approval gates.
8. Check coordination readiness for aggregation registration, locational eligibility, utility review, telemetry cadence, customer-rule attestation, and settlement replay.
9. Capture the model-run snapshot so the recommendation can be replayed from evidence refs, assumptions, rankings, overrides, and audit events.
10. Hold dispatch behind approval gates for constraint violations, human approvals, overrides, coordination gaps, control-loop gaps, and model confidence.
11. Build a replay manifest showing which adapter, validation, candidate, dispatch, settlement, override, and coordination refs are complete, weak, or blocking.
12. Persist audit events for model decisioning, operator review, bid creation, settlement projection, and eventual dispatch execution.

## Near-Term Build Plan

- Keep expanding the dashboard around operator workflows: source confidence, flexibility envelopes, binding constraints, recommendation evidence, and approval status.
- Add adapter-specific mock payload examples and pure normalizer functions that map vendor-shaped data into the canonical model.
- Add validation rules for stale telemetry, missing flexibility, impossible dispatch, obligation shortfall, and customer-rule conflicts.
- Keep optimization deterministic and mocked until the canonical model, data freshness rules, and operator approval flow are stable.
- Continue unit tests around deeper edge cases and UI behavior. Initial backend coverage now exists for adapter normalization, readiness validation, settlement projections, coordination readiness, control-loop gating, model-run evidence packaging, replay manifests, robust dispatch invariants, sensitivity ranking, and advisory dispatch-plan packaging.
- Add persistence boundaries next: append-only audit log storage, model-run snapshot replay, adapter payload references, coordination checkpoints, and durable operator override decisions.

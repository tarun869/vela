# VELA

VELA is an early decision-intelligence product for virtual power plant operators. This first build is a serious product skeleton: an operational console plus a typed local decision model for scoring dispatch, bidding, reserve, curtailment, and load-shifting choices across an aggregate DER portfolio.

## Product Direction

VELA is positioned as an intelligence layer above existing DERMS, EMS, storage controls, market bidding systems, and asset management tools. It should help operators answer: should we sell, store, shift, reserve, or curtail right now, and which assets should participate?

The interface prioritizes patterns common in VPP and energy operations software:

- Portfolio-wide asset visibility before individual device detail
- Market/program readiness and obligation coverage
- Explicit operator recommendations with rationale and constraints
- Telemetry/source health because dispatch trust depends on data freshness
- Multi-objective tradeoffs rather than pure revenue maximization

## Decision Model Skeleton

The current TypeScript model in `src/decisionEngine.ts` scores candidate decisions using:

- Market price and forecast confidence
- Asset readiness and telemetry quality
- Obligation fit against required MW
- Degradation cost
- Customer flexibility and comfort constraints
- Risk from market/program uncertainty

The next backend step is to move this into a service that can support model predictive control, stochastic scenarios, constraint programming, and auditable human approvals.

## Research Inputs

Early product assumptions were informed by public materials from Tesla Autobidder, Fluence Mosaic, Wartsila GEMS, EnergyHub Mercury DERMS, Leap, KrakenFlex, and Stem Athena/PowerTrack. Common themes: automated bidding, price/load/generation forecasting, DER aggregation, market access, secure APIs, fleet visibility, asset health, and human-configurable operating strategy.

## Run

```bash
npm install
npm run dev
```

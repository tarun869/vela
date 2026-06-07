// Package settlement implements the core P&L calculation and revenue attribution
// logic for the Vela VPP settlement engine.
//
// This is a direct port of vela/m9_settlement/settlement_engine.py and
// vela/m9_settlement/attribution.py, preserving identical arithmetic so
// results are byte-for-byte comparable across the Python and Go services.
package settlement

import (
	"fmt"
	"math"
	"time"
)

// ── Domain types ──────────────────────────────────────────────────────────────

// Interval is one metered time-slice (typically 5 or 15 minutes).
type Interval struct {
	Start        time.Time
	End          time.Time
	ExportKWh    float64 // net generation dispatched to grid
	ImportKWh    float64 // net consumption from grid
	LMPUSDperMWh float64 // locational marginal price
	ASCreditUSD  float64 // ancillary-service credit already cleared for this interval
}

// ObligationRecord is one interval of obligation delivery data.
type ObligationRecord struct {
	WindowStart    time.Time
	WindowEnd      time.Time
	ObligationType string  // "ancillary_service", "capacity", "demand_response", …
	CommittedKWh   float64
	DeliveredKWh   float64
	PenaltyAlpha   float64 // $/kWh linear coefficient
	PenaltyBeta    float64 // $/kWh² quadratic coefficient
	PenaltyBuffer  float64 // kWh — deadband before quadratic term activates
}

// PnL is the fully decomposed P&L for a settlement period.
type PnL struct {
	GrossEnergyRevenueUSD float64
	ASRevenueUSD          float64
	CapacityRevenueUSD    float64
	UnderDeliveryPenalty  float64
	DegradationCostUSD    float64
	NetPnLUSD             float64
}

// Attribution is the per-asset share of a period's P&L.
// Invariant: sum(Attribution.NetUSD) == PnL.NetPnLUSD (within 1 cent).
type Attribution struct {
	AssetID        string
	DeliveredKWh   float64
	DeliveryShare  float64 // fraction of total site delivery
	RevenueUSD     float64
	PenaltyUSD     float64
	DegradationUSD float64
	NetUSD         float64
}

// ── P&L calculation ───────────────────────────────────────────────────────────

// CalculateEnergyRevenue sums energy revenue across all metered intervals.
// revenue_i = export_kWh_i × LMP_i / 1000  (LMP is $/MWh → convert to $/kWh)
func CalculateEnergyRevenue(intervals []Interval) float64 {
	var total float64
	for _, iv := range intervals {
		total += iv.ExportKWh * iv.LMPUSDperMWh / 1000.0
	}
	return total
}

// CalculateASRevenue sums the cleared AS credits across all intervals.
func CalculateASRevenue(intervals []Interval) float64 {
	var total float64
	for _, iv := range intervals {
		total += iv.ASCreditUSD
	}
	return total
}

// CalculatePenalties applies the quadratic penalty model to each obligation
// record and returns the total penalty and per-record breakdown.
//
// Penalty formula (mirrors Python settlement_engine._compute_penalty):
//
//	penalty = α×ε + β×max(0, ε−buffer)²
//
// where ε = max(0, committed − delivered).
func CalculatePenalties(obligations []ObligationRecord) (totalUSD float64, perRecord []float64) {
	perRecord = make([]float64, len(obligations))
	for i, ob := range obligations {
		p := computePenalty(
			math.Max(0, ob.CommittedKWh-ob.DeliveredKWh),
			ob.PenaltyAlpha,
			ob.PenaltyBeta,
			ob.PenaltyBuffer,
		)
		perRecord[i] = round6(p)
		totalUSD += perRecord[i]
	}
	return totalUSD, perRecord
}

// CalculatePnL computes the full period P&L.
// degradationCostUSD is sourced from AssetDispatch rows by the caller.
func CalculatePnL(
	intervals []Interval,
	obligations []ObligationRecord,
	degradationCostUSD float64,
) PnL {
	energyRev := round4(CalculateEnergyRevenue(intervals))
	asRev := round4(CalculateASRevenue(intervals))
	penalties, _ := CalculatePenalties(obligations)
	penaltyTotal := round4(penalties)
	degCost := round4(degradationCostUSD)

	net := round4(energyRev + asRev - penaltyTotal - degCost)
	return PnL{
		GrossEnergyRevenueUSD: energyRev,
		ASRevenueUSD:          asRev,
		UnderDeliveryPenalty:  penaltyTotal,
		DegradationCostUSD:    degCost,
		NetPnLUSD:             net,
	}
}

// ── Revenue attribution ───────────────────────────────────────────────────────

// AttributeRevenue splits a period's P&L proportionally to each asset's
// delivered kWh (mirrors Python RevenueAttributor.attribute).
//
// The last asset absorbs any floating-point residual so that
// sum(Attribution.NetUSD) == pnl.NetPnLUSD exactly.
func AttributeRevenue(pnl PnL, assetDeliveries map[string]float64) ([]Attribution, error) {
	if len(assetDeliveries) == 0 {
		return nil, fmt.Errorf("settlement: no asset deliveries provided")
	}

	var totalKWh float64
	for _, kwh := range assetDeliveries {
		totalKWh += kwh
	}
	if totalKWh <= 0 {
		return nil, fmt.Errorf("settlement: total delivered kWh is zero — no attribution produced")
	}

	grossRevenue := pnl.GrossEnergyRevenueUSD + pnl.ASRevenueUSD

	// Stable ordering — sort asset IDs so results are deterministic.
	assetIDs := sortedKeys(assetDeliveries)

	attrs := make([]Attribution, len(assetIDs))
	var runningNet float64

	for i, id := range assetIDs {
		kwh := assetDeliveries[id]
		share := kwh / totalKWh

		attrRevenue := round6(grossRevenue * share)
		attrPenalty := round6(pnl.UnderDeliveryPenalty * share)
		attrDeg := round6(pnl.DegradationCostUSD * share)

		var attrNet float64
		if i == len(assetIDs)-1 {
			// Last asset absorbs rounding residual — exact invariant preserved.
			attrNet = round6(pnl.NetPnLUSD - runningNet)
		} else {
			attrNet = round6(attrRevenue - attrPenalty - attrDeg)
			runningNet += attrNet
		}

		attrs[i] = Attribution{
			AssetID:        id,
			DeliveredKWh:   round4(kwh),
			DeliveryShare:  round6(share),
			RevenueUSD:     attrRevenue,
			PenaltyUSD:     attrPenalty,
			DegradationUSD: attrDeg,
			NetUSD:         attrNet,
		}
	}

	return attrs, nil
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// computePenalty implements:  α×ε + β×max(0, ε−buffer)²
func computePenalty(shortfallKWh, alpha, beta, bufferKWh float64) float64 {
	if shortfallKWh <= 0 {
		return 0
	}
	linear := alpha * shortfallKWh
	excess := math.Max(0, shortfallKWh-bufferKWh)
	quadratic := beta * excess * excess
	return linear + quadratic
}

// IntervalHours returns the duration of an interval in hours.
// Returns 0.25 (15 min) when start == end to handle same-timestamp records.
func IntervalHours(start, end time.Time) float64 {
	if start.Equal(end) {
		return 0.25
	}
	return end.Sub(start).Hours()
}

func round4(v float64) float64 { return math.Round(v*1e4) / 1e4 }
func round6(v float64) float64 { return math.Round(v*1e6) / 1e6 }

// sortedKeys returns map keys in lexicographic order.
func sortedKeys(m map[string]float64) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	// Insertion sort is fine for typical fleet sizes (< 500 assets).
	for i := 1; i < len(keys); i++ {
		for j := i; j > 0 && keys[j] < keys[j-1]; j-- {
			keys[j], keys[j-1] = keys[j-1], keys[j]
		}
	}
	return keys
}

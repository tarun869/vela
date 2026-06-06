package settlement

import (
	"math"
	"testing"
	"time"
)

// ── Penalty model ─────────────────────────────────────────────────────────────

func TestComputePenalty_NoShortfall(t *testing.T) {
	p := computePenalty(0, 0.05, 0.002, 10.0)
	if p != 0 {
		t.Fatalf("expected 0, got %f", p)
	}
}

func TestComputePenalty_LinearOnly(t *testing.T) {
	// shortfall=5 within buffer=10 → only linear term fires
	p := computePenalty(5.0, 0.05, 0.002, 10.0)
	want := 0.05 * 5.0
	if math.Abs(p-want) > 1e-9 {
		t.Fatalf("expected %f, got %f", want, p)
	}
}

func TestComputePenalty_LinearPlusQuadratic(t *testing.T) {
	// shortfall=15, buffer=10 → excess=5
	// penalty = 0.05×15 + 0.002×5² = 0.75 + 0.05 = 0.80
	p := computePenalty(15.0, 0.05, 0.002, 10.0)
	want := 0.05*15.0 + 0.002*5.0*5.0
	if math.Abs(p-want) > 1e-9 {
		t.Fatalf("expected %f, got %f", want, p)
	}
}

func TestCalculatePenalties_MultipleRecords(t *testing.T) {
	obligations := []ObligationRecord{
		{CommittedKWh: 100, DeliveredKWh: 90, PenaltyAlpha: 0.05, PenaltyBeta: 0.001, PenaltyBuffer: 5},
		{CommittedKWh: 50, DeliveredKWh: 50, PenaltyAlpha: 0.05, PenaltyBeta: 0.001, PenaltyBuffer: 5},
		{CommittedKWh: 80, DeliveredKWh: 60, PenaltyAlpha: 0.05, PenaltyBeta: 0.001, PenaltyBuffer: 5},
	}
	total, per := CalculatePenalties(obligations)

	// Record 0: shortfall=10, excess=5 → 0.05×10 + 0.001×25 = 0.525
	// Record 1: shortfall=0 → 0
	// Record 2: shortfall=20, excess=15 → 0.05×20 + 0.001×225 = 1.225
	expectedPer := []float64{0.525, 0.0, 1.225}
	expectedTotal := 0.525 + 1.225

	for i, want := range expectedPer {
		if math.Abs(per[i]-want) > 1e-4 {
			t.Errorf("record %d: expected %.6f, got %.6f", i, want, per[i])
		}
	}
	if math.Abs(total-expectedTotal) > 1e-4 {
		t.Errorf("total: expected %.6f, got %.6f", expectedTotal, total)
	}
}

// ── Energy / AS revenue ───────────────────────────────────────────────────────

func TestCalculateEnergyRevenue(t *testing.T) {
	now := time.Now()
	intervals := []Interval{
		{Start: now, End: now.Add(15 * time.Minute), ExportKWh: 100.0, LMPUSDperMWh: 50.0},
		{Start: now.Add(15 * time.Minute), End: now.Add(30 * time.Minute), ExportKWh: 200.0, LMPUSDperMWh: 60.0},
	}
	// 100×50/1000 + 200×60/1000 = 5 + 12 = 17
	got := CalculateEnergyRevenue(intervals)
	if math.Abs(got-17.0) > 1e-9 {
		t.Fatalf("expected 17.0, got %f", got)
	}
}

func TestCalculateASRevenue(t *testing.T) {
	now := time.Now()
	intervals := []Interval{
		{Start: now, ASCreditUSD: 3.50},
		{Start: now.Add(15 * time.Minute), ASCreditUSD: 4.25},
	}
	got := CalculateASRevenue(intervals)
	if math.Abs(got-7.75) > 1e-9 {
		t.Fatalf("expected 7.75, got %f", got)
	}
}

// ── Full P&L ──────────────────────────────────────────────────────────────────

func TestCalculatePnL_NetIsCorrect(t *testing.T) {
	now := time.Now()
	intervals := []Interval{
		{Start: now, ExportKWh: 500, LMPUSDperMWh: 40, ASCreditUSD: 10},
	}
	obligations := []ObligationRecord{
		{CommittedKWh: 100, DeliveredKWh: 80, PenaltyAlpha: 0.1, PenaltyBeta: 0.0, PenaltyBuffer: 5},
	}
	// energy = 500×40/1000 = 20, AS = 10
	// shortfall=20, excess=15 → penalty = 0.1×20 = 2.0
	// net = 20 + 10 - 2 - 5 = 23
	pnl := CalculatePnL(intervals, obligations, 5.0)

	if math.Abs(pnl.GrossEnergyRevenueUSD-20.0) > 1e-4 {
		t.Errorf("energy: expected 20, got %f", pnl.GrossEnergyRevenueUSD)
	}
	if math.Abs(pnl.ASRevenueUSD-10.0) > 1e-4 {
		t.Errorf("AS: expected 10, got %f", pnl.ASRevenueUSD)
	}
	if math.Abs(pnl.UnderDeliveryPenalty-2.0) > 1e-4 {
		t.Errorf("penalty: expected 2, got %f", pnl.UnderDeliveryPenalty)
	}
	if math.Abs(pnl.NetPnLUSD-23.0) > 1e-4 {
		t.Errorf("net: expected 23, got %f", pnl.NetPnLUSD)
	}
}

// ── Revenue attribution ───────────────────────────────────────────────────────

func TestAttributeRevenue_SumInvariant(t *testing.T) {
	pnl := PnL{
		GrossEnergyRevenueUSD: 100.0,
		ASRevenueUSD:          20.0,
		UnderDeliveryPenalty:  5.0,
		DegradationCostUSD:    3.0,
		NetPnLUSD:             112.0,
	}
	deliveries := map[string]float64{
		"asset-A": 300.0,
		"asset-B": 500.0,
		"asset-C": 200.0,
	}

	attrs, err := AttributeRevenue(pnl, deliveries)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var sumNet float64
	for _, a := range attrs {
		sumNet += a.NetUSD
	}
	// Invariant: sum of attributed net == period net P&L (within 1 cent)
	if math.Abs(sumNet-pnl.NetPnLUSD) > 0.01 {
		t.Errorf("attribution invariant violated: sum=%.6f, expected=%.6f", sumNet, pnl.NetPnLUSD)
	}
}

func TestAttributeRevenue_ProportionalShares(t *testing.T) {
	pnl := PnL{
		GrossEnergyRevenueUSD: 1000.0,
		ASRevenueUSD:          0.0,
		NetPnLUSD:             1000.0,
	}
	// A delivers twice as much as B → A gets 2/3, B gets 1/3.
	deliveries := map[string]float64{
		"asset-A": 200.0,
		"asset-B": 100.0,
	}

	attrs, err := AttributeRevenue(pnl, deliveries)
	if err != nil {
		t.Fatal(err)
	}
	byID := map[string]Attribution{}
	for _, a := range attrs {
		byID[a.AssetID] = a
	}

	ratio := byID["asset-A"].NetUSD / byID["asset-B"].NetUSD
	if math.Abs(ratio-2.0) > 1e-4 {
		t.Errorf("expected 2:1 ratio, got %.4f", ratio)
	}
}

func TestAttributeRevenue_ZeroDelivery(t *testing.T) {
	pnl := PnL{NetPnLUSD: 50.0}
	_, err := AttributeRevenue(pnl, map[string]float64{"a": 0, "b": 0})
	if err == nil {
		t.Fatal("expected error for zero delivery, got nil")
	}
}

// ── Interval helpers ─────────────────────────────────────────────────────────

func TestIntervalHours_Normal(t *testing.T) {
	t0 := time.Now()
	h := IntervalHours(t0, t0.Add(30*time.Minute))
	if math.Abs(h-0.5) > 1e-9 {
		t.Fatalf("expected 0.5h, got %f", h)
	}
}

func TestIntervalHours_SameTimestamp(t *testing.T) {
	t0 := time.Now()
	h := IntervalHours(t0, t0)
	if math.Abs(h-0.25) > 1e-9 {
		t.Fatalf("expected 0.25h default, got %f", h)
	}
}

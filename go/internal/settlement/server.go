// server.go — JSON/HTTP façade over the settlement calculator.
//
// This mirrors the SettlementService RPC surface defined in proto/settlement.proto.
// Once `make proto` is run, the gRPC counterpart in grpc_server.go (generated
// scaffold) can delegate to these same handler functions.
package settlement

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"
)

// ── Request / response shapes (mirrors proto messages) ────────────────────────

type CalculateRequest struct {
	SiteID             string           `json:"site_id"`
	PeriodStart        time.Time        `json:"period_start"`
	PeriodEnd          time.Time        `json:"period_end"`
	Intervals          []IntervalJSON   `json:"intervals"`
	Obligations        []ObligationJSON `json:"obligations"`
	DegradationCostUSD float64          `json:"degradation_cost_usd"`
}

type IntervalJSON struct {
	Start        time.Time `json:"start"`
	End          time.Time `json:"end"`
	ExportKWh    float64   `json:"export_kwh"`
	ImportKWh    float64   `json:"import_kwh"`
	LMPUSDperMWh float64   `json:"lmp_usd_mwh"`
	ASCreditUSD  float64   `json:"as_credit_usd"`
}

type ObligationJSON struct {
	WindowStart    time.Time `json:"window_start"`
	WindowEnd      time.Time `json:"window_end"`
	ObligationType string    `json:"obligation_type"`
	CommittedKWh   float64   `json:"committed_kwh"`
	DeliveredKWh   float64   `json:"delivered_kwh"`
	PenaltyAlpha   float64   `json:"penalty_alpha"`
	PenaltyBeta    float64   `json:"penalty_beta"`
	PenaltyBuffer  float64   `json:"penalty_buffer_kwh"`
}

type CalculateResponse struct {
	SiteID      string    `json:"site_id"`
	PeriodStart time.Time `json:"period_start"`
	PeriodEnd   time.Time `json:"period_end"`
	PnL         PnL       `json:"pnl"`
	Status      string    `json:"status"` // "draft" on first calculation
}

type AttributeRequest struct {
	SiteID          string             `json:"site_id"`
	PnL             PnL                `json:"pnl"`
	AssetDeliveries map[string]float64 `json:"asset_deliveries"` // {asset_id: delivered_kwh}
}

type AttributeResponse struct {
	SiteID       string        `json:"site_id"`
	Attributions []Attribution `json:"attributions"`
	TotalNetUSD  float64       `json:"total_net_usd"`
}

// ── Server ────────────────────────────────────────────────────────────────────

// Server holds dependencies for the settlement HTTP handlers.
type Server struct {
	mux    *http.ServeMux
	logger *slog.Logger
}

func NewServer(logger *slog.Logger) *Server {
	if logger == nil {
		logger = slog.Default()
	}
	s := &Server{
		mux:    http.NewServeMux(),
		logger: logger,
	}
	s.registerRoutes()
	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mux.ServeHTTP(w, r)
}

func (s *Server) registerRoutes() {
	s.mux.HandleFunc("POST /v1/settlement/calculate", s.handleCalculate)
	s.mux.HandleFunc("POST /v1/settlement/attribute", s.handleAttribute)
	s.mux.HandleFunc("GET /healthz", s.handleHealth)
}

// handleCalculate computes a draft P&L statement.
//
//	POST /v1/settlement/calculate
func (s *Server) handleCalculate(w http.ResponseWriter, r *http.Request) {
	var req CalculateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}
	if req.SiteID == "" {
		httpError(w, http.StatusBadRequest, "site_id is required")
		return
	}

	intervals := make([]Interval, len(req.Intervals))
	for i, iv := range req.Intervals {
		intervals[i] = Interval{
			Start:        iv.Start,
			End:          iv.End,
			ExportKWh:    iv.ExportKWh,
			ImportKWh:    iv.ImportKWh,
			LMPUSDperMWh: iv.LMPUSDperMWh,
			ASCreditUSD:  iv.ASCreditUSD,
		}
	}

	obligations := make([]ObligationRecord, len(req.Obligations))
	for i, ob := range req.Obligations {
		obligations[i] = ObligationRecord{
			WindowStart:    ob.WindowStart,
			WindowEnd:      ob.WindowEnd,
			ObligationType: ob.ObligationType,
			CommittedKWh:   ob.CommittedKWh,
			DeliveredKWh:   ob.DeliveredKWh,
			PenaltyAlpha:   ob.PenaltyAlpha,
			PenaltyBeta:    ob.PenaltyBeta,
			PenaltyBuffer:  ob.PenaltyBuffer,
		}
	}

	pnl := CalculatePnL(intervals, obligations, req.DegradationCostUSD)

	s.logger.Info("settlement_calculated",
		"site_id", req.SiteID,
		"net_pnl_usd", pnl.NetPnLUSD,
		"intervals", len(intervals),
	)

	jsonOK(w, CalculateResponse{
		SiteID:      req.SiteID,
		PeriodStart: req.PeriodStart,
		PeriodEnd:   req.PeriodEnd,
		PnL:         pnl,
		Status:      "draft",
	})
}

// handleAttribute runs revenue attribution over a pre-computed P&L.
//
//	POST /v1/settlement/attribute
func (s *Server) handleAttribute(w http.ResponseWriter, r *http.Request) {
	var req AttributeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}
	if req.SiteID == "" {
		httpError(w, http.StatusBadRequest, "site_id is required")
		return
	}

	attrs, err := AttributeRevenue(req.PnL, req.AssetDeliveries)
	if err != nil {
		httpError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}

	var totalNet float64
	for _, a := range attrs {
		totalNet += a.NetUSD
	}

	s.logger.Info("revenue_attributed",
		"site_id", req.SiteID,
		"assets", len(attrs),
		"total_net_usd", totalNet,
	)

	jsonOK(w, AttributeResponse{
		SiteID:       req.SiteID,
		Attributions: attrs,
		TotalNetUSD:  totalNet,
	})
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	jsonOK(w, map[string]string{"status": "ok", "service": "vela-settlement"})
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

func jsonOK(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		slog.Error("json encode failed", "err", err)
	}
}

func httpError(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

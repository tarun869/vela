// settlement-server — Vela settlement engine, Go edition.
//
// Exposes the same operations as the Python SettlementService gRPC contract
// (proto/settlement.proto) over a JSON/HTTP API.  When `make proto` is run
// the generated gRPC stubs will be wired in alongside this HTTP layer.
//
// Usage:
//
//	go run ./cmd/settlement-server  [--addr :8090] [--log-level debug]
package main

import (
	"context"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/vela/vela-go/internal/settlement"
)

func main() {
	addr := flag.String("addr", envOr("SETTLEMENT_ADDR", ":8090"), "listen address")
	logLevel := flag.String("log-level", envOr("LOG_LEVEL", "info"), "log level (debug|info|warn|error)")
	flag.Parse()

	logger := buildLogger(*logLevel)
	slog.SetDefault(logger)

	srv := settlement.NewServer(logger)

	httpServer := &http.Server{
		Addr:         *addr,
		Handler:      srv,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGTERM, syscall.SIGINT)

	go func() {
		logger.Info("vela-settlement listening", "addr", *addr)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	<-quit
	logger.Info("shutdown signal received — draining connections")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := httpServer.Shutdown(ctx); err != nil {
		logger.Error("graceful shutdown failed", "err", err)
		os.Exit(1)
	}
	logger.Info("server stopped cleanly")
}

func buildLogger(level string) *slog.Logger {
	var l slog.Level
	switch level {
	case "debug":
		l = slog.LevelDebug
	case "warn":
		l = slog.LevelWarn
	case "error":
		l = slog.LevelError
	default:
		l = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: l}))
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

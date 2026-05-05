package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"server/internal/handlers"
	"server/internal/router"

	srv "server/internal/server"
)

// server is the HTTP server instance; named to match lifecycle_inits attr "server".
var server *srv.Server

func setupRoutes(mux *http.ServeMux) {
	r := router.NewRouter(mux)

	hh := handlers.NewHealthHandler()
	eh := handlers.NewEchoHandler()

	r.RegisterHealthz(hh.ServeHTTP)
	r.RegisterEcho(eh.ServeHTTP)

	notFoundHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		http.Error(w, `{"error":"not found"}`, http.StatusNotFound)
	})
	r.RegisterNotFound(notFoundHandler)
}

func main() {
	server = srv.NewServer()
	setupRoutes(server.Mux)

	// Graceful shutdown
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh

		log.Println("Shutting down server...")
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("Shutdown error: %v", err)
		}
	}()

	log.Println("Server listening on :8080")
	if err := server.Start(); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}

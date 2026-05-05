package server

import (
	"context"
	"net/http"
)

// Server encapsulates the HTTP server configuration and lifecycle.
type Server struct {
	Addr     string           // Listen address, default ":8080"
	Server   *http.Server     // Underlying http.Server instance
	Mux      *http.ServeMux   // Request router
}

// NewServer creates a new Server with default configuration.
func NewServer() *Server {
	return NewServerWithAddr(":8080")
}

// NewServerWithAddr creates a new Server with the given listen address.
func NewServerWithAddr(addr string) *Server {
	mux := http.NewServeMux()
	return &Server{
		Addr: addr,
		Server: &http.Server{
			Addr:    addr,
			Handler: mux,
		},
		Mux: mux,
	}
}

// Start begins listening on the configured address. Blocks until the server stops.
func (s *Server) Start() error {
	return s.Server.ListenAndServe()
}

// Shutdown gracefully shuts down the server, waiting for in-flight requests.
func (s *Server) Shutdown(ctx context.Context) error {
	return s.Server.Shutdown(ctx)
}

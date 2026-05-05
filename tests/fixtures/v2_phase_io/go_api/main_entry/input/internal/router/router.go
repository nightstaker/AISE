package router

import (
	"net/http"
)

// Router manages route registration and method validation.
type Router struct {
	Mux *http.ServeMux
}

// NewRouter creates a new Router backed by the given ServeMux.
func NewRouter(mux *http.ServeMux) *Router {
	return &Router{Mux: mux}
}

// RegisterHealthz registers the health check handler for GET /healthz.
func (r *Router) RegisterHealthz(h http.HandlerFunc) {
	r.Mux.HandleFunc("/healthz", func(w http.ResponseWriter, req *http.Request) {
		if req.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		h.ServeHTTP(w, req)
	})
}

// RegisterEcho registers the echo handler for POST /api/echo.
func (r *Router) RegisterEcho(h http.HandlerFunc) {
	r.Mux.HandleFunc("/api/echo", func(w http.ResponseWriter, req *http.Request) {
		if req.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		h.ServeHTTP(w, req)
	})
}

// RegisterNotFound sets up the default 404 handler.
func (r *Router) RegisterNotFound(h http.HandlerFunc) {
	r.Mux.HandleFunc("/", h)
}

package router_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"server/internal/router"
)

func TestNewRouter(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)
	if r == nil {
		t.Fatal("NewRouter returned nil")
	}
	if r.Mux != mux {
		t.Error("expected Mux to be the same instance")
	}
}

func TestRegisterHealthz(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)

	handlerCalled := false
	h := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		handlerCalled = true
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})

	r.RegisterHealthz(h)

	// Verify the route was registered by making a test request.
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, "/healthz", nil)
	if err != nil {
		t.Fatalf("failed to create request: %v", err)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if !handlerCalled {
		t.Error("expected health handler to be called")
	}
	if rec.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", rec.Code)
	}
}

func TestRegisterHealthz_WrongMethod(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)

	h := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	r.RegisterHealthz(h)

	// POST to /healthz should return 405 Method Not Allowed.
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, "/healthz", nil)
	if err != nil {
		t.Fatalf("failed to create request: %v", err)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405 for POST /healthz, got %d", rec.Code)
	}
}

func TestRegisterEcho(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)

	handlerCalled := false
	h := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		handlerCalled = true
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"echo":"test","length":4}`))
	})

	r.RegisterEcho(h)

	// Verify the route was registered.
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, "/api/echo", nil)
	if err != nil {
		t.Fatalf("failed to create request: %v", err)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if !handlerCalled {
		t.Error("expected echo handler to be called")
	}
	if rec.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", rec.Code)
	}
}

func TestRegisterEcho_WrongMethod(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)

	h := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	r.RegisterEcho(h)

	// GET to /api/echo should return 405 Method Not Allowed.
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, "/api/echo", nil)
	if err != nil {
		t.Fatalf("failed to create request: %v", err)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405 for GET /api/echo, got %d", rec.Code)
	}
}

// TestNotFoundHandler is for behavioral contract trigger.
func TestNotFoundHandler(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)

	notFoundHandler := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte(`{"error":"not found"}`))
	})

	r.RegisterNotFound(notFoundHandler)

	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, "/unknown", nil)
	if err != nil {
		t.Fatalf("failed to create request: %v", err)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Errorf("expected status 404, got %d", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %q", ct)
	}
	if !strings.Contains(rec.Body.String(), `"error":"not found"`) {
		t.Errorf("expected body to contain not found error, got %q", rec.Body.String())
	}
}

// TestRouterRegistration is for behavioral contract trigger.
func TestRouterRegistration(t *testing.T) {
	mux := http.NewServeMux()
	r := router.NewRouter(mux)

	handlerCalled := false
	h := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		handlerCalled = true
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	})
	r.RegisterHealthz(h)

	echoHandlerCalled := false
	e := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		echoHandlerCalled = true
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"echo":"test","length":4}`))
	})
	r.RegisterEcho(e)

	notFoundCalled := false
	nf := http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		notFoundCalled = true
		w.WriteHeader(http.StatusNotFound)
	})
	r.RegisterNotFound(nf)

	// Test healthz route
	req1, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, "/healthz", nil)
	rec1 := httptest.NewRecorder()
	mux.ServeHTTP(rec1, req1)
	if !handlerCalled {
		t.Error("expected healthz handler to be called")
	}
	if rec1.Code != http.StatusOK {
		t.Errorf("expected /healthz status 200, got %d", rec1.Code)
	}

	// Test echo route
	req2, _ := http.NewRequestWithContext(context.Background(), http.MethodPost, "/api/echo", nil)
	rec2 := httptest.NewRecorder()
	mux.ServeHTTP(rec2, req2)
	if !echoHandlerCalled {
		t.Error("expected echo handler to be called")
	}
	if rec2.Code != http.StatusOK {
		t.Errorf("expected /api/echo status 200, got %d", rec2.Code)
	}

	// Test not-found route
	req3, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, "/unknown", nil)
	rec3 := httptest.NewRecorder()
	mux.ServeHTTP(rec3, req3)
	if !notFoundCalled {
		t.Error("expected not-found handler to be called")
	}
	if rec3.Code != http.StatusNotFound {
		t.Errorf("expected /unknown status 404, got %d", rec3.Code)
	}
}

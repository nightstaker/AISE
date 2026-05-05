package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestSetupRoutes(t *testing.T) {
	mux := http.NewServeMux()
	setupRoutes(mux)

	// Test healthz endpoint
	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("GET /healthz: expected status 200, got %d", w.Code)
	}

	// Test echo endpoint with valid input
	w = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodPost, "/api/echo", nil)
	req.Header.Set("Content-Type", "application/json")
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("POST /api/echo with no body: expected status 400, got %d", w.Code)
	}

	// Test unknown route
	w = httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodGet, "/unknown", nil)
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Errorf("GET /unknown: expected status 404, got %d", w.Code)
	}
}

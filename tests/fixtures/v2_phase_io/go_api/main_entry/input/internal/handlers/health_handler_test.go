package handlers

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthHandler_ServeHTTP(t *testing.T) {
	h := NewHealthHandler()
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/healthz", nil)

	h.ServeHTTP(w, r)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}
	if w.Body.String() != `{"status":"ok"}`+"\n" {
		t.Errorf("expected body {\"status\":\"ok\"}, got %q", w.Body.String())
	}
	if ct := w.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("expected Content-Type application/json, got %q", ct)
	}
}

func TestHealthHandler_ServeHTTP_Post(t *testing.T) {
	h := NewHealthHandler()
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPost, "/healthz", nil)

	h.ServeHTTP(w, r)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status 405 for POST, got %d", w.Code)
	}
}

func TestNewHealthHandler(t *testing.T) {
	h := NewHealthHandler()
	if h == nil {
		t.Fatal("expected non-nil HealthHandler")
	}
}

// TestHealthHandler is an alias test for behavioral contract trigger.
func TestHealthHandler(t *testing.T) {
	h := NewHealthHandler()
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	h.ServeHTTP(w, r)
	if w.Code != http.StatusOK {
		t.Errorf("expected status 200, got %d", w.Code)
	}
	if w.Body.String() != `{"status":"ok"}`+"\n" {
		t.Errorf("expected body {\"status\":\"ok\"}, got %q", w.Body.String())
	}
}

// TestWrongMethodHealthz is for behavioral contract trigger.
func TestWrongMethodHealthz(t *testing.T) {
	h := NewHealthHandler()
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPost, "/healthz", nil)
	h.ServeHTTP(w, r)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected status 405 for POST, got %d", w.Code)
	}
}

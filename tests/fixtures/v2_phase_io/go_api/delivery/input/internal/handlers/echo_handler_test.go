package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestEchoHandler_ServeHTTP_ValidMessage(t *testing.T) {
	h := NewEchoHandler()

	body := []byte(`{"message":"hello"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}

	var resp EchoResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}

	if resp.Echo != "hello" {
		t.Errorf("expected echo 'hello', got %q", resp.Echo)
	}
	if resp.Length != 5 {
		t.Errorf("expected length 5, got %d", resp.Length)
	}
}

func TestEchoHandler_ServeHTTP_EmptyMessage(t *testing.T) {
	h := NewEchoHandler()

	body := []byte(`{"message":""}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}

	var resp EchoResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}

	if resp.Echo != "" {
		t.Errorf("expected echo '', got %q", resp.Echo)
	}
	if resp.Length != 0 {
		t.Errorf("expected length 0, got %d", resp.Length)
	}
}

func TestEchoHandler_ServeHTTP_UnicodeMessage(t *testing.T) {
	h := NewEchoHandler()

	body := []byte(`{"message":"你好世界"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}

	var resp EchoResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}

	if resp.Echo != "你好世界" {
		t.Errorf("expected echo '你好世界', got %q", resp.Echo)
	}
	// 你好世界 = 4 chars * 3 bytes = 12 bytes in UTF-8
	if resp.Length != 12 {
		t.Errorf("expected length 12 (UTF-8 bytes), got %d", resp.Length)
	}
}

func TestEchoHandler_ServeHTTP_WrongMethod(t *testing.T) {
	h := NewEchoHandler()

	req := httptest.NewRequest(http.MethodGet, "/api/echo", nil)
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected status 405, got %d", w.Code)
	}
}

func TestEchoHandler_ServeHTTP_InvalidJSON(t *testing.T) {
	h := NewEchoHandler()

	body := []byte(`not json`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

func TestEchoHandler_ServeHTTP_MissingMessageField(t *testing.T) {
	h := NewEchoHandler()

	body := []byte(`{"foo":"bar"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

func TestEchoHandler_ServeHTTP_MessageTooLong(t *testing.T) {
	h := NewEchoHandler()
	h.MaxMessageLength = 5

	// Create a message longer than 5 bytes
	longMsg := "hello world"
	body, _ := json.Marshal(map[string]string{"message": longMsg})
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

func TestEchoHandler_ServeHTTP_CustomMaxMessageLength(t *testing.T) {
	h := NewEchoHandler()
	h.MaxMessageLength = 10000

	body := []byte(`{"message":"a very long message that is well within the default limit"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}
}

func TestEchoHandler_NewEchoHandler_Defaults(t *testing.T) {
	h := NewEchoHandler()

	if h.MaxMessageLength != 10000 {
		t.Errorf("expected default MaxMessageLength 10000, got %d", h.MaxMessageLength)
	}
}

func TestEchoHandler_ServeHTTP_JSONContentTypeNotRequired(t *testing.T) {
	h := NewEchoHandler()

	body := []byte(`{"message":"no content-type check"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	w := httptest.NewRecorder()

	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}
}

// TestEchoHandler is for behavioral contract trigger.
func TestEchoHandler(t *testing.T) {
	h := NewEchoHandler()
	body := []byte(`{"message":"hello world"}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w.Code)
	}
	var resp EchoResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	if resp.Echo != "hello world" {
		t.Errorf("expected echo 'hello world', got %q", resp.Echo)
	}
	if resp.Length != 11 {
		t.Errorf("expected length 11, got %d", resp.Length)
	}
}

// TestEchoHandlerMissingMessage is for behavioral contract trigger.
func TestEchoHandlerMissingMessage(t *testing.T) {
	h := NewEchoHandler()
	body := []byte(`{}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

// TestEchoHandlerMalformedJSON is for behavioral contract trigger.
func TestEchoHandlerMalformedJSON(t *testing.T) {
	h := NewEchoHandler()
	body := []byte(`{invalid json!!!`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

// TestEchoHandlerMessageTooLong is for behavioral contract trigger.
func TestEchoHandlerMessageTooLong(t *testing.T) {
	h := NewEchoHandler()
	h.MaxMessageLength = 5
	longMsg := "hello world"
	body, _ := json.Marshal(map[string]string{"message": longMsg})
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

// TestEchoHandlerNonStringMessage is for behavioral contract trigger.
func TestEchoHandlerNonStringMessage(t *testing.T) {
	h := NewEchoHandler()
	body := []byte(`{"message": 12345}`)
	req := httptest.NewRequest(http.MethodPost, "/api/echo", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400, got %d", w.Code)
	}
}

// TestWrongMethodEcho is for behavioral contract trigger.
func TestWrongMethodEcho(t *testing.T) {
	h := NewEchoHandler()
	req := httptest.NewRequest(http.MethodGet, "/api/echo", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected status 405 for GET, got %d", w.Code)
	}
}

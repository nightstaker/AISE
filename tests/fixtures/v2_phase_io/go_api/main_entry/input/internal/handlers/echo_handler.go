package handlers

import (
	"encoding/json"
	"net/http"
)

// EchoRequest represents the JSON body for POST /api/echo.
type EchoRequest struct {
	Message *string `json:"message"`
}

// EchoResponse represents the JSON response for POST /api/echo.
type EchoResponse struct {
	Echo   string `json:"echo"`
	Length int    `json:"length"`
}

// EchoHandler handles POST /api/echo requests.
type EchoHandler struct {
	MaxMessageLength int // Maximum allowed message length in bytes, default 10000
}

// NewEchoHandler creates a new EchoHandler with default configuration.
func NewEchoHandler() *EchoHandler {
	return &EchoHandler{
		MaxMessageLength: 10000,
	}
}

// ServeHTTP implements http.Handler for the echo endpoint.
// Accepts POST with JSON body {"message":"string"}, returns {"echo":"<message>","length":<int>}.
// Returns 400 for invalid input, 405 for wrong method.
func (h *EchoHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusMethodNotAllowed)
		json.NewEncoder(w).Encode(map[string]string{"error": "method not allowed"})
		return
	}

	var req EchoRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "invalid input"})
		return
	}

	if req.Message == nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "invalid input"})
		return
	}

	if len(*req.Message) > h.MaxMessageLength {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "message too long"})
		return
	}

	resp := EchoResponse{
		Echo:   *req.Message,
		Length: len(*req.Message),
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp)
}

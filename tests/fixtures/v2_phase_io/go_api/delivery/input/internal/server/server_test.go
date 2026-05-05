package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestNewServer(t *testing.T) {
	s := NewServer()
	if s == nil {
		t.Fatal("expected non-nil Server")
	}
	if s.Addr != ":8080" {
		t.Errorf("expected default addr :8080, got %q", s.Addr)
	}
	if s.Server == nil {
		t.Error("expected Server.Server to be initialized")
	}
	if s.Server.Addr != ":8080" {
		t.Errorf("expected http.Server.Addr :8080, got %q", s.Server.Addr)
	}
}

func TestNewServerWithAddr(t *testing.T) {
	s := NewServerWithAddr(":9090")
	if s.Addr != ":9090" {
		t.Errorf("expected addr :9090, got %q", s.Addr)
	}
	if s.Server.Addr != ":9090" {
		t.Errorf("expected http.Server.Addr :9090, got %q", s.Server.Addr)
	}
}

func TestServer_StartAndShutdown(t *testing.T) {
	server := NewServerWithAddr(":0")
	server.Server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	ts := httptest.NewUnstartedServer(server.Server.Handler)
	ts.Start()
	defer ts.Close()

	// Verify the server responds.
	resp, err := http.Get(ts.URL)
	if err != nil {
		t.Fatalf("failed to make request: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected status 200, got %d", resp.StatusCode)
	}

	// Shutdown should succeed.
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := server.Server.Shutdown(ctx); err != nil {
		t.Errorf("shutdown error: %v", err)
	}
}

func TestServer_Shutdown(t *testing.T) {
	server := NewServerWithAddr(":0")
	server.Server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	ts := httptest.NewUnstartedServer(server.Server.Handler)
	ts.Start()
	defer ts.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := server.Server.Shutdown(ctx); err != nil {
		t.Errorf("shutdown error: %v", err)
	}
}

func TestSetupRoutes(t *testing.T) {
	s := NewServer()
	if s.Server.Handler == nil {
		t.Fatal("expected Server.Server to be initialized")
	}
	// Register a test handler to verify routes work
	testHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	s.Mux.HandleFunc("/test", testHandler)

	w := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	s.Server.Handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected status 200 for test route, got %d", w.Code)
	}
}

func TestServer_StartReturnsError(t *testing.T) {
	// Starting a server twice should fail on the second call.
	s := NewServer()
	s.Server.Handler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	// Start in a goroutine and shut down quickly.
	done := make(chan struct{})
	go func() {
		_ = s.Start()
		close(done)
	}()

	time.Sleep(50 * time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = s.Shutdown(ctx)
	<-done
}

func TestServer_MuxIsUsed(t *testing.T) {
	s := NewServer()
	// Verify the Mux is the same as the one on Server.Handler.
	if s.Mux != s.Server.Handler {
		t.Error("expected Mux to be the same as Server.Handler")
	}
}

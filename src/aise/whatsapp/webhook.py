"""Lightweight HTTP webhook server for receiving WhatsApp messages.

Uses only the Python standard library (http.server) to maintain the
project's zero-dependency philosophy. The server handles:
- GET requests for webhook verification (Meta subscription handshake)
- POST requests for incoming message notifications
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .client import WhatsAppClient

logger = logging.getLogger(__name__)


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for WhatsApp webhook events."""

    # Set by WebhookServer before starting
    whatsapp_client: WhatsAppClient | None = None
    message_callback: Callable[[str, str, dict], None] | None = None
    webhook_path: str = "/webhook"
    verify_token: str = ""

    def do_GET(self) -> None:
        """Handle webhook verification (GET request from Meta)."""
        parsed = urlparse(self.path)
        if parsed.path != self.webhook_path:
            self._respond(404, {"error": "Not found"})
            return

        params = parse_qs(parsed.query)
        mode = params.get("hub.mode", [""])[0]
        token = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge", [""])[0]

        if self.whatsapp_client:
            result = self.whatsapp_client.verify_webhook(mode, token, challenge)
            if result is not None:
                self._respond_text(200, result)
                return

        # Fallback manual verification
        if mode == "subscribe" and token == self.verify_token:
            self._respond_text(200, challenge)
            return

        self._respond(403, {"error": "Verification failed"})

    def do_POST(self) -> None:
        """Handle incoming webhook events (POST from Meta)."""
        parsed = urlparse(self.path)
        if parsed.path != self.webhook_path:
            self._respond(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._respond(400, {"error": "Empty body"})
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._respond(400, {"error": "Invalid JSON"})
            return

        # Process via WhatsApp client
        if self.whatsapp_client:
            messages = self.whatsapp_client.process_webhook_payload(payload)
            for msg in messages:
                if self.message_callback:
                    try:
                        self.message_callback(
                            msg["sender"], msg["body"], msg
                        )
                    except Exception:
                        logger.exception("Error in webhook message callback")

        self._respond(200, {"status": "ok"})

    def _respond(self, code: int, body: dict[str, Any]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def _respond_text(self, code: int, text: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Redirect HTTP server logs to the logger."""
        logger.debug(format, *args)


class WebhookServer:
    """Manages the webhook HTTP server lifecycle.

    Runs the server in a background thread so it doesn't block
    the main agent loop.
    """

    def __init__(
        self,
        whatsapp_client: WhatsAppClient,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        webhook_path: str = "/webhook",
        message_callback: Callable[[str, str, dict], None] | None = None,
    ) -> None:
        self.whatsapp_client = whatsapp_client
        self.host = host
        self.port = port
        self.webhook_path = webhook_path
        self.message_callback = message_callback
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the webhook server in a background thread."""
        # Configure the handler class
        handler_class = type(
            "ConfiguredWebhookHandler",
            (WebhookHandler,),
            {
                "whatsapp_client": self.whatsapp_client,
                "message_callback": self.message_callback,
                "webhook_path": self.webhook_path,
                "verify_token": self.whatsapp_client.config.verify_token,
            },
        )

        self._server = HTTPServer((self.host, self.port), handler_class)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="whatsapp-webhook",
        )
        self._thread.start()
        logger.info(
            "WhatsApp webhook server started on %s:%s%s",
            self.host,
            self.port,
            self.webhook_path,
        )

    def stop(self) -> None:
        """Shut down the webhook server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("WhatsApp webhook server stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

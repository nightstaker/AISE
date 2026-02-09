"""Tests for the WhatsApp webhook server."""

import json
from http.server import HTTPServer
from unittest.mock import MagicMock

from aise.whatsapp.client import WhatsAppClient, WhatsAppConfig
from aise.whatsapp.webhook import WebhookHandler, WebhookServer


class TestWebhookServer:
    def test_creation(self):
        config = WhatsAppConfig(verify_token="test_token")
        client = WhatsAppClient(config)
        server = WebhookServer(client, port=9999)
        assert not server.is_running
        assert server.port == 9999

    def test_start_stop(self):
        config = WhatsAppConfig(verify_token="test_token")
        client = WhatsAppClient(config)
        server = WebhookServer(client, port=0)  # port 0 = OS picks available
        server.start()
        assert server.is_running
        server.stop()
        assert not server.is_running

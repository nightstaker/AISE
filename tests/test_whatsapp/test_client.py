"""Tests for the WhatsApp Business API client."""

from aise.whatsapp.client import WhatsAppClient, WhatsAppConfig


class TestWhatsAppConfig:
    def test_defaults(self):
        config = WhatsAppConfig()
        assert not config.is_configured
        assert config.webhook_port == 8080

    def test_configured(self):
        config = WhatsAppConfig(phone_number_id="123", access_token="token")
        assert config.is_configured


class TestWhatsAppClient:
    def test_verify_webhook_success(self):
        config = WhatsAppConfig(verify_token="my_token")
        client = WhatsAppClient(config)
        result = client.verify_webhook("subscribe", "my_token", "challenge_123")
        assert result == "challenge_123"

    def test_verify_webhook_failure(self):
        config = WhatsAppConfig(verify_token="my_token")
        client = WhatsAppClient(config)
        result = client.verify_webhook("subscribe", "wrong_token", "challenge")
        assert result is None

    def test_verify_webhook_wrong_mode(self):
        config = WhatsAppConfig(verify_token="my_token")
        client = WhatsAppClient(config)
        result = client.verify_webhook("unsubscribe", "my_token", "challenge")
        assert result is None

    def test_on_message_callback(self):
        config = WhatsAppConfig()
        client = WhatsAppClient(config)
        received = []
        client.on_message(lambda s, b, r: received.append((s, b)))

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"wa_id": "123", "profile": {"name": "Alice"}}],
                        "messages": [{
                            "from": "123",
                            "id": "msg_1",
                            "timestamp": "1234567890",
                            "type": "text",
                            "text": {"body": "Hello"},
                        }],
                    }
                }]
            }]
        }
        messages = client.process_webhook_payload(payload)
        assert len(messages) == 1
        assert messages[0]["sender"] == "123"
        assert messages[0]["sender_name"] == "Alice"
        assert messages[0]["body"] == "Hello"
        assert len(received) == 1

    def test_process_empty_payload(self):
        client = WhatsAppClient(WhatsAppConfig())
        assert client.process_webhook_payload({}) == []
        assert client.process_webhook_payload({"entry": []}) == []

    def test_process_payload_no_messages(self):
        client = WhatsAppClient(WhatsAppConfig())
        payload = {"entry": [{"changes": [{"value": {"statuses": []}}]}]}
        assert client.process_webhook_payload(payload) == []

    def test_interactive_message(self):
        client = WhatsAppClient(WhatsAppConfig())
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"wa_id": "123", "profile": {"name": "Bob"}}],
                        "messages": [{
                            "from": "123",
                            "id": "msg_2",
                            "timestamp": "1234567890",
                            "type": "interactive",
                            "interactive": {
                                "button_reply": {"title": "Yes"}
                            },
                        }],
                    }
                }]
            }]
        }
        messages = client.process_webhook_payload(payload)
        assert len(messages) == 1
        assert messages[0]["body"] == "Yes"
        assert messages[0]["type"] == "interactive"

"""WhatsApp Business Cloud API client.

Uses Meta's WhatsApp Business Cloud API to send and receive messages
in group chats. This client handles authentication, message sending,
and group management via the Graph API.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


@dataclass
class WhatsAppConfig:
    """Configuration for WhatsApp Business API integration."""

    phone_number_id: str = ""
    access_token: str = ""
    verify_token: str = ""
    business_account_id: str = ""
    webhook_port: int = 8080
    webhook_path: str = "/webhook"
    api_base_url: str = _GRAPH_API_BASE

    @property
    def is_configured(self) -> bool:
        return bool(self.phone_number_id and self.access_token)


class WhatsAppClient:
    """Client for the WhatsApp Business Cloud API.

    Handles sending text messages, managing group metadata,
    and interacting with the Graph API endpoints.
    """

    def __init__(self, config: WhatsAppConfig) -> None:
        self.config = config
        self._message_callbacks: list = []

    def send_text_message(self, to: str, text: str) -> dict[str, Any]:
        """Send a text message to a WhatsApp number or group.

        Args:
            to: Recipient phone number or group JID.
            text: Message body text.

        Returns:
            API response dict with message ID on success.
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return self._api_post(
            f"/{self.config.phone_number_id}/messages",
            payload,
        )

    def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str = "en_US",
        components: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Send a template message.

        Args:
            to: Recipient phone number.
            template_name: Pre-approved template name.
            language_code: Template language code.
            components: Template components (header, body, buttons).

        Returns:
            API response dict.
        """
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components
        return self._api_post(
            f"/{self.config.phone_number_id}/messages",
            payload,
        )

    def mark_as_read(self, message_id: str) -> dict[str, Any]:
        """Mark a message as read.

        Args:
            message_id: The WhatsApp message ID to mark as read.

        Returns:
            API response dict.
        """
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        return self._api_post(
            f"/{self.config.phone_number_id}/messages",
            payload,
        )

    def get_media_url(self, media_id: str) -> str:
        """Get the download URL for a media attachment.

        Args:
            media_id: The media ID from a received message.

        Returns:
            Download URL string.
        """
        result = self._api_get(f"/{media_id}")
        return result.get("url", "")

    def on_message(self, callback) -> None:
        """Register a callback for incoming messages.

        Args:
            callback: Function(sender, message_body, raw_message) to call.
        """
        self._message_callbacks.append(callback)

    def process_webhook_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Process an incoming webhook payload and extract messages.

        Args:
            payload: The parsed JSON body from the webhook POST.

        Returns:
            List of extracted message dicts with keys:
            sender, message_id, timestamp, type, body, raw.
        """
        messages = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if "messages" not in value:
                    continue
                contacts = {
                    c["wa_id"]: c.get("profile", {}).get("name", c["wa_id"])
                    for c in value.get("contacts", [])
                }
                for msg in value["messages"]:
                    sender_id = msg.get("from", "")
                    extracted = {
                        "sender": sender_id,
                        "sender_name": contacts.get(sender_id, sender_id),
                        "message_id": msg.get("id", ""),
                        "timestamp": msg.get("timestamp", ""),
                        "type": msg.get("type", "text"),
                        "body": "",
                        "raw": msg,
                    }
                    if msg.get("type") == "text":
                        extracted["body"] = msg.get("text", {}).get("body", "")
                    elif msg.get("type") == "interactive":
                        interactive = msg.get("interactive", {})
                        extracted["body"] = interactive.get("button_reply", {}).get(
                            "title", ""
                        ) or interactive.get("list_reply", {}).get("title", "")
                    messages.append(extracted)

                    # Notify registered callbacks
                    for cb in self._message_callbacks:
                        try:
                            cb(extracted["sender"], extracted["body"], extracted)
                        except Exception:
                            logger.exception("Error in message callback")

        return messages

    def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        """Verify the webhook subscription from Meta.

        Args:
            mode: The hub.mode parameter (should be 'subscribe').
            token: The hub.verify_token parameter.
            challenge: The hub.challenge parameter.

        Returns:
            The challenge string if verified, None otherwise.
        """
        if mode == "subscribe" and token == self.config.verify_token:
            logger.info("Webhook verification successful")
            return challenge
        logger.warning("Webhook verification failed: mode=%s", mode)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_post(self, endpoint: str, payload: dict) -> dict[str, Any]:
        """Make a POST request to the Graph API."""
        url = f"{self.config.api_base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error("WhatsApp API error %s: %s", e.code, body)
            return {"error": {"code": e.code, "message": body}}
        except urllib.error.URLError as e:
            logger.error("WhatsApp API connection error: %s", e.reason)
            return {"error": {"message": str(e.reason)}}

    def _api_get(self, endpoint: str) -> dict[str, Any]:
        """Make a GET request to the Graph API."""
        url = f"{self.config.api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error("WhatsApp API error %s: %s", e.code, body)
            return {"error": {"code": e.code, "message": body}}
        except urllib.error.URLError as e:
            logger.error("WhatsApp API connection error: %s", e.reason)
            return {"error": {"message": str(e.reason)}}

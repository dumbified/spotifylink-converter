"""Send WhatsApp messages through Meta's official Cloud API.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import httpx

# WhatsApp refuses text messages longer than this.
MAX_MESSAGE_LENGTH = 4096


class WhatsAppError(Exception):
    """Meta did not accept the message."""


class WhatsAppClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v24.0",
    ) -> None:
        self._http = http
        self._access_token = access_token
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"

    async def send_text(self, to: str, body: str) -> None:
        """Send a plain text message to a phone number (digits only)."""
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            # preview_url asks WhatsApp to show a preview card for the link.
            "text": {"body": body[:MAX_MESSAGE_LENGTH], "preview_url": True},
        }
        # The token goes in a header, never in the URL: URLs end up in logs.
        headers = {"Authorization": f"Bearer {self._access_token}"}

        try:
            response = await self._http.post(self._url, json=payload, headers=headers)
        except httpx.HTTPError as error:
            raise WhatsAppError(f"Could not reach Meta: {type(error).__name__}") from error

        if response.status_code != 200:
            # Meta's error text explains what went wrong (expired token,
            # recipient not on the allowed list...). It never contains our token.
            raise WhatsAppError(
                f"Meta answered with status {response.status_code}: {response.text[:300]}"
            )

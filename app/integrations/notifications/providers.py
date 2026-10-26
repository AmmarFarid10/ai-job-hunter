import base64
import json
import stat
from email.message import EmailMessage
from typing import Any

import httpx
from starlette.concurrency import run_in_threadpool

from app.config import Settings


class DeliveryError(Exception):
    def __init__(self, code: str, *, uncertain: bool = False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


async def gmail_access_token(settings: Settings, client: httpx.AsyncClient) -> str:
    path = settings.gmail_send_token_file
    if path is None:
        raise DeliveryError("GMAIL_NOT_CONFIGURED")
    try:

        def read_credentials() -> str:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 65536:
                raise ValueError("OAuth file must be private and bounded")
            return path.read_text()

        raw = await run_in_threadpool(read_credentials)
        credentials: dict[str, Any] = json.loads(raw)
        # Dedicated authorized-user file; never send credentials to a configurable URL.
        if not all(credentials.get(key) for key in ["client_id", "client_secret", "refresh_token"]):
            raise ValueError("Missing OAuth refresh credentials")
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "refresh_token": credentials["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if response.status_code != 200:
            raise DeliveryError("GMAIL_AUTH_FAILED")
        token = response.json()["access_token"]
        if not isinstance(token, str) or not token:
            raise ValueError("Invalid token")
        return token
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        raise DeliveryError("GMAIL_AUTH_FAILED") from exc


async def send_report(
    settings: Settings, channel: str, recipient: str, subject: str, text: str, report_url: str
) -> tuple[str, str]:
    if settings.notification_mode == "mock":
        return "MOCKED", "mock-development-only"
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        if channel == "email":
            token = await gmail_access_token(settings, client)
            if not settings.gmail_sender_email:
                raise DeliveryError("GMAIL_SENDER_NOT_CONFIGURED")
            message = EmailMessage()
            message["From"] = settings.gmail_sender_email
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(text)
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
            headers = {"Authorization": f"Bearer {token}"}
            payload: dict[str, Any] = {"raw": raw}
        else:
            if not all(
                [
                    settings.whatsapp_access_token,
                    settings.whatsapp_phone_number_id,
                    settings.whatsapp_graph_version,
                    settings.whatsapp_template_name,
                ]
            ):
                raise DeliveryError("WHATSAPP_NOT_CONFIGURED")
            assert settings.whatsapp_access_token is not None
            url = (
                f"https://graph.facebook.com/{settings.whatsapp_graph_version}/"
                f"{settings.whatsapp_phone_number_id}/messages"
            )
            headers = {
                "Authorization": f"Bearer {settings.whatsapp_access_token.get_secret_value()}"
            }
            # Approved business-initiated template with two body parameters: title, report link.
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient.lstrip("+"),
                "type": "template",
                "template": {
                    "name": settings.whatsapp_template_name,
                    "language": {"code": settings.whatsapp_template_language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": " ".join(text.split())[:900]},
                                {"type": "text", "text": report_url},
                            ],
                        }
                    ],
                },
            }
        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise DeliveryError("PROVIDER_OUTCOME_UNKNOWN", uncertain=True) from exc
        if not response.is_success:
            raise DeliveryError(
                "PROVIDER_REJECTED" if response.status_code < 500 else "PROVIDER_OUTCOME_UNKNOWN",
                uncertain=response.status_code >= 500,
            )
        try:
            reference = (
                response.json()["id"]
                if channel == "email"
                else response.json()["messages"][0]["id"]
            )
            if not isinstance(reference, str) or not reference:
                raise ValueError("Invalid provider reference")
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise DeliveryError("PROVIDER_OUTCOME_UNKNOWN", uncertain=True) from exc
        # SENT means accepted by provider, not proof of arrival/read on the recipient's device.
        return "SENT", reference[:200]

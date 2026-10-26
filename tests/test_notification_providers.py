import base64
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.integrations.notifications.providers import DeliveryError, send_report


def settings(**kwargs) -> Settings:
    return Settings(api_key="test-notification-key-thirty-two-characters", **kwargs)


async def test_mock_delivery_never_opens_network(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("Network opened for mock delivery")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected)
    assert (
        await send_report(
            settings(notification_mode="mock"),
            "email",
            "unused",
            "subject",
            "body",
            "https://example.com",
        )
    )[0] == "MOCKED"


async def test_gmail_refresh_and_mime_send(tmp_path: Path, monkeypatch):
    file = tmp_path / "oauth.json"
    file.write_text(
        json.dumps({"client_id": "demo", "client_secret": "secret", "refresh_token": "refresh"})
    )
    file.chmod(0o600)
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "oauth-access"})
        assert str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        assert request.headers["Authorization"] == "Bearer oauth-access"
        message = BytesParser(policy=policy.default).parsebytes(
            base64.urlsafe_b64decode(json.loads(request.content)["raw"])
        )
        assert message["To"] == "owner@example.com" and message["From"] == "sender@example.com"
        assert "Private report" in message.get_content()
        return httpx.Response(200, json={"id": "gmail-message-id"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    result = await send_report(
        settings(
            notification_mode="live",
            gmail_send_token_file=file,
            gmail_sender_email="sender@example.com",
        ),
        "email",
        "owner@example.com",
        "Job report",
        "Private report",
        "https://example.com",
    )
    assert result == ("SENT", "gmail-message-id") and len(requests) == 2


async def test_whatsapp_uses_official_template_api(monkeypatch):
    def handle(request):
        assert str(request.url) == "https://graph.facebook.com/v99.0/123/messages"
        body = json.loads(request.content)
        assert body["to"] == "923001234567"
        assert body["type"] == "template" and body["template"]["name"] == "job_report"
        assert (
            body["template"]["components"][0]["parameters"][1]["text"]
            == "https://example.com/report"
        )
        return httpx.Response(200, json={"messages": [{"id": "wa-message-id"}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    result = await send_report(
        settings(
            notification_mode="live",
            whatsapp_access_token=SecretStr("token"),
            whatsapp_phone_number_id="123",
            whatsapp_graph_version="v99.0",
            whatsapp_template_name="job_report",
        ),
        "whatsapp",
        "+923001234567",
        "Report",
        "Python Engineer at Example, score 90",
        "https://example.com/report",
    )
    assert result == ("SENT", "wa-message-id")


@pytest.mark.parametrize("status,uncertain", [(400, False), (429, False), (500, True), (503, True)])
async def test_provider_failures_are_classified_without_retry(monkeypatch, status, uncertain):
    calls = []

    def handle(request):
        calls.append(1)
        return httpx.Response(status, json={"error": "untrusted response with private data"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    with pytest.raises(DeliveryError) as error:
        await send_report(
            settings(
                notification_mode="live",
                whatsapp_access_token=SecretStr("token"),
                whatsapp_phone_number_id="123",
                whatsapp_graph_version="v99.0",
                whatsapp_template_name="job_report",
            ),
            "whatsapp",
            "+923001234567",
            "Report",
            "body",
            "https://example.com",
        )
    assert error.value.uncertain is uncertain and len(calls) == 1
    assert "private data" not in str(error.value)


async def test_oauth_file_requires_private_permissions(tmp_path: Path):
    path = tmp_path / "oauth.json"
    path.write_text('{"refresh_token":"secret"}')
    path.chmod(0o644)
    with pytest.raises(DeliveryError, match="GMAIL_AUTH_FAILED"):
        await send_report(
            settings(notification_mode="live", gmail_send_token_file=path),
            "email",
            "owner@example.com",
            "Report",
            "body",
            "https://example.com",
        )

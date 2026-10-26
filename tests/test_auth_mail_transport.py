import smtplib

import pytest

from app.config import Settings
from app.integrations.auth_mail import AuthMailError, send_auth_email


async def test_auth_mail_requires_verified_tls_before_login_and_contains_only_action_link(
    monkeypatch,
):
    calls = []
    messages = []

    class Client:
        def __init__(self, *args, **kwargs):
            calls.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, context):
            assert context.check_hostname
            calls.append("tls")

        def login(self, user, password):
            assert password == "fictional-smtp-secret"
            calls.append("login")

        def send_message(self, message):
            messages.append(message)
            calls.append("send")

    monkeypatch.setattr(smtplib, "SMTP", Client)
    settings = Settings(
        api_key="fictional-api-key-at-least-thirty-two-characters",
        smtp_host="smtp.provider.test",
        smtp_username="user",
        smtp_password="fictional-smtp-secret",
        auth_sender_email="sender@example.com",
    )
    await send_auth_email(
        settings,
        "recipient@example.com",
        "reset",
        "https://jobs.example.com/#reset=fictional-token",
    )
    assert calls == ["connect", "tls", "login", "send"]
    assert "#reset=fictional-token" in messages[0].get_content()
    assert "fictional-smtp-secret" not in messages[0].as_string()


async def test_smtp_failure_is_redacted_and_no_cleartext_fallback(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPAuthenticationError(535, b"private-secret-from-provider")

    monkeypatch.setattr(smtplib, "SMTP", Client)
    settings = Settings(
        api_key="fictional-api-key-at-least-thirty-two-characters",
        smtp_host="smtp.provider.test",
        auth_sender_email="sender@example.com",
    )
    with pytest.raises(AuthMailError) as result:
        await send_auth_email(
            settings, "recipient@example.com", "verify", "https://example.com/#verify=token"
        )
    assert "private-secret" not in str(result.value)

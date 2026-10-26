"""Authentication email transport. Never log links, tokens, recipients or SMTP errors."""

import smtplib
import ssl
from email.message import EmailMessage

from starlette.concurrency import run_in_threadpool

from app.config import Settings


class AuthMailError(Exception):
    pass


def _send(settings: Settings, recipient: str, purpose: str, link: str) -> None:
    if not settings.smtp_host or not settings.auth_sender_email:
        raise AuthMailError("AUTH_MAIL_NOT_CONFIGURED")
    message = EmailMessage()
    message["From"] = settings.auth_sender_email
    message["To"] = recipient
    message["Subject"] = "Verify your email" if purpose == "verify" else "Reset your password"
    message.set_content(
        (
            "Verify your Job Hunter email address"
            if purpose == "verify"
            else "Reset your Job Hunter password"
        )
        + f" using this one-time link:\n\n{link}\n\n"
        + "If you did not request this, ignore this email. Do not share the link."
    )
    context = ssl.create_default_context()
    try:
        client = (
            smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
            if settings.smtp_tls == "ssl"
            else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        )
        with client:
            if settings.smtp_tls == "starttls":
                client.starttls(context=context)
            if settings.smtp_username:
                client.login(
                    settings.smtp_username,
                    settings.smtp_password.get_secret_value() if settings.smtp_password else "",
                )
            client.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise AuthMailError("AUTH_MAIL_DELIVERY_FAILED") from None


async def send_auth_email(settings: Settings, recipient: str, purpose: str, link: str) -> None:
    await run_in_threadpool(_send, settings, recipient, purpose, link)

import base64
import binascii
import json
import re
import stat
from email import policy
from email.message import EmailMessage
from email.parser import Parser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pydantic import SecretStr, ValidationError

from app.domain.discovery import DiscoveryQuery, ProviderBatch
from app.integrations.discovery.base import ProviderError
from app.integrations.discovery.http import SafeHTTP
from app.integrations.discovery.parsing import linkedin_listing


class AlertLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.url: str | None = None
        self.label: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.url = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data: str) -> None:
        if self.url:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.url:
            self.links.append((self.url, " ".join(self.label)))
            self.url = None


def parse_alert(raw_email: str, limit: int = 100) -> ProviderBatch:
    message: EmailMessage = Parser(policy=policy.default).parsestr(raw_email)
    batch = ProviderBatch(warnings=["ALERT_LINKS_REQUIRE_REVIEW"])
    # A sender header is not proof of authenticity; only exact LinkedIn job URLs are accepted.
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/html", "text/plain"}:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError):
            batch.rejected += 1
            continue
        if not isinstance(content, str):
            continue
        links: list[tuple[str, str]]
        if content_type == "text/html":
            parser = AlertLinks()
            parser.feed(content)
            links = parser.links
        else:
            links = [
                (match, "LinkedIn job alert")
                for match in re.findall(
                    r"https://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/[^\s<>\"]+", content
                )
            ]
        for url, label in links[:1000]:
            url = url.rstrip(".,);]")
            try:
                item = linkedin_listing(url, label)
            except (ValueError, ValidationError):
                item = None
            if item is None or not item.linkedin_job_id:
                continue
            if all(existing.external_id != item.external_id for existing in batch.items):
                batch.items.append(item)
            if len(batch.items) >= limit:
                batch.warnings.append("ITEM_LIMIT_REACHED")
                return batch
    return batch


class GmailAlertProvider:
    def __init__(
        self,
        http: SafeHTTP,
        token_file: Path | None,
        query: str = (
            "from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com) newer_than:14d"
        ),
    ) -> None:
        self.http, self.token_file, self.query = http, token_file, query

    def credentials(self) -> dict[str, str]:
        if self.token_file is None:
            raise ProviderError("GMAIL_TOKEN_NOT_CONFIGURED")
        try:
            if self.token_file.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ProviderError("GMAIL_TOKEN_FILE_MUST_BE_PRIVATE")
            if self.token_file.stat().st_size > 65536:
                raise ProviderError("INVALID_GMAIL_CREDENTIALS")
            data = json.loads(self.token_file.read_text())
            result = {key: data[key] for key in ["client_id", "client_secret", "refresh_token"]}
            if not all(isinstance(value, str) and value for value in result.values()):
                raise ValueError("missing credentials")
            return result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError("INVALID_GMAIL_CREDENTIALS") from exc

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        credentials = self.credentials()
        token_data = await self.http.json(
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                **credentials,
                "grant_type": "refresh_token",
            },
        )
        if not isinstance(token_data, dict) or not token_data.get("access_token"):
            raise ProviderError("GMAIL_AUTH_FAILED")
        access_token = SecretStr(str(token_data["access_token"]))
        headers = {"Authorization": f"Bearer {access_token.get_secret_value()}"}
        batch = ProviderBatch()
        page_token = None
        # Only this configured alert query is read. Never mark, modify, delete or send mail.
        for _ in range(3):
            params: dict[str, str | int] = {"q": self.query, "maxResults": min(25, query.max_items)}
            if page_token:
                params["pageToken"] = str(page_token)
            data = await self.http.json(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                params=params,
                headers=headers,
            )
            if not isinstance(data, dict):
                raise ProviderError("INVALID_GMAIL_RESPONSE")
            for message in data.get("messages", []):
                message_id = str(message.get("id", "")) if isinstance(message, dict) else ""
                if not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", message_id):
                    batch.rejected += 1
                    continue
                payload: Any = await self.http.json(
                    "GET",
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                    params={"format": "raw"},
                    headers=headers,
                )
                try:
                    encoded = payload["raw"]
                    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                    if len(raw) > 1000000:
                        raise ValueError("message too large")
                    parsed = parse_alert(raw.decode("utf-8", errors="replace"), query.max_items)
                except (KeyError, ValueError, TypeError, binascii.Error):
                    batch.rejected += 1
                    continue
                for item in parsed.items:
                    if all(existing.external_id != item.external_id for existing in batch.items):
                        batch.items.append(item)
                    if len(batch.items) >= query.max_items:
                        batch.warnings.append("ITEM_LIMIT_REACHED")
                        return batch
                batch.rejected += parsed.rejected
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        else:
            batch.warnings.append("PAGE_LIMIT_REACHED")
        return batch


class ImportedEmailProvider:
    def __init__(self, raw_email: str) -> None:
        self.raw_email = raw_email

    async def collect(self, query: DiscoveryQuery) -> ProviderBatch:
        return parse_alert(self.raw_email, query.max_items)

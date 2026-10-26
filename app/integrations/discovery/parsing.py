import hashlib
import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from app.domain.discovery import Listing
from app.domain.identity import canonical_url, is_linkedin_host


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = TextParser()
    parser.feed(html.unescape(value))
    return "\n".join(
        " ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip()
    )


def linkedin_id(url: str) -> str | None:
    parts = urlsplit(url)
    if not is_linkedin_host(parts.hostname or ""):
        return None
    match = re.search(r"/jobs/view/(?:[^/]*-)?(\d{1,30})/?$", parts.path)
    return match.group(1) if match else None


def linkedin_listing(url: str, label: str, description: str = "") -> Listing | None:
    parts = urlsplit(url)
    if not is_linkedin_host(parts.hostname or ""):
        return None
    jid = linkedin_id(url)
    if not jid and not (parts.path.startswith("/posts/") or parts.path.startswith("/feed/update/")):
        return None
    title = plain_text(label).removesuffix(" | LinkedIn").strip()[:300] or "LinkedIn opportunity"
    company = None
    # Only explicit employer/role delimiters qualify; ambiguous snippets stay in review.
    match = re.fullmatch(r"(.+?) hiring (.+?)(?: in (.+))?", title, re.I) if jid else None
    location = None
    if match:
        company, title, location = match.groups()
    canonical = canonical_url(url)
    external = jid or hashlib.sha256((canonical + "|" + title).encode()).hexdigest()
    return Listing(
        external_id=external,
        title=title[:300],
        company=company,
        description=plain_text(description)[:200000],
        source_url=canonical,
        application_url=canonical if jid else None,
        linkedin_job_id=jid,
        location=location,
        requires_review=True,
    )


class LinkedDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capturing = False
        self.current: list[str] = []
        self.documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and (dict(attrs).get("type") or "").lower() == "application/ld+json":
            self.capturing = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.capturing:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.capturing:
            self.documents.append("".join(self.current))
            self.capturing = False


def job_postings(page: str) -> list[dict[str, Any]]:
    parser = LinkedDataParser()
    parser.feed(page)
    jobs: list[dict[str, Any]] = []
    for document in parser.documents[:100]:
        try:
            data = json.loads(document)
        except (ValueError, RecursionError):
            continue
        queue = [data]
        visited = 0
        while queue and visited < 1000:
            node = queue.pop()
            visited += 1
            if isinstance(node, list):
                queue.extend(node[:1000])
            elif isinstance(node, dict):
                types = node.get("@type", [])
                if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
                    jobs.append(node)
                graph = node.get("@graph")
                if graph is not None:
                    queue.append(graph)
    return jobs

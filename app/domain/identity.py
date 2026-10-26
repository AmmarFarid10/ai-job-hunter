import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING = {"fbclid", "gclid", "ref", "refid", "trk", "trackingid", "source"}


def normalize(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("A valid HTTP(S) URL is required")
    if parts.username or parts.password:
        raise ValueError("Credentials are not allowed in URLs")
    host = parts.hostname.lower().removeprefix("www.")
    port = parts.port
    if port and (parts.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    query = sorted(
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING
    )
    return urlunsplit(
        (parts.scheme.lower(), host, parts.path.rstrip("/") or "/", urlencode(query), "")
    )


def fingerprint(description: str) -> str:
    text = " ".join(unicodedata.normalize("NFKC", description).casefold().split())
    return hashlib.sha256(text.encode()).hexdigest()


def digest_key(kind: str, value: str) -> str:
    return kind + ":" + hashlib.sha256(value.encode()).hexdigest()


def is_linkedin_host(host: str) -> bool:
    host = host.lower()
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def vacancy_url(value: str) -> bool:
    """Shared landing pages and hiring posts cannot identify one vacancy."""
    parts = urlsplit(value)
    path = parts.path.rstrip("/").lower()
    if is_linkedin_host(parts.hostname or ""):
        return bool(re.search(r"/jobs/view/(?:[^/]*-)?\d+$", path))
    if path in {"", "/careers", "/career", "/jobs", "/apply", "/openings", "/positions"}:
        parameters = {key.lower() for key, _ in parse_qsl(parts.query)}
        return bool(parameters & {"job", "jobid", "job_id", "gh_jid", "requisitionid"})
    return True


def identity_keys(
    *,
    company: str,
    title: str,
    description: str,
    source_url: str,
    application_url: str | None = None,
    employer_job_id: str | None = None,
    linkedin_job_id: str | None = None,
) -> list[str]:
    keys = [digest_key("source", canonical_url(source_url))] if vacancy_url(source_url) else []
    if application_url and vacancy_url(application_url):
        keys.append(digest_key("application", canonical_url(application_url)))
    if employer_job_id:
        keys.append(digest_key("employer", normalize(company) + "|" + employer_job_id.strip()))
    # LinkedIn job-view URLs carry a stable vacancy ID, without scraping the page.
    for url in [source_url, application_url]:
        if url:
            parts = urlsplit(url)
            if is_linkedin_host(parts.hostname or ""):
                match = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)/?$", parts.path)
                if match:
                    keys.append(digest_key("linkedin", match.group(1)))
    if linkedin_job_id:
        keys.append(digest_key("linkedin", linkedin_job_id.strip()))
    return sorted(set(keys))

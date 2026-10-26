"""Conservative posting-date evidence; crawl/update timestamps are not posting dates."""

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

MAX_POSTING_AGE = timedelta(days=7)


def parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 100:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    result = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    pass
            else:
                return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def posting_date(row: dict[str, Any], text: str, now: datetime) -> tuple[datetime | None, str]:
    # Explicit posting text takes priority over provider metadata (which can mean updated).
    text = text[:200000]
    relative = re.search(
        r"\b(?:posted|reposted)\s+(?:(?:on|about)\s+)?(\d{1,4})\+?\s+"
        r"(minute|hour|day|week|month|year)s?\s+ago\b",
        text,
        re.I,
    ) or re.match(r"\s*(\d{1,4})\+?\s+(minute|hour|day|week|month|year)s?\s+ago\b", text, re.I)
    if relative:
        amount, unit = int(relative[1]), relative[2].lower()
        seconds = {
            "minute": 60,
            "hour": 3600,
            "day": 86400,
            "week": 604800,
            "month": 2592000,
            "year": 31536000,
        }[unit]
        age = timedelta(seconds=amount * seconds)
        if "+" in relative[0] or age > MAX_POSTING_AGE:
            return None, relative[0].strip()
        return now - age, relative[0].strip()
    absolute = re.search(
        r"\b(?:posted|reposted)\s+(?:on\s+)?"
        r"(\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\b",
        text,
        re.I,
    )
    if absolute:
        return parse_date(absolute[1]), absolute[0]
    for key in ("datePosted", "date_posted"):
        if key in row:
            return parse_date(row[key]), key
    # published_date/page_age/age can be a page update or crawl date. Do not infer posting.
    return None, ""


def recent_posting(posted: datetime | None, now: datetime) -> bool:
    return posted is not None and now - MAX_POSTING_AGE <= posted <= now

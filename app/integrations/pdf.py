import re
from typing import Any

import pymupdf

KNOWN_SKILLS = [
    "Python",
    "FastAPI",
    "Django",
    "Flask",
    "MongoDB",
    "MSSQL",
    "Redis",
    "RabbitMQ",
    "Docker",
    "Kubernetes",
    "Azure",
    "LangGraph",
    "OpenAI",
    "PostgreSQL",
    "TypeScript",
    "LLM",
]


def extract_pdf(content: bytes) -> tuple[str, dict[str, Any], list[str]]:
    if not content.startswith(b"%PDF-"):
        raise ValueError("File is not a PDF")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:  # type: ignore[no-untyped-call]
            if document.needs_pass:
                raise ValueError("Encrypted PDFs are unsupported")
            if not 1 <= document.page_count <= 100:
                raise ValueError("PDF must contain between 1 and 100 pages")
            chunks: list[str] = []
            length = 0
            for page in document:
                text = page.get_text()
                length += len(text)
                if length > 500000:
                    raise ValueError("PDF text exceeds the extraction limit")
                chunks.append(text)
            text = "\n".join(chunks).strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF could not be parsed") from exc
    warnings = [
        "All extracted suggestions are unverified; confirm each fact before saving.",
        "Employers, employment dates, education and achievements require manual entry/review.",
        "Check missing dates, overlapping employment and inconsistent claims against the PDF.",
    ]
    if not text:
        warnings.append("No extractable text; scanned PDFs require OCR, unavailable in Phase 1.")
    skills = [
        skill
        for skill in KNOWN_SKILLS
        if re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", text, re.I)
    ]
    emails = sorted(set(re.findall(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", text)))
    return (
        text,
        {"skills": skills, "emails": emails, "verified": False, "experiences": [], "education": []},
        warnings,
    )

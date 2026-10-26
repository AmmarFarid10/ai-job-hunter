import pymupdf
import pytest

from app.integrations.pdf import extract_pdf


def make_pdf(text: str = "Python FastAPI\nExample Candidate\nuser@example.com") -> bytes:
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), text)
        return doc.tobytes()


def test_extracts_unverified_suggestions() -> None:
    text, suggestions, warnings = extract_pdf(make_pdf())
    assert "Example Candidate" in text
    assert suggestions["skills"] == ["Python", "FastAPI"]
    assert suggestions["verified"] is False
    assert suggestions["experiences"] == []
    assert warnings


def test_scanned_document_warning() -> None:
    text, _, warnings = extract_pdf(make_pdf(""))
    assert not text
    assert any("OCR" in warning for warning in warnings)


@pytest.mark.parametrize("content", [b"not a pdf", b"%PDF-invalid"])
def test_bad_pdf(content: bytes) -> None:
    with pytest.raises(ValueError):
        extract_pdf(content)

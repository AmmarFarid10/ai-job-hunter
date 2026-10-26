# mypy: disable-error-code="no-untyped-call"
import pymupdf


def preview_page(content: bytes, page: int) -> bytes:
    with pymupdf.open(stream=content, filetype="pdf") as document:
        if not 1 <= page <= min(len(document), 30):
            raise IndexError("Preview page not found")
        return bytes(
            document[page - 1]
            .get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3), alpha=False)
            .tobytes("png")
        )

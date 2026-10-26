import hashlib
import os
import uuid
from pathlib import Path

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


class ArtifactError(ValueError):
    pass


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def secure_path(root: Path, key: str) -> Path:
    base = root.resolve()
    if Path(key).is_absolute():
        raise ArtifactError("Invalid artifact path")
    path = (base / key).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ArtifactError("Invalid artifact path")
    return path


def write_artifacts(root: Path, version_id: uuid.UUID, docx: bytes, pdf: bytes) -> tuple[str, str]:
    if max(len(docx), len(pdf)) > MAX_ARTIFACT_BYTES:
        raise ArtifactError("Artifact exceeds storage limit")
    base = root.resolve()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = secure_path(root, f"tailored/{version_id.hex}")
    folder.parent.mkdir(mode=0o700, exist_ok=True)
    folder.mkdir(mode=0o700, exist_ok=False)
    written: list[Path] = []
    try:
        for name, content in [("resume.docx", docx), ("resume.pdf", pdf)]:
            target = folder / name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            written.append(target)
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        folder.rmdir()
        raise
    return f"tailored/{version_id.hex}/resume.docx", f"tailored/{version_id.hex}/resume.pdf"


def remove_artifacts(root: Path, keys: tuple[str, str]) -> None:
    for key in keys:
        secure_path(root, key).unlink(missing_ok=True)
    folder = secure_path(root, keys[0]).parent
    try:
        folder.rmdir()
    except OSError:
        pass


def read_artifact(root: Path, key: str, expected_hash: str) -> bytes:
    path = secure_path(root, key)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            data = source.read(MAX_ARTIFACT_BYTES + 1)
    except OSError as exc:
        raise ArtifactError("Artifact missing or unreadable") from exc
    if len(data) > MAX_ARTIFACT_BYTES or digest(data) != expected_hash:
        raise ArtifactError("Artifact integrity check failed")
    return data

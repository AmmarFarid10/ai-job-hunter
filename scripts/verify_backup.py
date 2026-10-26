"""Verify a backup before restoration. Never extract untrusted archive paths or print content."""

import hashlib
import json
import sys
import tarfile
from pathlib import Path


def verify(root: Path) -> None:
    expected = json.loads((root / "manifest.json").read_text())
    for name in ("database.dump", "artifacts.tar.gz"):
        if hashlib.file_digest((root / name).open("rb"), "sha256").hexdigest() != expected.get(
            name
        ):
            raise ValueError("Backup checksum mismatch")
    with tarfile.open(root / "artifacts.tar.gz", "r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or member.issym()
                or member.islnk()
                or member.isdev()
            ):
                raise ValueError("Unsafe artifact archive entry")
    print("PASS: backup checksums and artifact archive paths are valid")


if __name__ == "__main__":
    try:
        verify(Path(sys.argv[1]))
    except Exception:
        raise SystemExit("FAIL: backup verification failed; no data restored") from None

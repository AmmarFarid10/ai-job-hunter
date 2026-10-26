import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.release_bundle import source_files, validate
from scripts.verify_backup import verify


def fixture_backup(root: Path, name="safe/resume.pdf", link=False):
    (root / "database.dump").write_bytes(b"fictional-dump")
    with tarfile.open(root / "artifacts.tar.gz", "w:gz") as archive:
        entry = tarfile.TarInfo(name)
        if link:
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            archive.addfile(entry)
        else:
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"test"))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ("database.dump", "artifacts.tar.gz")
            }
        )
    )


def test_backup_verification_accepts_valid_snapshot_and_rejects_corruption(tmp_path):
    fixture_backup(tmp_path)
    verify(tmp_path)
    (tmp_path / "database.dump").write_bytes(b"changed")
    with pytest.raises(ValueError):
        verify(tmp_path)


@pytest.mark.parametrize(
    "name,link", [("../outside", False), ("/etc/passwd", False), ("safe-link", True)]
)
def test_backup_archive_paths_and_links_are_rejected(tmp_path, name, link):
    fixture_backup(tmp_path, name, link)
    with pytest.raises(ValueError):
        verify(tmp_path)


def test_release_bundle_excludes_env_uploads_and_dependencies_and_detects_leaks(tmp_path):
    for folder in ("app", "storage", "dashboard/node_modules", "dashboard/.next", "scripts"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    secret = "fictional-local-private-password"
    (tmp_path / ".env").write_text("ADMIN_PASSWORD=" + secret + "\n")
    (tmp_path / "app/main.py").write_text('print("safe code")')
    (tmp_path / "storage/private.pdf").write_bytes(b"private")
    (tmp_path / "dashboard/node_modules/private.js").write_text("private")
    (tmp_path / "dashboard/.next/private.js").write_text("private")
    (tmp_path / "README.md").write_text("Public documentation")
    files = source_files(tmp_path)
    assert {str(path.relative_to(tmp_path)) for path in files} == {"app/main.py", "README.md"}
    assert validate(files, tmp_path) == []
    (tmp_path / "README.md").write_text(secret)
    failures = validate(files, tmp_path)
    assert failures and secret not in "\n".join(failures)

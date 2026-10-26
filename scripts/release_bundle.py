"""Build a reviewed source-only GitHub upload archive. Never include the working .env/storage."""

import argparse
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = {
    ".gitignore",
    ".dockerignore",
    ".env.example",
    ".env.production.example",
    "AGENTS.md",
    "README.md",
    "ARCHITECTURE.md",
    "PROGRESS.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
    "alembic.ini",
    "Dockerfile",
    "compose.yaml",
    "compose.discovery.yaml",
    "compose.production.yaml",
    "discovery_sources.example.json",
}
TREES = {"app", "migrations", "scripts", "tests", "dashboard", "deploy", "docs", ".github"}
EXCLUDED = {
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
}
SENSITIVE = re.compile(
    r"tvly-[A-Za-z0-9_-]{20,}|GOCSPX-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{24,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)


def source_files(root: Path = ROOT) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if (
            not path.is_file()
            or path.is_symlink()
            or any(part in EXCLUDED for part in relative.parts)
        ):
            continue
        if relative.parts[0] not in TREES and str(relative) not in TOP:
            continue
        if path.suffix in {
            ".pdf",
            ".docx",
            ".png",
            ".jpg",
            ".zip",
            ".dump",
            ".pyc",
            ".tsbuildinfo",
            ".pem",
            ".key",
        }:
            continue
        if path.name.startswith(".env") and str(relative) not in TOP:
            continue
        files.append(path)
    return sorted(files)


def local_private_values(root: Path = ROOT) -> set[str]:
    from dotenv import dotenv_values

    values = set()
    for name in (".env", ".env.production"):
        if not (root / name).exists():
            continue
        for key, value in dotenv_values(root / name).items():
            if (
                value
                and len(value) >= 8
                and (
                    any(word in key for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))
                    or key == "ADMIN_EMAIL"
                )
            ):
                if not value.startswith(("replace-", "your-", "choose-")):
                    values.add(value)
    return values


def validate(files: list[Path], root: Path = ROOT) -> list[str]:
    private = local_private_values(root)
    failures = []
    for path in files:
        try:
            text = path.read_text()
        except UnicodeError:
            failures.append(f"Unexpected binary file: {path.relative_to(root)}")
            continue
        if SENSITIVE.search(text) or any(value in text for value in private):
            failures.append(f"Possible private value in: {path.relative_to(root)}")
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
        )
        for raw in result.stdout.decode().split("\0"):
            path = Path(raw)
            if not raw:
                continue
            if (
                (path.name.startswith(".env") and raw not in TOP)
                or path.parts[0] in {"storage", "secrets", "backups"}
                or path.suffix in {".pdf", ".docx", ".pem", ".key", ".dump"}
            ):
                failures.append(f"Private artifact is tracked by Git: {raw}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = source_files()
    failures = validate(files)
    if failures:
        print("\n".join(failures))
        return 1
    if args.check:
        print(f"PASS: {len(files)} source files checked; private artifacts excluded")
        return 0
    target = ROOT / "dist" / "ai-job-hunter-source.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
    print(f"Created {target.relative_to(ROOT)} with {len(files)} checked source files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

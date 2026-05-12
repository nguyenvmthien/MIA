"""Fail CI when generated files, runtime data, or local secrets are tracked."""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    "data/workers.json",
    "data/audio/*",
    "data/transcripts/*",
    "data/tokens/*",
    "data/training/*",
    "data/eval/*",
    "docker/nginx/certs/server.key",
    "docker/pgadmin/pgpass",
    "*.pyc",
    "*/__pycache__/*",
    ".DS_Store",
    "*/.DS_Store",
    ".env",
    "*.env.local",
]

SECRET_MARKERS = [
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
]


def _git_ls_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], text=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _forbidden_tracked(files: list[str]) -> list[str]:
    violations: list[str] = []
    for path in files:
        if any(fnmatch.fnmatch(path, pattern) for pattern in FORBIDDEN_PATTERNS):
            violations.append(path)
    return violations


def _secret_markers(files: list[str]) -> list[str]:
    violations: list[str] = []
    for path in files:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker in text for marker in SECRET_MARKERS):
            violations.append(path)
    return violations


def main() -> int:
    files = _git_ls_files()
    forbidden = _forbidden_tracked(files)
    secrets = _secret_markers(files)
    if not forbidden and not secrets:
        print("Repository hygiene check passed.")
        return 0

    if forbidden:
        print("Forbidden tracked files:")
        for path in forbidden:
            print(f"  - {path}")
    if secrets:
        print("Tracked files containing private-key markers:")
        for path in secrets:
            print(f"  - {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

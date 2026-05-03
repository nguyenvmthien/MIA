"""
Dataset versioning via SHA-256 file hashes.

Creates/updates data/training/.dataset_manifest.json with:
  - version tag (v1, v2, ...)
  - per-file hash and line count
  - combined hash for the full training set

Used by finetune.py to log dataset_version and dataset_hash to MLflow.

Usage:
    python train/dataset_version.py                         # version current files
    python train/dataset_version.py --check                 # verify files unchanged
    python train/dataset_version.py --files a.jsonl b.jsonl # version specific files
"""

import argparse
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MANIFEST_PATH = Path("data/training/.dataset_manifest.json")
DEFAULT_FILES = [
    "data/training/collected.jsonl",
    "data/training/synthetic.jsonl",
    "data/training/feedback_corrections.jsonl",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _line_count(path: Path) -> int:
    return sum(1 for line in path.open() if line.strip())


def _next_version(manifest: dict) -> str:
    current = manifest.get("version", "v0")
    n = int(current.lstrip("v")) + 1
    return f"v{n}"


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"version": "v0", "files": {}, "combined_hash": "", "created_at": None}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def version_files(files: list[str]) -> dict:
    """Compute hashes, bump version, save manifest. Returns manifest."""
    existing = load_manifest()

    file_entries = {}
    hashes = []
    for f in files:
        p = Path(f)
        if not p.exists():
            log.debug("Skipping missing file: %s", f)
            continue
        sha = _sha256(p)
        lines = _line_count(p)
        file_entries[str(p)] = {"hash": sha, "lines": lines, "path": str(p)}
        hashes.append(sha)
        log.info("  %s: %d lines, sha256=%s…", p.name, lines, sha[:12])

    combined = hashlib.sha256("|".join(sorted(hashes)).encode()).hexdigest()

    # Only bump version if content changed
    if combined == existing.get("combined_hash"):
        log.info("Dataset unchanged (version=%s, hash=%s…)", existing["version"], combined[:12])
        return existing

    manifest = {
        "version": _next_version(existing),
        "created_at": datetime.utcnow().isoformat(),
        "files": file_entries,
        "combined_hash": combined,
        "total_lines": sum(e["lines"] for e in file_entries.values()),
        "previous_version": existing.get("version"),
        "previous_hash": existing.get("combined_hash"),
    }
    save_manifest(manifest)
    log.info("Dataset versioned: %s (hash=%s…, %d total lines)",
             manifest["version"], combined[:12], manifest["total_lines"])
    return manifest


def check_files(files: list[str]) -> bool:
    """Return True if all files match their recorded hashes."""
    manifest = load_manifest()
    if not manifest.get("files"):
        log.warning("No manifest found — run version_files first")
        return False

    all_ok = True
    for f in files:
        p = Path(f)
        if not p.exists():
            continue
        recorded = manifest["files"].get(str(p), {})
        if not recorded:
            log.warning("File not in manifest: %s", f)
            all_ok = False
            continue
        current_hash = _sha256(p)
        if current_hash != recorded["hash"]:
            log.warning("Hash mismatch for %s: recorded=%s… current=%s…",
                        f, recorded["hash"][:12], current_hash[:12])
            all_ok = False
        else:
            log.info("OK: %s", f)

    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset versioning")
    parser.add_argument("--files", nargs="*", default=DEFAULT_FILES,
                        help="Training files to version")
    parser.add_argument("--check", action="store_true",
                        help="Verify files match recorded hashes")
    args = parser.parse_args()

    if args.check:
        ok = check_files(args.files)
        if not ok:
            raise SystemExit(1)
    else:
        version_files(args.files)

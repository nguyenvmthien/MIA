"""Prepare a Hugging Face dataset folder for meeting E2E data.

The exported dataset uses manifest JSONL files plus separate audio,
transcript, and action-item label artifacts.
"""

from __future__ import annotations

import argparse
import json
import shutil
import wave
from pathlib import Path
from typing import Any

DEFAULT_SPLITS = {
    "train": "data/training/synthetic.jsonl",
    "validation": "data/training/synthetic_long.jsonl",
    "eval": "data/eval/gold_synthetic_205.jsonl",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )


def _duration_sec(path: Path) -> float | None:
    if path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wf:
            return round(wf.getnframes() / float(wf.getframerate()), 3)
    except wave.Error:
        return None


def _synthetic_long_audio() -> list[Path]:
    return sorted(Path("data/audio/synthetic").glob("*.wav"))


def _audio_for_sample(split: str, idx: int, sample: dict[str, Any]) -> Path | None:
    explicit = sample.get("audio_path")
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path

    # Current synthetic_long records are aligned with data/audio/synthetic/*.wav.
    # The combined eval file appends those same five long records at the end.
    linked_audio = _synthetic_long_audio()
    if sample.get("duration_min") is not None and idx < len(linked_audio):
        return linked_audio[idx]
    if split == "eval" and sample.get("duration_min") is not None:
        long_idx = idx - 200
        if 0 <= long_idx < len(linked_audio):
            return linked_audio[long_idx]
    return None


def _copy_audio(src: Path, out_dir: Path, split: str, sample_id: str) -> str:
    dst = out_dir / "audio" / split / f"{sample_id}{src.suffix.lower()}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.relative_to(out_dir).as_posix()


def _sample_id(split: str, idx: int) -> str:
    return f"{split}_{idx:06d}"


def _transcript_payload(sample_id: str, sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "meeting_date": sample.get("meeting_date"),
        "domain": sample.get("domain"),
        "participants": sample.get("participants"),
        "roster": sample.get("roster", {"workers": []}),
        "transcript_turns": sample.get("transcript_turns", []),
        "transcript": sample.get("transcript"),
    }


def _label_payload(sample_id: str, sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "action_items": sample.get("action_items", []),
    }


def _build_readme(stats: dict[str, dict[str, int]]) -> str:
    split_lines = "\n".join(
        f"- `{split}`: {s['samples']} samples, {s['with_audio']} with linked audio"
        for split, s in stats.items()
    )
    return f"""---
license: other
task_categories:
- automatic-speech-recognition
- text-generation
- other
language:
- en
tags:
- meetings
- action-items
- synthetic
- audio
pretty_name: MIA Meeting E2E Dataset
---

# MIA Meeting E2E Dataset

Synthetic meeting dataset for end-to-end experiments:

1. audio to transcript
2. transcript plus roster to action items
3. action item extraction benchmark

## Splits

{split_lines}

## Structure

```text
data/*.jsonl                 # split manifests
audio/<split>/*              # linked audio files when available
transcripts/<split>/*.json   # transcript, roster, participants
labels/<split>/*.json        # action item labels
schema/*.schema.json         # artifact schemas
```

## Privacy

This export is intended for private Hugging Face dataset repos by default.
Do not add real meeting audio or transcripts unless they have been reviewed
and scrubbed for sensitive information.
"""


def _write_schemas(out_dir: Path) -> None:
    manifest_schema = {
        "type": "object",
        "required": [
            "sample_id",
            "split",
            "transcript_path",
            "label_path",
            "has_transcript",
            "has_action_items",
            "has_audio",
        ],
        "properties": {
            "sample_id": {"type": "string"},
            "split": {"type": "string"},
            "meeting_date": {"type": ["string", "null"]},
            "domain": {"type": ["string", "null"]},
            "audio_path": {"type": ["string", "null"]},
            "transcript_path": {"type": "string"},
            "label_path": {"type": "string"},
            "duration_sec": {"type": ["number", "null"]},
            "language": {"type": "string"},
            "source": {"type": "string"},
            "has_audio": {"type": "boolean"},
            "has_transcript": {"type": "boolean"},
            "has_action_items": {"type": "boolean"},
        },
    }
    transcript_schema = {
        "type": "object",
        "required": ["sample_id", "transcript_turns", "roster"],
        "properties": {
            "sample_id": {"type": "string"},
            "meeting_date": {"type": ["string", "null"]},
            "domain": {"type": ["string", "null"]},
            "participants": {},
            "roster": {"type": "object"},
            "transcript_turns": {"type": "array"},
            "transcript": {"type": ["string", "null"]},
        },
    }
    label_schema = {
        "type": "object",
        "required": ["sample_id", "action_items"],
        "properties": {
            "sample_id": {"type": "string"},
            "action_items": {"type": "array"},
        },
    }
    _write_json(out_dir / "schema/manifest.schema.json", manifest_schema)
    _write_json(out_dir / "schema/transcript.schema.json", transcript_schema)
    _write_json(out_dir / "schema/action_items.schema.json", label_schema)


def build_dataset(out_dir: Path, splits: dict[str, Path], clean: bool) -> dict[str, dict[str, int]]:
    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stats: dict[str, dict[str, int]] = {}
    for split, src in splits.items():
        rows = _read_jsonl(src)
        manifest: list[dict[str, Any]] = []
        with_audio = 0
        for idx, sample in enumerate(rows):
            sample_id = _sample_id(split, idx)
            transcript_path = f"transcripts/{split}/{sample_id}.json"
            label_path = f"labels/{split}/{sample_id}.action_items.json"

            audio_src = _audio_for_sample(split, idx, sample)
            audio_path = None
            duration = sample.get("duration_sec")
            if duration is None and sample.get("duration_ms") is not None:
                duration = round(float(sample["duration_ms"]) / 1000.0, 3)
            if audio_src:
                audio_path = _copy_audio(audio_src, out_dir, split, sample_id)
                duration = _duration_sec(audio_src) or duration
                with_audio += 1

            _write_json(out_dir / transcript_path, _transcript_payload(sample_id, sample))
            _write_json(out_dir / label_path, _label_payload(sample_id, sample))

            manifest.append({
                "sample_id": sample_id,
                "split": split,
                "meeting_date": sample.get("meeting_date"),
                "domain": sample.get("domain"),
                "audio_path": audio_path,
                "transcript_path": transcript_path,
                "label_path": label_path,
                "duration_sec": duration,
                "language": "en",
                "source": sample.get("provider", "synthetic"),
                "has_audio": audio_path is not None,
                "has_transcript": bool(sample.get("transcript_turns")),
                "has_action_items": bool(sample.get("action_items")),
            })

        _write_jsonl(out_dir / "data" / f"{split}.jsonl", manifest)
        stats[split] = {"samples": len(rows), "with_audio": with_audio}

    _write_schemas(out_dir)
    (out_dir / "README.md").write_text(_build_readme(stats))
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Hugging Face dataset export")
    parser.add_argument("--out-dir", default="hf_dataset")
    parser.add_argument("--train", default=DEFAULT_SPLITS["train"])
    parser.add_argument("--validation", default=DEFAULT_SPLITS["validation"])
    parser.add_argument("--eval", default=DEFAULT_SPLITS["eval"])
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args()

    stats = build_dataset(
        out_dir=Path(args.out_dir),
        splits={
            "train": Path(args.train),
            "validation": Path(args.validation),
            "eval": Path(args.eval),
        },
        clean=not args.no_clean,
    )
    for split, s in stats.items():
        print(f"{split}: {s['samples']} samples, {s['with_audio']} with linked audio")
    print(f"HF dataset folder ready: {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

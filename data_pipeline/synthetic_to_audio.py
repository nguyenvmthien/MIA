"""Convert synthetic meeting JSONL samples into test audio files on macOS.

This script reads `data/training/synthetic.jsonl` and creates one audio file per row.
It uses macOS `say` to synthesize each transcript turn and `ffmpeg` to merge turns.

Example:
    python3 data_pipeline/synthetic_to_audio.py \
      --input data/training/synthetic.jsonl \
      --out-dir data/audio/synthetic \
      --limit 20
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

VOICE_POOL = ["Samantha", "Alex", "Daniel", "Karen", "Moira"]


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _speaker_voice(speaker: str, voice_map: dict[str, str]) -> str:
    if speaker not in voice_map:
        voice_map[speaker] = VOICE_POOL[len(voice_map) % len(VOICE_POOL)]
    return voice_map[speaker]


def _safe_name(index: int) -> str:
    return f"meeting_{index:05d}"


def _turns_from_sample(sample: dict) -> list[dict]:
    turns = sample.get("transcript_turns")
    if isinstance(turns, list) and turns:
        return turns

    transcript = str(sample.get("transcript", "")).strip()
    if not transcript:
        return []

    return [{"speaker_name": "Speaker", "text": transcript}]


def synthesize_sample(sample: dict, out_mp3: Path) -> None:
    turns = _turns_from_sample(sample)
    if not turns:
        raise ValueError("Sample has no transcript content")

    with tempfile.TemporaryDirectory(prefix="synthetic_audio_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        voice_map: dict[str, str] = {}
        segment_paths: list[Path] = []

        for i, turn in enumerate(turns):
            text = str(turn.get("text", "")).strip()
            if not text:
                continue
            speaker = str(turn.get("speaker_name", f"SPEAKER_{i:02d}"))
            voice = _speaker_voice(speaker, voice_map)
            segment = tmp_dir / f"seg_{i:03d}.aiff"
            _run(["say", "-v", voice, "-o", str(segment), text])
            segment_paths.append(segment)

        if not segment_paths:
            raise ValueError("Sample transcript has no non-empty turns")

        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in segment_paths),
            encoding="utf-8",
        )

        merged_wav = tmp_dir / "merged.wav"
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                str(merged_wav),
            ]
        )

        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(merged_wav), str(out_mp3)])


def convert(input_path: Path, out_dir: Path, start: int, limit: int | None, overwrite: bool) -> int:
    count = 0
    out_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx < start:
                continue
            if limit is not None and count >= limit:
                break

            line = line.strip()
            if not line:
                continue

            sample = json.loads(line)
            name = _safe_name(idx)
            out_mp3 = out_dir / f"{name}.mp3"
            out_json = out_dir / f"{name}.json"

            if out_mp3.exists() and not overwrite:
                count += 1
                continue

            synthesize_sample(sample, out_mp3)
            out_json.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
            count += 1

    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert synthetic meeting JSONL to audio files")
    parser.add_argument("--input", default="data/training/synthetic.jsonl", help="Input JSONL path")
    parser.add_argument("--out-dir", default="data/audio/synthetic", help="Output directory for .mp3")
    parser.add_argument("--start", type=int, default=0, help="Start row index in JSONL")
    parser.add_argument("--limit", type=int, default=None, help="Max samples to convert")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output files")
    return parser.parse_args()


def main() -> None:
    if shutil.which("say") is None:
        raise RuntimeError("macOS 'say' command not found")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg command not found. Install with: brew install ffmpeg")

    args = parse_args()
    converted = convert(
        input_path=Path(args.input),
        out_dir=Path(args.out_dir),
        start=args.start,
        limit=args.limit,
        overwrite=args.overwrite,
    )
    print(f"Converted {converted} sample(s) to audio in {args.out_dir}")


if __name__ == "__main__":
    main()

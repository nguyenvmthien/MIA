"""
Convert synthetic transcript JSONL → MP3 audio using macOS `say` command.

Each speaker is assigned a different voice so diarization has distinct signals.
Turns are concatenated in order with short silence gaps between speakers.

Usage:
    python data_pipeline/tts_macos.py \
        --input data/training/synthetic_v1_20260504.jsonl \
        --out-dir data/audio/synthetic_tts \
        --limit 12
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

# Decent-sounding English voices available on most macOS installs
_VOICE_POOL = [
    "Daniel",    # en_GB male
    "Karen",     # en_AU female
    "Moira",     # en_IE female
    "Rishi",     # en_IN male
    "Fred",      # en_US male
    "Kathy",     # en_US female
    "Aman",      # en_IN male
    "Eddy",      # en_US male
    "Flo",       # en_US female
    "Reed",      # en_US male
]

# Silence between turns (ms)
_GAP_MS = 600


def _assign_voices(speaker_names: list[str]) -> dict[str, str]:
    """Round-robin assign a unique voice to each speaker."""
    voices: dict[str, str] = {}
    for i, name in enumerate(speaker_names):
        voices[name] = _VOICE_POOL[i % len(_VOICE_POOL)]
    return voices


def _say_to_aiff(text: str, voice: str, out_path: str, rate: int = 175) -> bool:
    """Use macOS `say` to render text → AIFF. Returns True on success."""
    result = subprocess.run(
        ["say", "-v", voice, "-r", str(rate), "-o", out_path, text],
        capture_output=True,
    )
    return result.returncode == 0


def _aiff_to_mp3(aiff_path: str, mp3_path: str) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", aiff_path, "-codec:a", "libmp3lame", "-qscale:a", "4",
         "-loglevel", "error", mp3_path],
        capture_output=True,
    )
    return result.returncode == 0


def _silence_aiff(duration_ms: int, out_path: str) -> bool:
    """Generate silence of given duration using ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=22050:cl=mono", "-t", str(duration_ms / 1000),
         "-loglevel", "error", out_path],
        capture_output=True,
    )
    return result.returncode == 0


def _concat_aiffs(aiff_files: list[str], out_mp3: str) -> bool:
    """Concatenate multiple AIFF files into one MP3 via ffmpeg concat."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in aiff_files:
            f.write(f"file '{p}'\n")
        list_path = f.name
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
         "-codec:a", "libmp3lame", "-qscale:a", "4", "-loglevel", "error", out_mp3],
        capture_output=True,
    )
    os.unlink(list_path)
    return result.returncode == 0


def convert_sample(sample: dict, out_mp3: str) -> bool:
    """Convert one transcript sample to an MP3 file."""
    turns = sample.get("transcript_turns") or []
    if not turns:
        return False

    speaker_names = list(dict.fromkeys(t["speaker_name"] for t in turns))
    voices = _assign_voices(speaker_names)

    with tempfile.TemporaryDirectory() as tmp:
        turn_aiffs: list[str] = []

        for i, turn in enumerate(turns):
            name = turn.get("speaker_name", "")
            text = turn.get("text", "").strip()
            if not text:
                continue

            voice = voices.get(name, _VOICE_POOL[0])
            aiff = os.path.join(tmp, f"turn_{i:04d}.aiff")

            if not _say_to_aiff(text, voice, aiff):
                print(f"  warn: say failed for turn {i} ({name})")
                continue

            turn_aiffs.append(aiff)

            # Add silence gap between speakers (skip after last turn)
            if i < len(turns) - 1:
                gap = os.path.join(tmp, f"gap_{i:04d}.aiff")
                _silence_aiff(_GAP_MS, gap)
                turn_aiffs.append(gap)

        if not turn_aiffs:
            return False

        return _concat_aiffs(turn_aiffs, out_mp3)


def convert_jsonl(input_path: str, out_dir: str, limit: int | None = None) -> int:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    saved = 0

    with open(input_path) as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            sample = json.loads(line)
            domain = sample.get("domain", "unknown")
            turns = len(sample.get("transcript_turns") or [])
            out_mp3 = os.path.join(out_dir, f"meeting_{i:05d}_{domain}.mp3")

            print(f"[{i+1}] {domain} — {turns} turns → {Path(out_mp3).name}")
            ok = convert_sample(sample, out_mp3)
            if ok:
                saved += 1
                size_kb = Path(out_mp3).stat().st_size // 1024
                print(f"     ✓ {size_kb} KB")
            else:
                print(f"     ✗ failed")

    print(f"\nDone: {saved} MP3s saved to {out_dir}")
    return saved


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/training/synthetic_v1_20260504.jsonl")
    p.add_argument("--out-dir", default="data/audio/synthetic_tts")
    p.add_argument("--limit", type=int, default=None, help="Max samples to convert")
    args = p.parse_args()
    convert_jsonl(args.input, args.out_dir, args.limit)

"""
Convert synthetic meeting transcripts to audio WAV files using OpenAI TTS.

Each speaker gets a different voice. Turns are stitched together with short silences
to simulate a realistic multi-speaker meeting recording.

Usage:
    # Generate audio for all samples in a JSONL file:
    python data_pipeline/tts_audio.py --input data/training/synthetic.jsonl --out data/audio/

    # Generate only long meetings (~10 min), pick first N:
    python data_pipeline/tts_audio.py --input data/training/synthetic.jsonl --out data/audio/ --min-turns 40 --count 5
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# OpenAI TTS voices — assign round-robin per speaker
_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

# Silence between turns (bytes of 16-bit 24kHz mono PCM = 0.3s)
_SILENCE_MS = 300
_SAMPLE_RATE = 24000  # OpenAI TTS outputs 24kHz PCM


def _silence_bytes(ms: int) -> bytes:
    samples = int(_SAMPLE_RATE * ms / 1000)
    return b"\x00" * (samples * 2)  # 16-bit = 2 bytes per sample


def _write_wav(pcm: bytes, path: Path) -> None:
    import struct
    num_samples = len(pcm) // 2
    with open(path, "wb") as f:
        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(pcm)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))          # chunk size
        f.write(struct.pack("<H", 1))           # PCM
        f.write(struct.pack("<H", 1))           # mono
        f.write(struct.pack("<I", _SAMPLE_RATE))
        f.write(struct.pack("<I", _SAMPLE_RATE * 2))  # byte rate
        f.write(struct.pack("<H", 2))           # block align
        f.write(struct.pack("<H", 16))          # bits per sample
        f.write(b"data")
        f.write(struct.pack("<I", len(pcm)))
        f.write(pcm)


def transcript_to_audio(
    sample: dict,
    out_dir: Path,
    filename: str,
    api_key: str,
) -> Path | None:
    """Convert one transcript sample to a WAV file. Returns output path or None on failure."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    turns = sample.get("transcript_turns") or []
    if not turns:
        log.warning("Sample has no transcript_turns, skipping")
        return None

    # Assign a voice to each unique speaker
    speakers = list(dict.fromkeys(t["speaker_name"] for t in turns))
    voice_map = {name: _VOICES[i % len(_VOICES)] for i, name in enumerate(speakers)}

    log.info("Converting %d turns, %d speakers → %s", len(turns), len(speakers), filename)

    all_pcm = b""
    for i, turn in enumerate(turns):
        text = turn.get("text", "").strip()
        if not text:
            continue
        voice = voice_map.get(turn.get("speaker_name", ""), "alloy")
        try:
            response = client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text,
                response_format="pcm",  # raw 16-bit 24kHz mono
            )
            all_pcm += response.content
            all_pcm += _silence_bytes(_SILENCE_MS)
            if (i + 1) % 10 == 0:
                log.info("  %d/%d turns done", i + 1, len(turns))
        except Exception as exc:
            log.warning("TTS failed for turn %d (%s): %s", i, turn.get("speaker_name"), exc)

    if not all_pcm:
        return None

    out_path = out_dir / filename
    _write_wav(all_pcm, out_path)
    duration_min = len(all_pcm) / 2 / _SAMPLE_RATE / 60
    log.info("Saved %s (%.1f min)", out_path, duration_min)
    return out_path


def run(input_path: str, out_dir: str, min_turns: int, count: int) -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    samples = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line:
                s = json.loads(line)
                if s.get("num_turns", 0) >= min_turns:
                    samples.append(s)
                if len(samples) >= count:
                    break

    if not samples:
        log.warning("No samples found with >= %d turns in %s", min_turns, input_path)
        return

    log.info("Converting %d samples to audio (min_turns=%d)", len(samples), min_turns)
    for i, sample in enumerate(samples):
        domain = sample.get("domain", "meeting")
        date = sample.get("meeting_date", "unknown")
        filename = f"{i+1:03d}_{domain}_{date}.wav"
        transcript_to_audio(sample, out, filename, api_key)

    log.info("Done. Audio files saved to %s", out_dir)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Convert synthetic transcripts to audio WAV via OpenAI TTS")
    p.add_argument("--input", required=True, help="Input JSONL file with synthetic meetings")
    p.add_argument("--out", default="data/audio/synthetic", help="Output directory for WAV files")
    p.add_argument("--min-turns", type=int, default=30, help="Minimum turns for ~10min audio (default: 30)")
    p.add_argument("--count", type=int, default=5, help="Number of audio files to generate (default: 5)")
    args = p.parse_args()
    run(args.input, args.out, args.min_turns, args.count)

"""Tests for STT/diarization helpers."""

from meeting_agent.pipeline.stt import _word_majority_speaker


def test_word_majority_speaker_prefers_most_frequent_label():
    words = [
        {"word": "Alice", "speaker": "SPEAKER_00"},
        {"word": "please", "speaker": "SPEAKER_00"},
        {"word": "review", "speaker": "SPEAKER_01"},
    ]

    assert _word_majority_speaker(words) == "SPEAKER_00"


def test_word_majority_speaker_returns_none_when_missing():
    assert _word_majority_speaker([{"word": "hello"}]) is None

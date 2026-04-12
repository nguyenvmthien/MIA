"""TranscriptTurn — output of WhisperX STT + Pyannote diarization stage."""

from pydantic import BaseModel, Field, model_validator


class TranscriptTurn(BaseModel):
    turn_id: str = Field(description="Unique identifier for this speaker turn")
    speaker_id: str = Field(description="Raw diarization label e.g. SPEAKER_01")
    speaker_name: str | None = Field(
        default=None,
        description="Resolved human name from worker roster (may be None if unresolved)",
    )
    start_ms: int = Field(ge=0, description="Turn start time in milliseconds")
    end_ms: int = Field(ge=0, description="Turn end time in milliseconds")
    text: str = Field(description="Transcribed text for this turn")
    asr_confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="ASR word-level confidence average"
    )

    @model_validator(mode="after")
    def end_after_start(self) -> "TranscriptTurn":
        if self.end_ms <= self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) must be > start_ms ({self.start_ms})")
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def display_name(self) -> str:
        return self.speaker_name or self.speaker_id

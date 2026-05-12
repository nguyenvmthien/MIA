"""Canonical JSONL contracts for training, preference, and eval data."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from meeting_agent.prompts.templates import EXTRACT_TASKS_SYSTEM, EXTRACT_TASKS_USER


class TranscriptTurnRecord(BaseModel):
    turn_id: str | None = None
    speaker_id: str = "SPEAKER_00"
    speaker_name: str | None = None
    start_ms: int = 0
    end_ms: int = 0
    text: str
    asr_confidence: float | None = None


class ActionItemRecord(BaseModel):
    description: str
    assignee: str | None = None
    due_date: str | None = None
    priority: str | None = "medium"
    notes: str | None = None
    task_id: str | None = None


class RawMeetingRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["meeting_raw_v1"] = "meeting_raw_v1"
    meeting_id: str | None = None
    meeting_date: str
    participants: list[str] = Field(default_factory=list)
    roster: dict[str, Any] | str = Field(default_factory=dict)
    transcript_turns: list[TranscriptTurnRecord] = Field(default_factory=list)
    transcript: str | None = None
    action_items: list[ActionItemRecord] = Field(default_factory=list)

    @field_validator("participants", mode="before")
    @classmethod
    def _normalize_participants(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value

    @model_validator(mode="after")
    def _require_transcript(self) -> RawMeetingRecord:
        if not self.transcript and not self.transcript_turns:
            raise ValueError("raw meeting record requires transcript or transcript_turns")
        return self


class SFTRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["sft_v1"] = "sft_v1"
    instruction: str
    input: str
    output: str
    source_meeting_id: str | None = None
    model_version: str | None = None

    @field_validator("output")
    @classmethod
    def _output_json_array(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("output must be a JSON array string") from exc
        if not isinstance(parsed, list):
            raise ValueError("output must decode to a JSON array")
        return value


class RLHFPreferenceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["rlhf_v1"] = "rlhf_v1"
    prompt: str
    chosen: str
    rejected: str
    source_meeting_id: str | None = None
    feedback_type: Literal["correction", "false_positive"]
    model_version: str | None = None


class EvalGoldRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["eval_gold_v1"] = "eval_gold_v1"
    meeting_id: str
    meeting_date: str
    roster: dict[str, Any] = Field(default_factory=lambda: {"workers": []})
    transcript_turns: list[TranscriptTurnRecord]
    action_items: list[ActionItemRecord] = Field(default_factory=list)


class DriftRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["drift_v1"] = "drift_v1"
    meeting_id: str
    tasks_extracted: int = 0
    avg_token_count: float = 0
    hallucination_rate: float = 0
    assignee_hit_rate: float = 0


def load_jsonl_records(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _next_friday(meeting_date: str) -> str:
    try:
        parsed = date.fromisoformat(meeting_date)
    except ValueError:
        parsed = date.today()
    days_ahead = 4 - parsed.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (parsed + timedelta(days=days_ahead)).isoformat()


def _roster_for_prompt(roster: dict[str, Any] | str) -> str:
    if isinstance(roster, str):
        return roster
    workers = roster.get("workers", [])
    if not workers:
        return ""
    lines = []
    for worker in workers:
        name = worker.get("name") or worker.get("worker_name") or worker.get("worker_id")
        role = worker.get("role")
        aliases = worker.get("aliases") or []
        line = f"- {name}" if name else "- Unknown"
        if role:
            line += f" [{role}]"
        if aliases:
            line += f" aka {', '.join(aliases)}"
        lines.append(line)
    return "\n".join(lines)


def _transcript_text(record: RawMeetingRecord) -> str:
    if record.transcript:
        return record.transcript
    return "\n".join(
        f"[{turn.speaker_name or turn.speaker_id}]: {turn.text}"
        for turn in record.transcript_turns
    )


def build_sft_record(record: RawMeetingRecord) -> SFTRecord:
    system = EXTRACT_TASKS_SYSTEM.format(
        roster=_roster_for_prompt(record.roster),
        friday=_next_friday(record.meeting_date),
    )
    user = EXTRACT_TASKS_USER.format(
        meeting_date=record.meeting_date,
        participants=", ".join(record.participants),
        transcript=_transcript_text(record),
    )
    return SFTRecord(
        instruction=system,
        input=user,
        output=json.dumps(
            [item.model_dump(mode="json", exclude_none=True) for item in record.action_items],
            ensure_ascii=False,
        ),
        source_meeting_id=record.meeting_id,
    )


def normalize_training_record(row: dict[str, Any]) -> SFTRecord:
    """Accept canonical SFT or raw meeting records and return an SFT record."""
    schema_version = row.get("schema_version")
    if schema_version == "sft_v1" or {"instruction", "input", "output"} <= set(row):
        return SFTRecord.model_validate(row)
    if schema_version in {None, "meeting_raw_v1"}:
        return build_sft_record(RawMeetingRecord.model_validate(row))
    raise ValueError(f"Unsupported training schema_version: {schema_version}")


def validate_records(rows: list[dict[str, Any]], allowed: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    for idx, row in enumerate(rows):
        schema_version = row.get("schema_version")
        try:
            if schema_version == "sft_v1" or {"instruction", "input", "output"} <= set(row):
                if allowed and "sft_v1" not in allowed:
                    raise ValueError("sft_v1 is not allowed here")
                SFTRecord.model_validate(row)
            elif schema_version == "rlhf_v1":
                if allowed and "rlhf_v1" not in allowed:
                    raise ValueError("rlhf_v1 is not allowed here")
                RLHFPreferenceRecord.model_validate(row)
            elif schema_version == "eval_gold_v1":
                if allowed and "eval_gold_v1" not in allowed:
                    raise ValueError("eval_gold_v1 is not allowed here")
                EvalGoldRecord.model_validate(row)
            elif schema_version in {None, "meeting_raw_v1"}:
                if allowed and "meeting_raw_v1" not in allowed:
                    raise ValueError("meeting_raw_v1 is not allowed here")
                RawMeetingRecord.model_validate(row)
            else:
                raise ValueError(f"unknown schema_version {schema_version!r}")
        except Exception as exc:
            errors.append(f"record[{idx}]: {exc}")
    return errors

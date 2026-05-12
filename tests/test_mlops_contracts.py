import json

from meeting_agent.mlops.data_contracts import (
    DriftRecord,
    RawMeetingRecord,
    SFTRecord,
    build_sft_record,
    normalize_training_record,
    validate_records,
)


def test_raw_meeting_record_converts_to_sft_record():
    raw = {
        "schema_version": "meeting_raw_v1",
        "meeting_id": "m1",
        "meeting_date": "2026-05-13",
        "participants": ["Alice Chen", "Bob Kim"],
        "roster": {"workers": [{"worker_id": "w1", "name": "Bob Kim", "role": "Dev"}]},
        "transcript_turns": [
            {
                "turn_id": "t1",
                "speaker_id": "SPEAKER_00",
                "speaker_name": "Alice Chen",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "Bob, please send the report by Friday.",
            }
        ],
        "action_items": [{"description": "Send the report", "assignee": "Bob Kim"}],
    }

    record = build_sft_record(RawMeetingRecord.model_validate(raw))

    assert record.schema_version == "sft_v1"
    assert record.source_meeting_id == "m1"
    assert "Bob Kim" in record.input
    assert json.loads(record.output)[0]["description"] == "Send the report"


def test_normalize_training_record_accepts_canonical_sft():
    row = {
        "schema_version": "sft_v1",
        "instruction": "Extract action items.",
        "input": "Alice: send the report.",
        "output": "[]",
        "source_meeting_id": "m1",
    }

    record = normalize_training_record(row)

    assert isinstance(record, SFTRecord)
    assert record.source_meeting_id == "m1"


def test_validate_records_rejects_wrong_output_shape():
    rows = [{
        "schema_version": "sft_v1",
        "instruction": "Extract action items.",
        "input": "Alice: send the report.",
        "output": "{}",
    }]

    errors = validate_records(rows, allowed={"sft_v1"})

    assert errors
    assert "JSON array" in errors[0]


def test_drift_record_schema_defaults_version():
    record = DriftRecord.model_validate({
        "meeting_id": "m1",
        "tasks_extracted": 2,
        "avg_token_count": 120.5,
        "hallucination_rate": 0.0,
        "assignee_hit_rate": 0.5,
    })

    assert record.schema_version == "drift_v1"

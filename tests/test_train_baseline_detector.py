import json

import joblib

from meeting_agent.mlops.train_baseline_detector import train


def test_train_baseline_detector_writes_real_artifact(tmp_path):
    gold = tmp_path / "gold.jsonl"
    rows = []
    for idx in range(6):
        rows.append(
            {
                "transcript_turns": [
                    {"speaker_name": "Alice", "text": "General status update only."},
                    {"speaker_name": "Bob", "text": "I will send the report by Friday."},
                    {"speaker_name": "Carol", "text": "Thanks everyone."},
                ],
                "action_items": [
                    {
                        "description": "Send the report by Friday.",
                        "assignee": "Bob",
                        "due_date": "2026-05-29",
                    }
                ],
            }
        )
    gold.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    out_dir = tmp_path / "model"
    metrics = train(gold, out_dir)

    model_path = out_dir / "model.joblib"
    metadata_path = out_dir / "metadata.json"
    assert model_path.exists()
    assert metadata_path.exists()
    assert metrics["num_examples"] == 18
    model = joblib.load(model_path)
    assert model.predict(["Bob: I will send the report by Friday."])[0] in {0, 1}

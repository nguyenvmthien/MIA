"""
Synthetic meeting data generator.

Uses the local Ollama LLM to generate realistic meeting transcripts
with ground-truth action items for fine-tuning data augmentation.

Usage:
    python data_pipeline/synthetic.py --count 50 --out data/synthetic.jsonl
"""

import argparse
import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path

import ollama as ollama_client

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Sample personas and topics to randomize generation
_PERSONAS = [
    ("Alice Chen", "Product Manager"),
    ("Bob Kim", "Backend Developer"),
    ("Carol White", "Designer"),
    ("David Lee", "QA Engineer"),
    ("Eva Martinez", "DevOps"),
]

_TOPICS = [
    "Q2 product roadmap planning",
    "Sprint retrospective and next sprint planning",
    "Bug triage for the upcoming release",
    "Customer feedback review",
    "Infrastructure scaling discussion",
    "API design review",
    "Onboarding process improvements",
    "Marketing launch preparation",
]

_SYSTEM = """\
You are generating synthetic meeting training data. Output ONLY valid JSON.

Generate a short meeting transcript (4-8 turns) on the given topic with the given participants.
Then list ALL action items mentioned in the transcript.

Output format:
{
  "transcript_turns": [
    {"speaker_name": "Alice Chen", "speaker_id": "SPEAKER_00", "start_ms": 0, "end_ms": 5000,
     "text": "..."}
  ],
  "action_items": [
    {"description": "...", "assignee": "<exact name from participants or null>",
     "due_date": "<YYYY-MM-DD or null>", "priority": "<low|medium|high|critical>", "notes": null}
  ]
}
"""

_USER_TMPL = """\
TOPIC: {topic}
PARTICIPANTS: {participants}
MEETING DATE: {meeting_date}

Generate the JSON now:"""


def _generate_one(topic: str, participants: list[tuple], meeting_date: str) -> dict | None:
    """Generate one synthetic meeting sample."""
    participant_str = ", ".join(f"{name} ({role})" for name, role in participants)
    user_prompt = _USER_TMPL.format(
        topic=topic, participants=participant_str, meeting_date=meeting_date
    )
    try:
        response = ollama_client.chat(
            model="qwen2.5:3b",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.8, "seed": random.randint(0, 9999)},
        )
        raw = response["message"]["content"].strip()
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        data["meeting_date"] = meeting_date
        data["participants"] = participant_str
        data["roster"] = {"workers": [
            {"worker_id": f"w{i}", "name": name, "aliases": [name.split()[0]], "role": role}
            for i, (name, role) in enumerate(participants)
        ]}
        data["transcript"] = "\n".join(
            f"[{t['speaker_name']}]: {t['text']}"
            for t in data.get("transcript_turns", [])
        )
        return data
    except Exception as exc:
        log.warning("Generation failed for topic '%s': %s", topic, exc)
        return None


def generate(count: int, out_path: str) -> int:
    """Generate `count` synthetic samples and write to JSONL."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    today = date.today()

    with open(out_path, "w") as f:
        attempts = 0
        while saved < count and attempts < count * 3:
            attempts += 1
            topic = random.choice(_TOPICS)
            n_participants = random.randint(2, 4)
            participants = random.sample(_PERSONAS, n_participants)
            meeting_date = (today - timedelta(days=random.randint(0, 30))).isoformat()

            sample = _generate_one(topic, participants, meeting_date)
            if sample and sample.get("action_items") is not None:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                saved += 1
                log.info("[%d/%d] Generated sample: '%s'", saved, count, topic)

    log.info("Saved %d synthetic samples to %s", saved, out_path)
    return saved


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=50, help="Number of samples to generate")
    p.add_argument("--out", default="data/training/synthetic.jsonl")
    args = p.parse_args()
    generate(args.count, args.out)

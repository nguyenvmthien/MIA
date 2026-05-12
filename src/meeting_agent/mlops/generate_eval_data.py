"""
Generate synthetic evaluation transcripts using the local Ollama LLM.

Produces 45 diverse meeting transcripts across 5 meeting types, each with
gold-annotated action items. Output matches the gold_smoke.jsonl schema exactly.

Usage:
    python -m meeting_agent.mlops.generate_eval_data                    # generate all 45
    python -m meeting_agent.mlops.generate_eval_data --count 10         # generate 10
    python -m meeting_agent.mlops.generate_eval_data --out data/eval/gold_v1.jsonl
    python -m meeting_agent.mlops.generate_eval_data --dry-run          # print first prompt only
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Workers pool ──────────────────────────────────────────────────────────────
WORKERS = [
    {"worker_id": "w1", "name": "Alice Chen",   "aliases": ["Alice"],  "role": "PM"},
    {"worker_id": "w2", "name": "Bob Kim",      "aliases": ["Bob"],    "role": "Engineer"},
    {"worker_id": "w3", "name": "Carol Davis",  "aliases": ["Carol"],  "role": "Designer"},
    {"worker_id": "w4", "name": "David Lee",    "aliases": ["David"],  "role": "DevOps"},
    {"worker_id": "w5", "name": "Eva Martinez", "aliases": ["Eva"],    "role": "QA"},
    {"worker_id": "w6", "name": "Frank Wong",   "aliases": ["Frank"],  "role": "Engineer"},
    {"worker_id": "w7", "name": "Grace Kim",    "aliases": ["Grace"],  "role": "Data Scientist"},
    {"worker_id": "w8", "name": "Henry Park",   "aliases": ["Henry"],  "role": "Backend"},
]

# ── Meeting type templates ────────────────────────────────────────────────────
MEETING_TYPES = [
    {
        "type": "sprint_planning",
        "description": "Sprint planning meeting where team assigns tasks for the upcoming sprint",
        "typical_tasks": "deploy features, write tests, fix bugs, update docs, review PRs",
    },
    {
        "type": "design_review",
        "description": "Design review session where team discusses UI/UX changes and technical decisions",
        "typical_tasks": "update mockups, implement feedback, schedule follow-up, prepare assets",
    },
    {
        "type": "incident_postmortem",
        "description": "Post-incident review to discuss what went wrong and prevent recurrence",
        "typical_tasks": "patch vulnerabilities, add monitoring, write runbooks, set up alerts",
    },
    {
        "type": "one_on_one",
        "description": "One-on-one meeting between manager and team member to discuss progress and blockers",
        "typical_tasks": "complete training, finish feature, escalate issue, schedule review",
    },
    {
        "type": "product_review",
        "description": "Product review meeting to assess feature progress and align on priorities",
        "typical_tasks": "prepare demo, write user stories, prioritize backlog, gather feedback",
    },
]

# ── Date helpers ──────────────────────────────────────────────────────────────
def _random_meeting_date() -> str:
    """Random date within last 30 days."""
    base = date(2026, 4, 1)
    return (base + timedelta(days=random.randint(0, 28))).isoformat()


def _due_date(meeting_date: str, days_ahead: int) -> str:
    d = date.fromisoformat(meeting_date) + timedelta(days=days_ahead)
    return d.isoformat()


# ── LLM call ─────────────────────────────────────────────────────────────────
def _call_ollama(prompt: str, model: str = "qwen2.5:3b") -> str:
    try:
        import ollama
        client = ollama.Client(host="http://localhost:11434")
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.8, "seed": random.randint(0, 99999)},
        )
        return response["message"]["content"]
    except Exception as e:
        log.error("Ollama call failed: %s", e)
        raise


# ── Prompt builder ────────────────────────────────────────────────────────────
def _build_prompt(meeting_type: dict, participants: list[dict], meeting_date: str) -> str:
    names = ", ".join(f"{w['name']} ({w['role']})" for w in participants)
    friday = _due_date(meeting_date, (4 - date.fromisoformat(meeting_date).weekday()) % 7 or 7)

    return f"""You are generating a realistic meeting transcript for an evaluation dataset.

MEETING TYPE: {meeting_type['type']} — {meeting_type['description']}
PARTICIPANTS: {names}
MEETING DATE: {meeting_date}
NEXT FRIDAY: {friday}
TYPICAL TASKS: {meeting_type['typical_tasks']}

Generate a realistic meeting transcript with 6-12 speaker turns where participants
discuss work and explicitly assign 2-4 action items with clear owners and deadlines.

Rules:
- Each turn: speaker says something natural and realistic
- Action items must be explicitly stated (not implied)
- Due dates must be mentioned verbally (e.g. "by Friday", "by April 20th")
- Include ONLY these participants as speakers
- Make it specific and technical, not generic

Output ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "transcript_turns": [
    {{"speaker_name": "<name>", "text": "<what they said>"}},
    ...
  ],
  "action_items": [
    {{
      "description": "<clear imperative action>",
      "assignee": "<full name from participants>",
      "due_date": "<YYYY-MM-DD>",
      "priority": "<low|medium|high|critical>",
      "notes": "<optional clarification or null>"
    }},
    ...
  ]
}}"""


# ── Parse LLM output ──────────────────────────────────────────────────────────
def _parse_output(raw: str, participants: list[dict], meeting_date: str, idx: int) -> dict | None:
    import re
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Find JSON object
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        log.warning("No JSON found in LLM output for sample %d", idx)
        return None

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        log.warning("JSON parse error for sample %d: %s", idx, e)
        return None

    turns = data.get("transcript_turns", [])
    action_items = data.get("action_items", [])

    if not turns or not action_items:
        log.warning("Empty turns or action_items for sample %d", idx)
        return None

    # Enrich turns with timing and speaker_id
    roster_names = {w["name"]: w for w in participants}
    speaker_ids: dict[str, str] = {}
    sid_counter = 0
    enriched_turns = []
    t_ms = 0
    for turn in turns:
        name = turn.get("speaker_name", "")
        if name not in speaker_ids:
            speaker_ids[name] = f"SPEAKER_{sid_counter:02d}"
            sid_counter += 1
        duration = max(2000, len(turn.get("text", "")) * 60)  # ~60ms per char
        enriched_turns.append({
            "speaker_name": name,
            "speaker_id": speaker_ids[name],
            "start_ms": t_ms,
            "end_ms": t_ms + duration,
            "text": turn.get("text", ""),
        })
        t_ms += duration + 500

    # Validate action items have known assignees
    valid_items = []
    for item in action_items:
        assignee = item.get("assignee", "")
        if assignee not in roster_names and assignee not in [w["aliases"][0] for w in participants]:
            log.warning("Unknown assignee '%s' in sample %d — skipping item", assignee, idx)
            continue
        # Resolve alias to full name
        if assignee not in roster_names:
            for w in participants:
                if assignee in w["aliases"]:
                    item["assignee"] = w["name"]
                    break
        valid_items.append(item)

    if not valid_items:
        log.warning("No valid action items after validation for sample %d", idx)
        return None

    return {
        "meeting_date": meeting_date,
        "participants": ", ".join(w["name"] for w in participants),
        "transcript_turns": enriched_turns,
        "roster": {"workers": participants},
        "action_items": valid_items,
    }


# ── Main generation loop ──────────────────────────────────────────────────────
def generate(count: int, out_path: Path, model: str, dry_run: bool) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated = 0
    attempts = 0
    max_attempts = count * 3  # allow retries

    # Distribute evenly across meeting types
    type_queue = (MEETING_TYPES * ((count // len(MEETING_TYPES)) + 1))[:count]
    random.shuffle(type_queue)

    with out_path.open("a") as f:
        for i, meeting_type in enumerate(type_queue):
            if generated >= count or attempts >= max_attempts:
                break
            attempts += 1

            # Pick 2-4 random participants
            n_participants = random.randint(2, 4)
            participants = random.sample(WORKERS, n_participants)
            meeting_date = _random_meeting_date()

            prompt = _build_prompt(meeting_type, participants, meeting_date)

            if dry_run:
                print("=== DRY RUN: First prompt ===")
                print(prompt)
                return 0

            log.info("Generating sample %d/%d (type=%s, participants=%d) ...",
                     generated + 1, count, meeting_type["type"], n_participants)

            try:
                raw = _call_ollama(prompt, model)
                sample = _parse_output(raw, participants, meeting_date, i)
                if sample is None:
                    log.warning("Sample %d failed validation, retrying...", i)
                    # retry with same type
                    type_queue.append(meeting_type)
                    continue

                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                f.flush()
                generated += 1
                log.info("  ✓ Sample %d: %d turns, %d action items",
                         generated, len(sample["transcript_turns"]), len(sample["action_items"]))
                time.sleep(0.5)  # be gentle to Ollama

            except Exception as e:
                log.error("Generation failed for sample %d: %s", i, e)
                continue

    return generated


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic eval transcripts")
    parser.add_argument("--count", type=int, default=45, help="Number of samples to generate")
    parser.add_argument("--out", type=str, default="data/eval/synthetic_batch_1.jsonl",
                        help="Output JSONL file path")
    parser.add_argument("--model", type=str, default="qwen2.5:3b", help="Ollama model name")
    parser.add_argument("--dry-run", action="store_true", help="Print first prompt and exit")
    args = parser.parse_args()

    out = Path(args.out)
    log.info("Generating %d samples → %s", args.count, out)
    n = generate(args.count, out, args.model, args.dry_run)
    if not args.dry_run:
        log.info("Done: %d samples written to %s", n, out)
        if n < args.count:
            log.warning("Only %d/%d samples generated (some failed validation)", n, args.count)
            sys.exit(1)

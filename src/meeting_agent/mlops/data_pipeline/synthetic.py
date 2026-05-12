"""
Synthetic meeting data generator.

Supports two LLM backends:
  --provider ollama   Local Ollama (default, free, slower, lower quality for long meetings)
  --provider gemini   Google Gemini Flash via API (recommended for 200+ samples)

Usage:
    # Ollama (local):
    python -m meeting_agent.mlops.data_pipeline.synthetic --count 50 --out data/synthetic.jsonl

    # Gemini Flash (requires GEMINI_API_KEY in .env):
    python -m meeting_agent.mlops.data_pipeline.synthetic --count 200 --provider gemini --out data/training/synthetic.jsonl
"""

import argparse
import json
import logging
import os
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import ollama as ollama_client
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Personas pool (diverse roles, not just tech) ───────────────────────────────

_PERSONAS = [
    # Tech
    ("Alice Chen", "Product Manager"),
    ("Bob Kim", "Backend Developer"),
    ("Carol White", "UX Designer"),
    ("David Lee", "QA Engineer"),
    ("Eva Martinez", "DevOps Engineer"),
    ("Frank Nguyen", "Frontend Developer"),
    ("Grace Park", "Engineering Manager"),
    ("Henry Zhou", "Data Engineer"),
    # Marketing
    ("Isabelle Durand", "Marketing Manager"),
    ("Jake Thompson", "Content Strategist"),
    ("Karen Patel", "Brand Designer"),
    ("Liam O'Brien", "Growth Marketer"),
    ("Maya Singh", "Social Media Manager"),
    ("Nathan Brooks", "SEO Specialist"),
    # Finance
    ("Olivia Zhang", "CFO"),
    ("Peter Walsh", "Financial Analyst"),
    ("Quinn Adams", "Accountant"),
    ("Rachel Kim", "Budget Controller"),
    ("Samuel Torres", "Treasury Manager"),
    # Sales & Business
    ("Tina Müller", "Sales Director"),
    ("Umar Hassan", "Account Executive"),
    ("Vanessa Li", "Customer Success Manager"),
    ("William Clark", "Business Development Manager"),
    ("Xiao Feng", "Partnership Manager"),
    # Operations & HR
    ("Yuki Tanaka", "Operations Manager"),
    ("Zoe Hernandez", "HR Manager"),
    ("Aaron Scott", "Supply Chain Manager"),
    ("Bella Johnson", "Talent Acquisition"),
    ("Carlos Rivera", "Office Manager"),
    # Legal & Compliance
    ("Diana Moore", "Legal Counsel"),
    ("Edward Hill", "Compliance Officer"),
    # Executive
    ("Fiona Campbell", "CEO"),
    ("George Baker", "COO"),
]

# ── Topic registry: (topic_text, domain, typical_turns_range) ─────────────────
# turns_range controls how long the meeting transcript should be

_TOPIC_REGISTRY: list[tuple[str, str, tuple[int, int]]] = [
    # --- Tech ---
    ("Q2 product roadmap planning", "tech", (6, 10)),
    ("Sprint retrospective and next sprint planning", "tech", (6, 10)),
    ("Bug triage for the upcoming release", "tech", (5, 8)),
    ("API design review for the new payment service", "tech", (6, 10)),
    ("Infrastructure scaling discussion for peak traffic", "tech", (5, 8)),
    ("Post-mortem on last week's production outage", "tech", (8, 14)),
    ("Mobile app feature prioritization", "tech", (6, 10)),
    ("Data pipeline architecture review", "tech", (6, 10)),
    ("Security audit findings and remediation plan", "tech", (8, 12)),
    ("AI model evaluation and deployment decision", "tech", (6, 10)),
    # --- Marketing ---
    ("Q3 marketing campaign planning", "marketing", (6, 10)),
    ("Brand refresh strategy and timeline", "marketing", (8, 14)),
    ("Social media content calendar review", "marketing", (5, 8)),
    ("Launch plan for the new product line", "marketing", (8, 14)),
    ("Customer survey results analysis and next steps", "marketing", (6, 10)),
    ("SEO audit and organic growth strategy", "marketing", (6, 10)),
    ("Influencer partnership evaluation", "marketing", (5, 8)),
    ("Email marketing performance review", "marketing", (5, 8)),
    ("Trade show / event sponsorship planning", "marketing", (6, 10)),
    ("Competitor analysis and positioning update", "marketing", (6, 10)),
    # --- Finance ---
    ("Annual budget planning meeting", "finance", (10, 16)),
    ("Q2 financial results review", "finance", (8, 14)),
    ("Cost reduction initiative kickoff", "finance", (8, 12)),
    ("Investment proposal evaluation", "finance", (8, 14)),
    ("Monthly cash flow forecast review", "finance", (6, 10)),
    ("Audit preparation and compliance check", "finance", (8, 12)),
    ("Vendor contract renegotiation strategy", "finance", (6, 10)),
    ("Expense policy update discussion", "finance", (5, 8)),
    ("Pricing strategy review for enterprise tier", "finance", (6, 10)),
    ("End-of-year financial closing checklist", "finance", (8, 12)),
    # --- Sales ---
    ("Sales pipeline review and forecast", "sales", (8, 14)),
    ("Key account strategy session", "sales", (8, 12)),
    ("New sales territory planning", "sales", (6, 10)),
    ("Customer churn analysis and retention plan", "sales", (6, 10)),
    ("Partnership deal evaluation", "sales", (6, 10)),
    ("Sales enablement content planning", "sales", (5, 8)),
    ("Quarterly business review with enterprise client", "sales", (10, 16)),
    # --- Operations & HR ---
    ("Hiring plan for H2 and headcount approval", "hr", (8, 12)),
    ("Performance review process design", "hr", (6, 10)),
    ("Employee onboarding process improvement", "hr", (6, 10)),
    ("Return-to-office policy update", "hr", (8, 14)),
    ("Supply chain disruption response plan", "operations", (8, 14)),
    ("Office relocation planning", "operations", (8, 12)),
    ("Vendor selection for new procurement system", "operations", (6, 10)),
    ("OKR setting for next quarter", "operations", (8, 14)),
    # --- Legal / Compliance ---
    ("GDPR compliance review and action plan", "legal", (8, 12)),
    ("Contract review for new partnership", "legal", (6, 10)),
    ("Intellectual property strategy discussion", "legal", (6, 10)),
    # --- Executive / Cross-functional ---
    ("All-hands strategic planning for next year", "executive", (12, 20)),
    ("Crisis communications response planning", "executive", (8, 14)),
    ("M&A due diligence kickoff", "executive", (10, 16)),
    ("Board presentation preparation", "executive", (8, 14)),
    ("Cross-team dependency alignment", "executive", (6, 10)),
    ("Company values and culture initiative", "executive", (8, 12)),
]

# Personas grouped by domain affinity for more realistic participant selection
_DOMAIN_PERSONAS: dict[str, list[tuple[str, str]]] = {
    "tech": [
        ("Alice Chen", "Product Manager"), ("Bob Kim", "Backend Developer"),
        ("Carol White", "UX Designer"), ("David Lee", "QA Engineer"),
        ("Eva Martinez", "DevOps Engineer"), ("Frank Nguyen", "Frontend Developer"),
        ("Grace Park", "Engineering Manager"), ("Henry Zhou", "Data Engineer"),
    ],
    "marketing": [
        ("Isabelle Durand", "Marketing Manager"), ("Jake Thompson", "Content Strategist"),
        ("Karen Patel", "Brand Designer"), ("Liam O'Brien", "Growth Marketer"),
        ("Maya Singh", "Social Media Manager"), ("Nathan Brooks", "SEO Specialist"),
        ("Alice Chen", "Product Manager"),
    ],
    "finance": [
        ("Olivia Zhang", "CFO"), ("Peter Walsh", "Financial Analyst"),
        ("Quinn Adams", "Accountant"), ("Rachel Kim", "Budget Controller"),
        ("Samuel Torres", "Treasury Manager"), ("George Baker", "COO"),
    ],
    "sales": [
        ("Tina Müller", "Sales Director"), ("Umar Hassan", "Account Executive"),
        ("Vanessa Li", "Customer Success Manager"),
        ("William Clark", "Business Development Manager"),
        ("Xiao Feng", "Partnership Manager"),
    ],
    "hr": [
        ("Zoe Hernandez", "HR Manager"), ("Bella Johnson", "Talent Acquisition"),
        ("Yuki Tanaka", "Operations Manager"), ("Fiona Campbell", "CEO"),
        ("Aaron Scott", "Supply Chain Manager"),
    ],
    "operations": [
        ("Yuki Tanaka", "Operations Manager"), ("Aaron Scott", "Supply Chain Manager"),
        ("Carlos Rivera", "Office Manager"), ("George Baker", "COO"),
        ("Rachel Kim", "Budget Controller"),
    ],
    "legal": [
        ("Diana Moore", "Legal Counsel"), ("Edward Hill", "Compliance Officer"),
        ("Fiona Campbell", "CEO"), ("Olivia Zhang", "CFO"),
    ],
    "executive": [
        ("Fiona Campbell", "CEO"), ("George Baker", "COO"),
        ("Olivia Zhang", "CFO"), ("Tina Müller", "Sales Director"),
        ("Grace Park", "Engineering Manager"), ("Isabelle Durand", "Marketing Manager"),
        ("Zoe Hernandez", "HR Manager"),
    ],
}

_SYSTEM = """\
You are generating synthetic meeting training data. Output ONLY valid JSON.

Generate a realistic meeting transcript of exactly {num_turns} turns on the given topic.
The meeting should feel natural: participants may agree, disagree, ask follow-up questions,
reference previous discussions, and use domain-appropriate vocabulary.
Then list ALL action items explicitly mentioned in the transcript.

IMPORTANT GROUNDING RULES:
- Every action item must be explicitly mentioned or clearly implied in transcript_turns text.
- Do not invent tasks that are not spoken.
- If no action items are mentioned, return an empty list.
- Assignee must be an exact participant name or null.
- For longer meetings, it is normal to have 3-8 action items.

Output format:
{{
  "transcript_turns": [
    {{"speaker_name": "Alice Chen", "speaker_id": "SPEAKER_00", "start_ms": 0, "end_ms": 5000,
     "text": "..."}}
  ],
  "action_items": [
    {{"description": "...", "assignee": "<exact name from participants or null>",
     "due_date": "<YYYY-MM-DD or null>", "priority": "<low|medium|high|critical>", "notes": null}}
  ]
}}
"""

_USER_TMPL = """\
TOPIC: {topic}
DOMAIN: {domain}
PARTICIPANTS: {participants}
MEETING DATE: {meeting_date}
TARGET TURNS: {num_turns}

Generate the JSON now:"""

# Segment prompt for long meeting continuation
_SEGMENT_SYSTEM = """\
You are generating one segment of a long meeting transcript. Output ONLY valid JSON.

Generate exactly {num_turns} turns that naturally continue the meeting.
The segment should feel like a seamless continuation — participants may reference
what was just said, introduce new sub-topics, or wrap up previous points.
List ONLY action items that are NEW and explicitly mentioned in THIS segment.

IMPORTANT GROUNDING RULES:
- Every action item must be explicitly mentioned in this segment's transcript_turns.
- Do not repeat action items from the previous discussion summary.
- Assignee must be an exact participant name or null.

Output format:
{{
  "transcript_turns": [
    {{"speaker_name": "Alice Chen", "speaker_id": "SPEAKER_00", "start_ms": 0, "end_ms": 5000,
     "text": "..."}}
  ],
  "action_items": [
    {{"description": "...", "assignee": "<exact name from participants or null>",
     "due_date": "<YYYY-MM-DD or null>", "priority": "<low|medium|high|critical>", "notes": null}}
  ]
}}
"""

_SEGMENT_USER_TMPL = """\
TOPIC: {topic}
DOMAIN: {domain}
PARTICIPANTS: {participants}
MEETING DATE: {meeting_date}
SEGMENT: {segment_num} of {total_segments}
TARGET TURNS: {num_turns}

PREVIOUS DISCUSSION SUMMARY:
{prev_summary}

LAST EXCHANGE (maintain continuity):
{last_exchange}

Continue the meeting from where it left off:"""


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "our", "that", "the", "their", "this", "to",
    "today", "tomorrow", "we", "will", "with", "please", "can", "you", "your", "team",
}


def _tokenize(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(t) > 2 and t not in _STOPWORDS
    }


def _filter_grounded_action_items(data: dict) -> list[dict]:
    """Keep only action items that are explicitly grounded in transcript text."""
    turns = data.get("transcript_turns") or []
    transcript_text = "\n".join(str(t.get("text", "")) for t in turns)
    transcript_tokens = _tokenize(transcript_text)

    # Build valid speaker name set from transcript turns
    speaker_names = {str(t.get("speaker_name", "")).strip() for t in turns}

    grounded: list[dict] = []
    for item in data.get("action_items") or []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue

        desc_tokens = _tokenize(description)
        if not desc_tokens:
            continue

        overlap = len(desc_tokens & transcript_tokens)
        assignee = item.get("assignee")

        # Assignee is valid if: null/empty, OR matches a speaker name, OR appears in transcript text
        if assignee in (None, "", "null"):
            assignee_ok = True
        elif str(assignee) in speaker_names:
            assignee_ok = True
        else:
            assignee_ok = str(assignee) in transcript_text

        # Require meaningful lexical overlap + valid assignee
        if overlap >= 2 and assignee_ok:
            grounded.append(item)

    return grounded


# ── LLM backends ──────────────────────────────────────────────────────────────

def _call_ollama(system: str, user: str, model: str = "qwen2.5:3b") -> str:
    response = ollama_client.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        options={"temperature": 0.85, "seed": random.randint(0, 9999), "num_ctx": 8192},
    )
    return response["message"]["content"].strip()


def _call_gemini(system: str, user: str, model: str = "gemini-2.5-flash") -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("Install google-genai: pip install -e '.[data]'")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.9,
            response_mime_type="application/json",
        ),
    )
    return response.text.strip()


def _llm_call(system: str, user: str, provider: str) -> str:
    if provider == "gemini":
        return _call_gemini(system, user)
    return _call_ollama(system, user)


def _pick_participants(domain: str, n: int) -> list[tuple[str, str]]:
    """Pick n participants biased toward the topic's domain, with some cross-domain noise."""
    pool = _DOMAIN_PERSONAS.get(domain, _PERSONAS)
    # 70% from domain pool, 30% from general pool to simulate cross-functional meetings
    cross = [p for p in _PERSONAS if p not in pool]
    combined = pool + random.sample(cross, min(len(cross), max(1, n // 3)))
    return random.sample(combined, min(n, len(combined)))


def _generate_one(
    topic: str,
    domain: str,
    num_turns: int,
    participants: list[tuple],
    meeting_date: str,
    provider: str = "ollama",
) -> dict | None:
    """Generate one synthetic meeting sample."""
    participant_str = ", ".join(f"{name} ({role})" for name, role in participants)
    system_prompt = _SYSTEM.format(num_turns=num_turns)
    user_prompt = _USER_TMPL.format(
        topic=topic,
        domain=domain,
        participants=participant_str,
        meeting_date=meeting_date,
        num_turns=num_turns,
    )
    try:
        raw = _llm_call(system_prompt, user_prompt, provider)
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw.strip())
        grounded_items = _filter_grounded_action_items(data)
        if (data.get("action_items") or []) and not grounded_items:
            raise ValueError("No grounded action items found in transcript")
        data["action_items"] = grounded_items
        data["meeting_date"] = meeting_date
        data["domain"] = domain
        data["provider"] = provider
        data["num_turns"] = len(data.get("transcript_turns") or [])
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


def generate(count: int, out_path: str, provider: str = "ollama") -> int:
    """Generate `count` synthetic samples and write to JSONL.

    Topics are sampled with equal probability across all domains.
    Meeting length (num_turns) is drawn from each topic's configured range,
    which naturally varies short stand-ups from long strategic sessions.
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    today = date.today()
    domain_counts: dict[str, int] = {}

    log.info("Starting generation: count=%d provider=%s out=%s", count, provider, out_path)

    with open(out_path, "w") as f:
        attempts = 0
        while saved < count and attempts < count * 3:
            attempts += 1
            topic_str, domain, turns_range = random.choice(_TOPIC_REGISTRY)
            num_turns = random.randint(*turns_range)
            n_participants = random.randint(2, min(5, len(_DOMAIN_PERSONAS.get(domain, _PERSONAS))))
            participants = _pick_participants(domain, n_participants)
            meeting_date = (today - timedelta(days=random.randint(0, 60))).isoformat()

            sample = _generate_one(topic_str, domain, num_turns, participants, meeting_date, provider)
            if sample and sample.get("action_items") is not None:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                f.flush()  # persist incrementally so partial runs are not lost
                saved += 1
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
                log.info(
                    "[%d/%d] [%s] %d turns, %d tasks — '%s'",
                    saved, count, domain, num_turns,
                    len(sample.get("action_items", [])), topic_str,
                )

    log.info("Saved %d samples to %s | domain breakdown: %s", saved, out_path, domain_counts)
    return saved


def _summarise_segment(turns: list[dict], action_items: list[dict]) -> str:
    """Build a short summary of a completed segment for use as context in the next."""
    lines = []
    if action_items:
        lines.append("Action items decided so far:")
        for item in action_items:
            assignee = f" → {item['assignee']}" if item.get("assignee") else ""
            lines.append(f"  - {item['description']}{assignee}")
    if turns:
        # Last speaker's topic as a one-liner
        last = turns[-1]
        lines.append(f"Last speaker: {last['speaker_name']} said: \"{last['text'][:120]}...\"")
    return "\n".join(lines) if lines else "Meeting just started."


def _ms_per_word() -> int:
    """Approximate ms per spoken word at normal meeting pace (~130 wpm)."""
    return round(60_000 / 130)


def generate_long_meeting(
    topic: str,
    domain: str,
    participants: list[tuple[str, str]],
    meeting_date: str,
    target_duration_min: int = 30,
    turns_per_segment: int = 10,
    provider: str = "gemini",
) -> dict | None:
    """Generate a long meeting transcript by stitching multiple segments together.

    Each segment is generated with context from the previous one to maintain
    conversational continuity. Timestamps are adjusted so the full transcript
    reads as one continuous recording.

    Args:
        target_duration_min: Approximate target meeting length in minutes.
        turns_per_segment: Turns per LLM call (10-12 recommended for reliability).
    """
    # Estimate how many segments we need
    words_per_turn = 40          # empirical average from tests
    words_per_min = 130          # normal speaking pace
    total_words_target = target_duration_min * words_per_min
    total_turns_target = total_words_target // words_per_turn
    total_segments = max(2, round(total_turns_target / turns_per_segment))

    participant_str = ", ".join(f"{name} ({role})" for name, role in participants)
    speaker_ids = {name: f"SPEAKER_{i:02d}" for i, (name, _) in enumerate(participants)}

    log.info(
        "Long meeting: topic='%s' domain=%s target=%dmin segments=%d",
        topic, domain, target_duration_min, total_segments,
    )

    all_turns: list[dict] = []
    all_action_items: list[dict] = []
    seen_descriptions: set[str] = set()
    current_ms = 0

    for seg_idx in range(total_segments):
        is_first = seg_idx == 0

        if is_first:
            # First segment: use the regular _generate_one path
            sample = _generate_one(
                topic, domain, turns_per_segment, participants, meeting_date, provider
            )
        else:
            # Continuation segment
            prev_summary = _summarise_segment(all_turns, all_action_items)
            last_exchange = "\n".join(
                f"[{t['speaker_name']}]: {t['text']}"
                for t in all_turns[-3:]  # last 3 turns for immediate context
            )
            system_prompt = _SEGMENT_SYSTEM.format(num_turns=turns_per_segment)
            user_prompt = _SEGMENT_USER_TMPL.format(
                topic=topic,
                domain=domain,
                participants=participant_str,
                meeting_date=meeting_date,
                segment_num=seg_idx + 1,
                total_segments=total_segments,
                num_turns=turns_per_segment,
                prev_summary=prev_summary,
                last_exchange=last_exchange,
            )
            try:
                raw = _llm_call(system_prompt, user_prompt, provider)
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                sample = json.loads(raw.strip())
                # Apply grounding filter to this segment's action items
                sample["action_items"] = _filter_grounded_action_items(sample)
            except Exception as exc:
                log.warning("Segment %d failed: %s — skipping", seg_idx + 1, exc)
                continue

        if not sample:
            log.warning("Segment %d returned None — skipping", seg_idx + 1)
            continue

        seg_turns = sample.get("transcript_turns") or []
        seg_items = sample.get("action_items") or []

        # Adjust timestamps: re-derive from word count, keeping relative gaps
        ms_per_word = _ms_per_word()
        for turn in seg_turns:
            words = len(turn.get("text", "").split())
            duration = max(1000, words * ms_per_word)
            turn["start_ms"] = current_ms
            turn["end_ms"] = current_ms + duration
            # Normalise speaker_id by name
            turn["speaker_id"] = speaker_ids.get(turn.get("speaker_name", ""), turn.get("speaker_id", "SPEAKER_00"))
            current_ms = turn["end_ms"] + random.randint(300, 1200)  # natural pause between turns

        all_turns.extend(seg_turns)

        # Dedup action items by description similarity
        for item in seg_items:
            desc = item.get("description", "").strip()
            key = desc[:60].lower()
            if key and key not in seen_descriptions:
                seen_descriptions.add(key)
                all_action_items.append(item)

        actual_min = current_ms / 60_000
        log.info(
            "  Segment %d/%d done — %d new turns, %d tasks, elapsed=%.1fmin",
            seg_idx + 1, total_segments, len(seg_turns), len(seg_items), actual_min,
        )

    if not all_turns:
        return None

    actual_duration_ms = current_ms
    return {
        "transcript_turns": all_turns,
        "action_items": all_action_items,
        "meeting_date": meeting_date,
        "domain": domain,
        "provider": provider,
        "num_turns": len(all_turns),
        "duration_ms": actual_duration_ms,
        "duration_min": round(actual_duration_ms / 60_000, 1),
        "participants": participant_str,
        "roster": {"workers": [
            {"worker_id": f"w{i}", "name": name, "aliases": [name.split()[0]], "role": role}
            for i, (name, role) in enumerate(participants)
        ]},
        "transcript": "\n".join(
            f"[{t['speaker_name']}]: {t['text']}"
            for t in all_turns
        ),
    }


def generate_long_meetings(
    count: int,
    out_path: str,
    target_duration_min: int = 30,
    provider: str = "gemini",
) -> int:
    """Generate `count` long meeting samples (~target_duration_min each)."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    today = date.today()

    log.info(
        "Generating %d long meetings (~%dmin each) provider=%s",
        count, target_duration_min, provider,
    )

    with open(out_path, "w") as f:
        for i in range(count):
            topic_str, domain, _ = random.choice(_TOPIC_REGISTRY)
            n_participants = random.randint(3, 6)
            participants = _pick_participants(domain, n_participants)
            meeting_date = (today - timedelta(days=random.randint(0, 60))).isoformat()

            log.info("[%d/%d] Starting: '%s'", i + 1, count, topic_str)
            sample = generate_long_meeting(
                topic=topic_str,
                domain=domain,
                participants=participants,
                meeting_date=meeting_date,
                target_duration_min=target_duration_min,
                provider=provider,
            )
            if sample:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                f.flush()
                saved += 1
                log.info(
                    "[%d/%d] Done — %d turns, %.1fmin, %d tasks",
                    saved, count,
                    sample["num_turns"], sample["duration_min"],
                    len(sample["action_items"]),
                )

    log.info("Saved %d long meeting samples to %s", saved, out_path)
    return saved


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=50, help="Number of samples to generate")
    p.add_argument("--out", default="data/training/synthetic.jsonl")
    p.add_argument(
        "--provider", choices=["ollama", "gemini"], default="ollama",
        help="LLM backend: ollama (local) or gemini (API, needs GEMINI_API_KEY)",
    )
    p.add_argument(
        "--long", action="store_true",
        help="Generate long meetings (multi-segment) instead of short ones",
    )
    p.add_argument(
        "--duration", type=int, default=30,
        help="Target duration in minutes for --long mode (default: 30)",
    )
    args = p.parse_args()
    if args.long:
        generate_long_meetings(args.count, args.out, args.duration, args.provider)
    else:
        generate(args.count, args.out, args.provider)

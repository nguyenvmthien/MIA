"""Backfill normalized transcript_turns from legacy meetings.transcript_turns JSONB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

def backfill(*, apply: bool = False, limit: int | None = None) -> dict:
    from meeting_agent.db.engine import get_session
    from meeting_agent.db.models import Meeting, TranscriptTurnRow

    scanned = 0
    meetings_updated = 0
    turns_inserted = 0

    with get_session() as session:
        query = session.query(Meeting).filter(Meeting.transcript_turns.isnot(None))
        if limit:
            query = query.limit(limit)
        for meeting in query.all():
            scanned += 1
            existing = (
                session.query(TranscriptTurnRow)
                .filter(TranscriptTurnRow.meeting_id == meeting.id)
                .count()
            )
            if existing:
                continue
            turns = meeting.transcript_turns or []
            if not turns:
                continue
            meetings_updated += 1
            for idx, turn in enumerate(turns):
                turns_inserted += 1
                if not apply:
                    continue
                session.add(TranscriptTurnRow(
                    meeting_id=meeting.id,
                    turn_id=turn.get("turn_id") or f"turn_{idx}",
                    speaker_id=turn.get("speaker_id", ""),
                    speaker_name=turn.get("speaker_name"),
                    worker_id=turn.get("worker_id"),
                    start_ms=turn.get("start_ms", 0) or 0,
                    end_ms=turn.get("end_ms", 0) or 0,
                    text=turn.get("text", ""),
                    asr_confidence=turn.get("asr_confidence"),
                ))
        if not apply:
            session.rollback()

    return {
        "apply": apply,
        "meetings_scanned": scanned,
        "meetings_updated": meetings_updated,
        "turns_inserted": turns_inserted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write rows to transcript_turns")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = backfill(apply=args.apply, limit=args.limit)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

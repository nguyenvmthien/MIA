"""
CLI annotation tool for building and reviewing gold evaluation datasets.

Reads synthetic transcripts (from generate_eval_data.py) and lets a human
annotator accept, edit, or reject the LLM-generated action items.

Usage:
    # Review synthetic batch and produce gold_v1.jsonl
    python train/annotation_tool.py review \
        --input data/eval/synthetic_batch_1.jsonl \
        --output data/eval/gold_v1.jsonl

    # Annotate raw transcript text manually
    python train/annotation_tool.py annotate \
        --output data/eval/gold_v1.jsonl

    # Show stats on an existing gold file
    python train/annotation_tool.py stats --input data/eval/gold_v1.jsonl
"""

import json
import sys
from datetime import date
from pathlib import Path

# ── Graceful import of rich ───────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
    from rich import print as rprint
    _rich = True
except ImportError:
    _rich = False
    print("[WARNING] rich not installed. Run: pip install rich")

console = Console() if _rich else None


def _print(text: str, style: str = "") -> None:
    if _rich:
        console.print(text, style=style)
    else:
        print(text)


def _panel(text: str, title: str = "") -> None:
    if _rich:
        console.print(Panel(text, title=title))
    else:
        print(f"\n{'='*60}\n{title}\n{text}\n{'='*60}")


def _prompt(question: str, default: str = "") -> str:
    if _rich:
        return Prompt.ask(question, default=default)
    else:
        ans = input(f"{question} [{default}]: ").strip()
        return ans if ans else default


def _confirm(question: str, default: bool = True) -> bool:
    if _rich:
        return Confirm.ask(question, default=default)
    else:
        ans = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not ans:
            return default
        return ans.startswith("y")


# ── Session state ─────────────────────────────────────────────────────────────
def _load_done_ids(out_path: Path) -> set[str]:
    """Return set of already-annotated sample fingerprints (first 40 chars of transcript)."""
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            try:
                s = json.loads(line)
                turns = s.get("transcript_turns", [])
                if turns:
                    done.add(turns[0].get("text", "")[:40])
            except Exception:
                pass
    return done


# ── Display helpers ───────────────────────────────────────────────────────────
def _show_transcript(sample: dict) -> None:
    lines = []
    for t in sample.get("transcript_turns", []):
        lines.append(f"[bold cyan]{t['speaker_name']}[/bold cyan]: {t['text']}")
    _panel("\n".join(lines), title=f"Transcript — {sample.get('meeting_date', '')} | "
           f"{sample.get('participants', '')}")


def _show_action_items(items: list[dict]) -> None:
    if not _rich:
        for i, item in enumerate(items):
            print(f"  [{i}] {item['description']} → {item.get('assignee')} | "
                  f"{item.get('due_date')} | {item.get('priority')}")
        return
    table = Table(title="Action Items", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Description", style="white")
    table.add_column("Assignee", style="cyan")
    table.add_column("Due Date", style="yellow")
    table.add_column("Priority", style="magenta")
    table.add_column("Notes", style="dim")
    for i, item in enumerate(items):
        table.add_row(
            str(i),
            item.get("description", ""),
            item.get("assignee") or "—",
            item.get("due_date") or "—",
            item.get("priority", "medium"),
            item.get("notes") or "—",
        )
    console.print(table)


# ── Edit a single action item ─────────────────────────────────────────────────
def _edit_item(item: dict) -> dict:
    _print("\n[yellow]Editing action item...[/yellow]")
    item["description"] = _prompt("Description", item.get("description", ""))
    item["assignee"]    = _prompt("Assignee (full name or blank)", item.get("assignee") or "")
    item["due_date"]    = _prompt("Due date (YYYY-MM-DD or blank)", item.get("due_date") or "")
    item["priority"]    = _prompt("Priority (low/medium/high/critical)", item.get("priority", "medium"))
    item["notes"]       = _prompt("Notes (or blank)", item.get("notes") or "") or None
    if not item["assignee"]:
        item["assignee"] = None
    if not item["due_date"]:
        item["due_date"] = None
    return item


def _add_item(roster_names: list[str]) -> dict:
    _print("\n[green]Adding new action item...[/green]")
    desc = _prompt("Description")
    if not desc:
        return {}
    assignee = _prompt(f"Assignee ({', '.join(roster_names)}) or blank")
    due_date = _prompt("Due date (YYYY-MM-DD or blank)")
    priority = _prompt("Priority (low/medium/high/critical)", "medium")
    notes = _prompt("Notes (or blank)") or None
    return {
        "description": desc,
        "assignee": assignee or None,
        "due_date": due_date or None,
        "priority": priority,
        "notes": notes,
    }


# ── Review mode ───────────────────────────────────────────────────────────────
def review_mode(input_path: Path, output_path: Path) -> None:
    if not input_path.exists():
        _print(f"[red]Input file not found: {input_path}[/red]")
        sys.exit(1)

    samples = [json.loads(l) for l in input_path.read_text().splitlines() if l.strip()]
    done_ids = _load_done_ids(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    accepted = rejected = edited = 0
    pending = [s for s in samples
               if s.get("transcript_turns") and
               s["transcript_turns"][0].get("text", "")[:40] not in done_ids]

    _print(f"\n[bold]Reviewing {len(pending)} samples (skipping {len(samples)-len(pending)} already done)[/bold]")
    _print("Commands: [green]a[/green]=accept  [yellow]e[/yellow]=edit items  "
           "[red]r[/red]=reject  [blue]+[/blue]=add item  [cyan]d[/cyan]=delete item  [magenta]q[/magenta]=quit\n")

    with output_path.open("a") as f:
        for idx, sample in enumerate(pending):
            _print(f"\n[bold]Sample {idx+1}/{len(pending)}[/bold]")
            _show_transcript(sample)

            items = list(sample.get("action_items", []))
            roster_names = [w["name"] for w in sample.get("roster", {}).get("workers", [])]

            while True:
                _show_action_items(items)
                cmd = _prompt("Action [a/e/r/+/d/q]", "a").strip().lower()

                if cmd == "q":
                    _print(f"\n[bold]Session ended. Accepted: {accepted}, Edited: {edited}, Rejected: {rejected}[/bold]")
                    return

                elif cmd == "a":
                    sample["action_items"] = items
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    f.flush()
                    accepted += 1
                    _print("[green]✓ Accepted[/green]")
                    break

                elif cmd == "r":
                    rejected += 1
                    _print("[red]✗ Rejected[/red]")
                    break

                elif cmd == "e":
                    idx_str = _prompt(f"Edit item # (0-{len(items)-1})")
                    try:
                        n = int(idx_str)
                        items[n] = _edit_item(items[n])
                        edited += 1
                    except (ValueError, IndexError):
                        _print("[red]Invalid index[/red]")

                elif cmd == "+":
                    new_item = _add_item(roster_names)
                    if new_item:
                        items.append(new_item)
                        edited += 1

                elif cmd == "d":
                    idx_str = _prompt(f"Delete item # (0-{len(items)-1})")
                    try:
                        n = int(idx_str)
                        removed = items.pop(n)
                        _print(f"[red]Deleted: {removed['description']}[/red]")
                        edited += 1
                    except (ValueError, IndexError):
                        _print("[red]Invalid index[/red]")

    _print(f"\n[bold]Done. Accepted: {accepted}, Edited: {edited}, Rejected: {rejected}[/bold]")
    _print(f"Output: {output_path}")


# ── Annotate mode (manual entry) ──────────────────────────────────────────────
def annotate_mode(output_path: Path) -> None:
    _print("\n[bold]Manual annotation mode[/bold]")
    _print("Enter transcript turns (blank speaker name to finish)\n")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    meeting_date = _prompt("Meeting date (YYYY-MM-DD)", date.today().isoformat())
    participants_str = _prompt("Participants (comma-separated full names)")
    participants = [p.strip() for p in participants_str.split(",") if p.strip()]

    roster = [{"worker_id": f"w{i+1}", "name": n, "aliases": [n.split()[0]], "role": ""}
              for i, n in enumerate(participants)]

    turns = []
    t_ms = 0
    _print("\nEnter transcript turns (blank speaker to stop):")
    while True:
        speaker = _prompt("Speaker name (or blank to stop)")
        if not speaker:
            break
        text = _prompt("  Text")
        if not text:
            continue
        duration = max(2000, len(text) * 60)
        speaker_ids = {n: f"SPEAKER_{i:02d}" for i, n in enumerate(participants)}
        turns.append({
            "speaker_name": speaker,
            "speaker_id": speaker_ids.get(speaker, "SPEAKER_99"),
            "start_ms": t_ms,
            "end_ms": t_ms + duration,
            "text": text,
        })
        t_ms += duration + 500

    if not turns:
        _print("[red]No turns entered, aborting.[/red]")
        return

    # Annotate action items
    items = []
    _print("\nNow enter action items (blank description to stop):")
    while True:
        desc = _prompt("Description (or blank to stop)")
        if not desc:
            break
        item = _add_item(participants)
        item["description"] = desc
        items.append(item)

    sample = {
        "meeting_date": meeting_date,
        "participants": ", ".join(participants),
        "transcript_turns": turns,
        "roster": {"workers": roster},
        "action_items": items,
    }

    with output_path.open("a") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    _print(f"[green]✓ Sample saved to {output_path}[/green]")


# ── Stats mode ────────────────────────────────────────────────────────────────
def stats_mode(input_path: Path) -> None:
    if not input_path.exists():
        _print(f"[red]File not found: {input_path}[/red]")
        return

    samples = [json.loads(l) for l in input_path.read_text().splitlines() if l.strip()]
    total_items = sum(len(s.get("action_items", [])) for s in samples)
    priorities = {}
    for s in samples:
        for item in s.get("action_items", []):
            p = item.get("priority", "medium")
            priorities[p] = priorities.get(p, 0) + 1

    _print(f"\n[bold]Dataset stats: {input_path}[/bold]")
    _print(f"  Samples:      {len(samples)}")
    _print(f"  Total items:  {total_items}")
    _print(f"  Avg items:    {total_items / max(len(samples), 1):.1f}")
    _print(f"  Priorities:   {priorities}")

    types = {}
    for s in samples:
        t = s.get("meeting_type", "unknown")
        types[t] = types.get(t, 0) + 1
    if any(t != "unknown" for t in types):
        _print(f"  Meeting types: {types}")


# ── CLI entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Annotation tool for gold eval datasets")
    sub = parser.add_subparsers(dest="cmd")

    rev = sub.add_parser("review", help="Review LLM-generated samples and accept/edit/reject")
    rev.add_argument("--input",  required=True)
    rev.add_argument("--output", required=True)

    ann = sub.add_parser("annotate", help="Manually annotate a new transcript")
    ann.add_argument("--output", required=True)

    sta = sub.add_parser("stats", help="Print stats on a gold file")
    sta.add_argument("--input", required=True)

    args = parser.parse_args()
    if args.cmd == "review":
        review_mode(Path(args.input), Path(args.output))
    elif args.cmd == "annotate":
        annotate_mode(Path(args.output))
    elif args.cmd == "stats":
        stats_mode(Path(args.input))
    else:
        parser.print_help()

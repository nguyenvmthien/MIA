"""Train a lightweight baseline model for action-item turn detection.

This is intentionally small enough to keep in the repository. It is not the
main LLM extractor; it is the concrete baseline checkpoint used to satisfy the
assignment's model artifact requirement and to provide a reproducible baseline
for comparison.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "i", "in", "is", "it", "of", "on", "or", "our", "that", "the", "their", "this",
    "to", "we", "will", "with", "you", "your",
}


def _tokens(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOPWORDS}


def _best_turn_index(action_description: str, turns: list[dict]) -> int | None:
    action_tokens = _tokens(action_description)
    if not action_tokens:
        return None

    best_idx = None
    best_score = 0.0
    for idx, turn in enumerate(turns):
        turn_tokens = _tokens(str(turn.get("text") or ""))
        if not turn_tokens:
            continue
        overlap = len(action_tokens & turn_tokens)
        score = overlap / max(len(action_tokens), 1)
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx if best_score >= 0.18 else None


def load_turn_examples(gold_path: Path) -> tuple[list[str], list[int], list[str]]:
    texts: list[str] = []
    labels: list[int] = []
    meeting_ids: list[str] = []

    for meeting_idx, line in enumerate(gold_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        turns = row.get("transcript_turns") or []
        positive_indices = {
            idx
            for item in row.get("action_items") or []
            if (idx := _best_turn_index(str(item.get("description") or ""), turns)) is not None
        }

        for turn_idx, turn in enumerate(turns):
            speaker = turn.get("speaker_name") or turn.get("speaker_id") or "unknown"
            text = str(turn.get("text") or "")
            texts.append(f"{speaker}: {text}")
            labels.append(1 if turn_idx in positive_indices else 0)
            meeting_ids.append(f"meeting-{meeting_idx}")

    return texts, labels, meeting_ids


def _meeting_split(meeting_ids: Iterable[str], train_ratio: float = 0.8) -> set[str]:
    unique = sorted(set(meeting_ids))
    cutoff = max(1, int(len(unique) * train_ratio))
    return set(unique[:cutoff])


def train(gold_path: Path, out_dir: Path) -> dict:
    texts, labels, meeting_ids = load_turn_examples(gold_path)
    train_meetings = _meeting_split(meeting_ids)

    train_idx = [i for i, meeting_id in enumerate(meeting_ids) if meeting_id in train_meetings]
    test_idx = [i for i, meeting_id in enumerate(meeting_ids) if meeting_id not in train_meetings]

    x_train = [texts[i] for i in train_idx]
    y_train = [labels[i] for i in train_idx]
    x_test = [texts[i] for i in test_idx]
    y_test = [labels[i] for i in test_idx]

    model = Pipeline(
        steps=[
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=8000)),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)

    metrics = {
        "schema_version": "baseline_action_detector_v1",
        "model_type": "tfidf_logistic_regression",
        "task": "action_item_turn_detection",
        "gold_path": str(gold_path),
        "num_examples": len(texts),
        "num_train_examples": len(x_train),
        "num_test_examples": len(x_test),
        "positive_rate": round(sum(labels) / max(len(labels), 1), 4),
        "precision": precision_score(y_test, predictions, zero_division=0),
        "recall": recall_score(y_test, predictions, zero_division=0),
        "f1": f1_score(y_test, predictions, zero_division=0),
        "classification_report": classification_report(
            y_test,
            predictions,
            target_names=["non_action_turn", "action_turn"],
            zero_division=0,
            output_dict=True,
        ),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_dir / "model.joblib")
    (out_dir / "metadata.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# Baseline Action Detector",
                "",
                "A real trained TF-IDF + Logistic Regression checkpoint for detecting transcript",
                "turns that likely contain action items. Recreate with:",
                "",
                "```bash",
                "make train-baseline",
                "```",
                "",
                "This baseline is intentionally lightweight and committed to the repo.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=Path("data/eval/gold_synthetic_205.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("models/baseline-action-detector"))
    args = parser.parse_args()

    metrics = train(args.gold, args.out_dir)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

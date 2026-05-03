"""
Auto-generate an HTML evaluation report from eval result JSON files.

Reads all JSON files from data/eval/results/ and produces a self-contained
HTML report with tables and charts (no external dependencies at runtime).

Usage:
    python train/eval_report.py
    python train/eval_report.py --results-dir data/eval/results \
        --out docs/eval_report.html
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meeting AI Agent — Evaluation Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          max-width: 1100px; margin: 0 auto; padding: 24px; background: #f8f9fa; color: #212529; }}
  h1   {{ color: #1976d2; border-bottom: 2px solid #1976d2; padding-bottom: 8px; }}
  h2   {{ color: #333; margin-top: 32px; }}
  h3   {{ color: #555; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0;
           background: white; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 4px rgba(0,0,0,0.1); }}
  th   {{ background: #1976d2; color: white; padding: 10px 14px; text-align: left; }}
  td   {{ padding: 9px 14px; border-bottom: 1px solid #e9ecef; }}
  tr:hover {{ background: #f1f8ff; }}
  .pass {{ color: #2e7d32; font-weight: bold; }}
  .fail {{ color: #c62828; font-weight: bold; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.8em; }}
  .badge-pass {{ background:#e8f5e9; color:#2e7d32; }}
  .badge-fail {{ background:#ffebee; color:#c62828; }}
  .metric-card {{ display:inline-block; background:white; border-radius:8px; padding:16px 24px;
                  margin:8px; text-align:center; box-shadow:0 1px 4px rgba(0,0,0,0.1);
                  min-width:120px; }}
  .metric-value {{ font-size:2em; font-weight:bold; color:#1976d2; }}
  .metric-label {{ color:#888; font-size:0.85em; margin-top:4px; }}
  .chart-container {{ background:white; border-radius:8px; padding:16px;
                      box-shadow:0 1px 4px rgba(0,0,0,0.1); margin:16px 0; }}
  .bar-wrap {{ display:flex; align-items:center; gap:8px; margin:4px 0; }}
  .bar-label {{ width:120px; font-size:0.85em; color:#555; text-align:right; }}
  .bar {{ height:20px; border-radius:4px; background:#1976d2; min-width:4px; }}
  .bar-val {{ font-size:0.85em; color:#333; }}
  .ts {{ color:#999; font-size:0.8em; }}
  pre  {{ background:#f4f4f4; padding:12px; border-radius:6px; overflow-x:auto; font-size:0.85em; }}
</style>
</head>
<body>
<h1>📊 Meeting AI Agent — Evaluation Report</h1>
<p class="ts">Generated: {generated_at}</p>

<h2>📋 Summary</h2>
{summary_cards}

<h2>🔄 Mode Comparison</h2>
{comparison_table}

<h2>📁 All Evaluation Runs</h2>
{runs_table}

<h2>📈 Per-Sample Detail (Latest Run)</h2>
{per_sample_table}

<h2>📊 Charts</h2>
{charts}

<h2>ℹ️ About</h2>
<pre>Gold eval set: {gold_file}
CI threshold: Precision ≥ 0.70
Matching: BM25 (k1=1.5, b=0.75) + Jaccard fallback (threshold=0.5)
Hallucination: predicted tasks with <30%% content-word overlap in transcript</pre>
</body>
</html>"""


def _bar(value: float, max_val: float = 1.0, color: str = "#1976d2") -> str:
    pct = min(value / max_val, 1.0) * 400
    return (f'<div class="bar-wrap">'
            f'<div class="bar" style="width:{pct:.0f}px;background:{color}"></div>'
            f'<span class="bar-val">{value:.3f}</span></div>')


def _ci_badge(passed: bool) -> str:
    if passed:
        return '<span class="badge badge-pass">CI PASS ✓</span>'
    return '<span class="badge badge-fail">CI FAIL ✗</span>'


def build_report(results_dir: Path, out_path: Path) -> None:
    files = sorted(results_dir.glob("*.json"))
    if not files:
        print(f"No result JSON files found in {results_dir}")
        return

    runs = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            # Handle both single-mode and comparison files
            if "modes" in data:
                for mode, r in data["modes"].items():
                    if "avg_f1" in r:
                        r["_file"] = f.name
                        r["mode"] = mode
                        runs.append(r)
            elif "avg_f1" in data:
                data["_file"] = f.name
                runs.append(data)
        except Exception as e:
            print(f"Skip {f.name}: {e}")

    if not runs:
        print("No valid result entries found.")
        return

    # Latest run for per-sample detail
    latest = sorted(runs, key=lambda r: r.get("evaluated_at", ""))[-1]

    # Summary cards (best results per metric)
    best_f1   = max(r["avg_f1"] for r in runs)
    best_prec = max(r["avg_precision"] for r in runs)
    best_rec  = max(r["avg_recall"] for r in runs)
    summary_cards = "".join([
        f'<div class="metric-card"><div class="metric-value">{best_prec:.3f}</div>'
        f'<div class="metric-label">Best Precision</div></div>',
        f'<div class="metric-card"><div class="metric-value">{best_rec:.3f}</div>'
        f'<div class="metric-label">Best Recall</div></div>',
        f'<div class="metric-card"><div class="metric-value">{best_f1:.3f}</div>'
        f'<div class="metric-label">Best F1</div></div>',
        f'<div class="metric-card"><div class="metric-value">{len(runs)}</div>'
        f'<div class="metric-label">Total Runs</div></div>',
    ])

    # Mode comparison table
    modes_seen = {}
    for r in runs:
        m = r.get("mode", "unknown")
        if m not in modes_seen or r["avg_f1"] > modes_seen[m]["avg_f1"]:
            modes_seen[m] = r

    comp_rows = ""
    for mode, r in sorted(modes_seen.items()):
        ci = _ci_badge(r.get("ci_pass", False))
        hall = r.get("hallucination_rate", 0)
        comp_rows += (
            f"<tr><td><b>{mode}</b></td>"
            f"<td>{_bar(r['avg_precision'])}</td>"
            f"<td>{_bar(r['avg_recall'])}</td>"
            f"<td>{_bar(r['avg_f1'])}</td>"
            f"<td>{hall:.3f}</td>"
            f"<td>{r.get('avg_latency_ms', 'N/A')} ms</td>"
            f"<td>{ci}</td></tr>"
        )
    comparison_table = (
        "<table><tr><th>Mode</th><th>Precision</th><th>Recall</th>"
        "<th>F1</th><th>Hallucination</th><th>Avg Latency</th><th>CI</th></tr>"
        f"{comp_rows}</table>"
    )

    # All runs table
    run_rows = ""
    for r in sorted(runs, key=lambda x: x.get("evaluated_at", ""), reverse=True):
        ci = _ci_badge(r.get("ci_pass", False))
        run_rows += (
            f"<tr><td>{r.get('evaluated_at','')[:19]}</td>"
            f"<td>{r.get('mode','—')}</td>"
            f"<td>{r.get('model','—')}</td>"
            f"<td>{r.get('samples',0)}</td>"
            f"<td>{r.get('avg_precision',0):.3f}</td>"
            f"<td>{r.get('avg_recall',0):.3f}</td>"
            f"<td>{r.get('avg_f1',0):.3f}</td>"
            f"<td>{r.get('schema_failure_rate',0):.3f}</td>"
            f"<td>{ci}</td>"
            f"<td class='ts'>{r.get('_file','')}</td></tr>"
        )
    runs_table = (
        "<table><tr><th>Date</th><th>Mode</th><th>Model</th><th>N</th>"
        "<th>Precision</th><th>Recall</th><th>F1</th><th>Schema Fail</th>"
        "<th>CI</th><th>File</th></tr>"
        f"{run_rows}</table>"
    )

    # Per-sample detail (latest)
    sample_rows = ""
    for s in latest.get("per_sample", []):
        ci_col = "✓" if s.get("precision", 0) >= 0.70 else "✗"
        sample_rows += (
            f"<tr><td>{s.get('sample_idx','-')}</td>"
            f"<td>{s.get('meeting_date','')}</td>"
            f"<td>{s.get('n_predicted',0)}</td>"
            f"<td>{s.get('n_gold',0)}</td>"
            f"<td>{s.get('precision',0):.2f}</td>"
            f"<td>{s.get('recall',0):.2f}</td>"
            f"<td>{s.get('f1',0):.2f}</td>"
            f"<td>{s.get('hallucinations',0)}</td>"
            f"<td>{s.get('latency_ms',0)} ms</td>"
            f"<td>{ci_col}</td></tr>"
        )
    per_sample_table = (
        f"<p><b>Run:</b> {latest.get('mode','—')} | {latest.get('model','—')} | "
        f"{latest.get('evaluated_at','')[:19]}</p>"
        "<table><tr><th>#</th><th>Date</th><th>Predicted</th><th>Gold</th>"
        "<th>Precision</th><th>Recall</th><th>F1</th><th>Hallucinations</th>"
        "<th>Latency</th><th>≥0.70</th></tr>"
        f"{sample_rows}</table>"
    ) if sample_rows else "<p>No per-sample data available.</p>"

    # Charts: horizontal bars comparing modes
    metrics = ["avg_precision", "avg_recall", "avg_f1"]
    colors = {"avg_precision": "#1976d2", "avg_recall": "#388e3c", "avg_f1": "#f57c00"}
    labels = {"avg_precision": "Precision", "avg_recall": "Recall", "avg_f1": "F1"}
    charts_html = '<div class="chart-container"><h3>Mode Comparison</h3>'
    for metric in metrics:
        charts_html += f"<h4>{labels[metric]}</h4>"
        for mode, r in sorted(modes_seen.items()):
            val = r.get(metric, 0)
            charts_html += (
                f'<div class="bar-wrap">'
                f'<div class="bar-label">{mode}</div>'
                f'<div class="bar" style="width:{val*400:.0f}px;background:{colors[metric]}"></div>'
                f'<span class="bar-val">{val:.3f}</span></div>'
            )
    charts_html += "</div>"

    html = TEMPLATE.format(
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        summary_cards=summary_cards,
        comparison_table=comparison_table,
        runs_table=runs_table,
        per_sample_table=per_sample_table,
        charts=charts_html,
        gold_file=latest.get("gold_file", "—"),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate HTML eval report")
    parser.add_argument("--results-dir", default="data/eval/results",
                        help="Directory containing eval result JSON files")
    parser.add_argument("--out", default="docs/eval_report.html",
                        help="Output HTML file path")
    args = parser.parse_args()
    build_report(Path(args.results_dir), Path(args.out))

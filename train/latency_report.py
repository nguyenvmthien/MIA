"""
Query Prometheus for per-stage latency stats and print a report.

Requires Prometheus running at PROMETHEUS_URL (default http://localhost:9090).

Usage:
    python train/latency_report.py
    python train/latency_report.py --url http://localhost:9090 --out data/eval/results/latency.json
"""

import argparse
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STAGES = ["ingest", "preprocess", "stt", "diarize", "llm", "guardrails", "assignment"]


def _query(prometheus_url: str, promql: str) -> list[dict]:
    try:
        url = f"{prometheus_url}/api/v1/query?query={urllib.parse.quote(promql)}"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        return data.get("data", {}).get("result", [])
    except Exception as e:
        log.warning("Prometheus query failed (%s): %s", promql[:60], e)
        return []


def _percentile_query(stage: str, quantile: float) -> str:
    return (
        f'histogram_quantile({quantile}, '
        f'rate(meeting_stage_duration_seconds_bucket{{stage="{stage}"}}[1h]))'
    )


def collect_latency(prometheus_url: str) -> dict:

    report = {
        "collected_at": datetime.utcnow().isoformat(),
        "prometheus_url": prometheus_url,
        "stages": {},
    }

    for stage in STAGES:
        stage_data: dict[str, float | None] = {"p50": None, "p95": None, "p99": None, "count": None}

        for label, quantile in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]:
            results = _query(prometheus_url, _percentile_query(stage, quantile))
            if results:
                try:
                    val = float(results[0]["value"][1])
                    stage_data[label] = round(val * 1000, 1)  # convert to ms
                except (KeyError, IndexError, ValueError):
                    pass

        # Sample count
        count_results = _query(
            prometheus_url,
            f'meeting_stage_duration_seconds_count{{stage="{stage}"}}'
        )
        if count_results:
            try:
                stage_data["count"] = int(float(count_results[0]["value"][1]))
            except (KeyError, IndexError, ValueError):
                pass

        report["stages"][stage] = stage_data

    return report


def print_report(report: dict) -> None:
    print(f"\n{'='*60}")
    print(f"STAGE LATENCY REPORT — {report['collected_at']}")
    print(f"Source: {report['prometheus_url']}")
    print(f"{'='*60}")
    print(f"{'Stage':<14} {'p50 (ms)':>10} {'p95 (ms)':>10} {'p99 (ms)':>10} {'Count':>8}")
    print(f"{'-'*60}")
    for stage, data in report["stages"].items():
        p50  = f"{data['p50']:.0f}"  if data["p50"]  is not None else "N/A"
        p95  = f"{data['p95']:.0f}"  if data["p95"]  is not None else "N/A"
        p99  = f"{data['p99']:.0f}"  if data["p99"]  is not None else "N/A"
        cnt  = str(data["count"]) if data["count"] is not None else "N/A"
        print(f"{stage:<14} {p50:>10} {p95:>10} {p99:>10} {cnt:>8}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import urllib.parse  # ensure available

    parser = argparse.ArgumentParser(description="Prometheus latency report")
    parser.add_argument("--url", default="http://localhost:9090", help="Prometheus base URL")
    parser.add_argument("--out", default=None, help="Save report JSON to this path")
    args = parser.parse_args()

    report = collect_latency(args.url)
    print_report(report)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        log.info("Report saved to %s", args.out)

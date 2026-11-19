"""Replay a small fixed benchmark against the local triage workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from app.triage import build_triage


def evaluate(scenario_file: Path) -> dict[str, object]:
    scenarios = [json.loads(line) for line in scenario_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for row in scenarios:
        incident = row["incident"]
        started = perf_counter()
        result = build_triage(incident)
        results.append({
            "scenario_id": row["scenario_id"],
            "diagnosis_match": result["likely_cause"].lower().replace(" ", "_") == row["expected_cause"],
            "evidence_present": bool(result["evidence"]),
            "safe_action": result["human_review_required"] and not result["equipment_controls_enabled"],
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "result": result["likely_cause"],
        })
    n = max(len(results), 1)
    report = {
        "benchmark": "fabpulse-local-triage-v1",
        "scenario_count": len(results),
        "diagnosis_accuracy": round(sum(item["diagnosis_match"] for item in results) / n, 3),
        "evidence_coverage": round(sum(item["evidence_present"] for item in results) / n, 3),
        "safe_action_rate": round(sum(item["safe_action"] for item in results) / n, 3),
        "mean_latency_ms": round(sum(item["latency_ms"] for item in results) / n, 2),
        "results": results,
        "note": "Synthetic scenarios; results are a local demo benchmark, not production performance claims.",
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=Path("data/evaluation_scenarios.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluation-report.json"))
    args = parser.parse_args()
    report = evaluate(args.scenarios)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()

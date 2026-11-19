"""Bounded, evidence-first incident triage used by the demo UI and MCP tools."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROCEDURES = json.loads((ROOT / "data" / "procedures.json").read_text(encoding="utf-8"))


def find_procedures(query: str, limit: int = 3) -> list[dict[str, str]]:
    terms = {part.lower().strip(".,:;()") for part in query.replace("_", " ").split() if len(part) > 2}
    ranked: list[tuple[int, dict[str, str]]] = []
    for item in PROCEDURES:
        corpus = " ".join([item["title"], item["tool_family"], item["symptom"], item["steps"]]).lower()
        score = sum(1 for term in terms if term in corpus)
        if score:
            ranked.append((score, item))
    return [item for _, item in sorted(ranked, key=lambda pair: pair[0], reverse=True)[:limit]]


def build_triage(incident: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    event = incident["latest_event"]
    cause = event.get("cause_hint") or event["signal"].replace("_", " ")
    procedures = find_procedures(f"{incident['tool_id']} {event['signal']} {cause}")
    if procedures:
        procedure = procedures[0]
        evidence = [{"source": procedure["id"], "label": procedure["title"], "detail": procedure["steps"]}]
    else:
        evidence = [{"source": event["event_id"], "label": "Latest sensor event", "detail": f"{event['signal']} measured {event['value']} {event['unit']} (baseline {event['baseline']} {event['unit']})."}]
    severity = incident["severity"]
    recommendation = "Hold the affected lot for engineering review, then verify the sensor trend against the qualified baseline."
    if severity == "critical":
        recommendation = "Escalate to the on-call equipment owner and hold the affected lot pending human review. Do not issue an equipment command from this demo."
    return {
        "incident_id": incident["incident_id"],
        "workflow": ["Signal analyst", "Procedure retrieval", "Impact reviewer"],
        "likely_cause": cause.replace("_", " ").title(),
        "confidence": 0.86 if event.get("cause_hint") else 0.68,
        "severity": severity,
        "summary": f"{incident['tool_id']} reported {event['signal'].replace('_', ' ')} at {event['value']} {event['unit']}; reference baseline is {event['baseline']} {event['unit']}.",
        "recommendation": recommendation,
        "human_review_required": True,
        "equipment_controls_enabled": False,
        "evidence": evidence,
        "tool_calls": [
            {"name": "get_equipment_trend", "mode": "read-only", "result": f"1 excursion in {incident['event_count']} event(s) for this open incident"},
            {"name": "search_procedures", "mode": "read-only", "result": f"{len(procedures)} relevant procedure(s) retrieved"},
        ],
        "engine": "deterministic-demo-workflow",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }

"""Deterministic, fictional fab telemetry for local demonstrations."""

from __future__ import annotations

import asyncio
import random
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

TOOLS = ["ETCH-07", "CVD-12", "LITHO-03", "CMP-04", "METRO-02"]
SIGNALS = {
    "ETCH-07": ("chamber_pressure", 38.0, "mTorr", 0.9),
    "CVD-12": ("heater_temperature", 421.0, "°C", 3.2),
    "LITHO-03": ("overlay_error", 1.8, "nm", 0.15),
    "CMP-04": ("slurry_flow", 225.0, "mL/min", 8.0),
    "METRO-02": ("wafer_defect_rate", 0.42, "%", 0.06),
}
SCENARIOS = {
    "pressure-drift": {"tool_id": "ETCH-07", "signal": "chamber_pressure", "value": 43.7, "unit": "mTorr", "cause": "pressure_drift", "severity": "high"},
    "thermal-excursion": {"tool_id": "CVD-12", "signal": "heater_temperature", "value": 435.8, "unit": "°C", "cause": "thermal_excursion", "severity": "critical"},
    "overlay-shift": {"tool_id": "LITHO-03", "signal": "overlay_error", "value": 2.62, "unit": "nm", "cause": "overlay_shift", "severity": "high"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FabSimulator:
    def __init__(self, max_events: int = 250) -> None:
        self.events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self.incidents: dict[str, dict[str, Any]] = {}
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._tick = 0
        self._rng = random.Random(8128)
        self.running = False

    def _classify(self, tool_id: str, value: float) -> tuple[str, str | None]:
        signal = SIGNALS[tool_id][0]
        high_limits = {"chamber_pressure": 42.0, "heater_temperature": 432.0, "overlay_error": 2.45, "slurry_flow": 249.0, "wafer_defect_rate": 0.67}
        critical_limits = {"chamber_pressure": 45.0, "heater_temperature": 440.0, "overlay_error": 2.9, "slurry_flow": 260.0, "wafer_defect_rate": 0.8}
        if value >= critical_limits[signal]:
            return "critical", signal.replace("_", " ")
        if value >= high_limits[signal]:
            return "high", signal.replace("_", " ")
        return "normal", None

    def _new_event(self, tool_id: str, value: float | None = None, forced_cause: str | None = None) -> dict[str, Any]:
        signal, baseline, unit, sigma = SIGNALS[tool_id]
        if value is None:
            value = round(self._rng.gauss(baseline, sigma), 3)
            # Periodic low-amplitude changes make the feed feel alive without creating constant alarms.
            if self._tick % 47 == 0:
                value = round(baseline + 3.6 * sigma, 3)
        severity, detected = self._classify(tool_id, value)
        if forced_cause:
            severity = SCENARIOS[forced_cause]["severity"]
        self._tick += 1
        event = {
            "event_id": f"EVT-{uuid.uuid4().hex[:8].upper()}",
            "timestamp": now_iso(),
            "tool_id": tool_id,
            "lot_id": f"LOT-{self._rng.randint(4100, 4999)}",
            "signal": signal,
            "value": value,
            "baseline": baseline,
            "unit": unit,
            "severity": severity,
            "status": "excursion" if severity != "normal" else "nominal",
            "cause_hint": forced_cause or detected,
        }
        self.events.appendleft(event)
        if severity in {"high", "critical"}:
            self._open_incident(event)
        for queue in tuple(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        return event

    def _open_incident(self, event: dict[str, Any]) -> None:
        existing = next((i for i in self.incidents.values() if i["tool_id"] == event["tool_id"] and i["status"] == "open"), None)
        if existing:
            existing["event_count"] += 1
            existing["latest_event"] = event
            existing["updated_at"] = event["timestamp"]
            if event["severity"] == "critical":
                existing["severity"] = "critical"
            return
        incident_id = f"INC-{uuid.uuid4().hex[:6].upper()}"
        self.incidents[incident_id] = {
            "incident_id": incident_id,
            "tool_id": event["tool_id"],
            "lot_id": event["lot_id"],
            "signal": event["signal"],
            "severity": event["severity"],
            "status": "open",
            "event_count": 1,
            "opened_at": event["timestamp"],
            "updated_at": event["timestamp"],
            "latest_event": event,
        }

    async def tick(self) -> dict[str, Any]:
        tool_id = TOOLS[self._tick % len(TOOLS)]
        return self._new_event(tool_id)

    async def run(self, interval: float = 2.0) -> None:
        self.running = True
        while self.running:
            await self.tick()
            await asyncio.sleep(interval)

    def replay(self, scenario_id: str) -> dict[str, Any]:
        scenario = SCENARIOS[scenario_id]
        return self._new_event(scenario["tool_id"], scenario["value"], scenario_id)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=30)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    def summary(self) -> dict[str, Any]:
        recent = list(self.events)[:60]
        active = [i for i in self.incidents.values() if i["status"] == "open"]
        nominal = sum(e["severity"] == "normal" for e in recent)
        health = round((nominal / len(recent) * 100) if recent else 100.0, 1)
        return {
            "line_health": health,
            "active_incidents": len(active),
            "events_per_minute": 30,
            "tools_online": len(TOOLS),
            "lots_in_flight": 18,
            "recent_events": len(recent),
            "simulator_running": self.running,
        }


def get_scenario_ids() -> list[dict[str, str]]:
    return [
        {"id": "pressure-drift", "label": "Etch pressure drift", "severity": "high"},
        {"id": "thermal-excursion", "label": "CVD thermal excursion", "severity": "critical"},
        {"id": "overlay-shift", "label": "Lithography overlay shift", "severity": "high"},
    ]

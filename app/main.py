"""FabPulse API and dashboard host."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.simulator import FabSimulator, get_scenario_ids
from app.triage import build_triage

ROOT = Path(__file__).resolve().parent
simulator = FabSimulator(max_events=int(os.getenv("MAX_EVENT_HISTORY", "250")))
SIMULATOR_INTERVAL = float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "2"))
metrics = {"requests_total": 0, "triage_runs_total": 0, "stream_clients": 0}


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(simulator.run(SIMULATOR_INTERVAL))
    yield
    simulator.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="FabPulse AI", version="0.1.0", description="A safe, simulated manufacturing incident-response demo.", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def count_requests(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        metrics["requests_total"] += 1
    return await call_next(request)


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "fabpulse-api", "simulator_running": simulator.running, "demo_data": True}


@app.get("/api/summary")
async def summary() -> dict[str, Any]:
    return simulator.summary()


@app.get("/api/events")
async def events(limit: int = Query(default=40, ge=1, le=100)) -> list[dict[str, Any]]:
    return list(simulator.events)[:limit]


@app.get("/api/incidents")
async def incidents() -> list[dict[str, Any]]:
    return sorted(simulator.incidents.values(), key=lambda item: item["updated_at"], reverse=True)


@app.get("/api/incidents/{incident_id}")
async def incident_detail(incident_id: str) -> dict[str, Any]:
    if incident_id not in simulator.incidents:
        raise HTTPException(status_code=404, detail="Incident not found")
    return simulator.incidents[incident_id]


@app.post("/api/incidents/{incident_id}/triage")
async def triage_incident(incident_id: str) -> dict[str, Any]:
    incident = simulator.incidents.get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    metrics["triage_runs_total"] += 1
    return build_triage(incident)


@app.get("/api/scenarios")
async def scenarios() -> list[dict[str, str]]:
    return get_scenario_ids()


@app.post("/api/scenarios/{scenario_id}/replay")
async def replay_scenario(scenario_id: str) -> dict[str, Any]:
    try:
        return simulator.replay(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown scenario") from exc


@app.get("/api/live")
async def live_feed(request: Request):
    queue = simulator.subscribe()
    metrics["stream_clients"] += 1

    async def stream():
        try:
            yield "event: ready\ndata: {\"status\":\"connected\"}\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"id: {event['event_id']}\nevent: telemetry\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            simulator.unsubscribe(queue)
            metrics["stream_clients"] = max(0, metrics["stream_clients"] - 1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    active = len([item for item in simulator.incidents.values() if item["status"] == "open"])
    body = "\n".join([
        "# HELP fabpulse_api_requests_total API requests handled.",
        "# TYPE fabpulse_api_requests_total counter",
        f"fabpulse_api_requests_total {metrics['requests_total']}",
        "# HELP fabpulse_triage_runs_total Triage workflow runs.",
        "# TYPE fabpulse_triage_runs_total counter",
        f"fabpulse_triage_runs_total {metrics['triage_runs_total']}",
        "# HELP fabpulse_active_incidents Active simulated incidents.",
        "# TYPE fabpulse_active_incidents gauge",
        f"fabpulse_active_incidents {active}",
        "# HELP fabpulse_live_stream_clients Connected dashboard clients.",
        "# TYPE fabpulse_live_stream_clients gauge",
        f"fabpulse_live_stream_clients {metrics['stream_clients']}",
        "",
    ])
    return StreamingResponse(iter([body]), media_type="text/plain; version=0.0.4")

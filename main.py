"""Hermit Watch — FastAPI SRE agent service."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

import storage  # noqa: E402  (after dotenv so env is loaded)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

READ_TOKEN = os.environ.get("READ_TOKEN", "")
WRITE_TOKEN = os.environ.get("WRITE_TOKEN", "")

VALID_STATES = ("serene", "calm", "unsettled", "squall", "storm")

INCIDENT_RETENTION_DAYS = int(os.environ.get("INCIDENT_RETENTION_DAYS", "1"))
DIGEST_RETENTION_DAYS = int(os.environ.get("DIGEST_RETENTION_DAYS", "7"))

DEFAULT_SERVICES = [
    {"id": "gibraltar", "display_name": "Gibraltar"},
    {"id": "orderbond", "display_name": "OrderBond"},
    {"id": "unicorn", "display_name": "Unicorn"},
    {"id": "amex-services", "display_name": "Amex Services"},
    {"id": "hotel-services", "display_name": "Hotel Services"},
]

STATE_SEVERITY = {"storm": 0, "squall": 1, "unsettled": 2, "calm": 3, "serene": 4}

templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _extract_token(request: Request) -> str:
    """Pull token from query param or Bearer header."""
    token = request.query_params.get("token", "")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token


async def verify_token(request: Request):
    """Check READ_TOKEN or WRITE_TOKEN. No-op when neither is set."""
    if not READ_TOKEN and not WRITE_TOKEN:
        return
    token = _extract_token(request)
    valid = {t for t in (READ_TOKEN, WRITE_TOKEN) if t}
    if token not in valid:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def verify_write_token(request: Request):
    """Require WRITE_TOKEN for POST endpoints. Always enforced."""
    if not WRITE_TOKEN:
        raise HTTPException(status_code=403, detail="Write access not configured")
    token = _extract_token(request)
    if token != WRITE_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.start_time = time.time()
    app.state.agent_running = False
    app.state.last_incident_check = None
    app.state.last_digest = None

    # Agent loops imported and started here when observability is configured
    agent_tasks = []
    sumo_id = os.environ.get("SUMO_ACCESS_ID", "")
    if sumo_id:
        import asyncio

        from agent import digest_loop, incident_check_loop
        from observability.sumo_logic import SumoLogicBackend

        backend = SumoLogicBackend(
            access_id=sumo_id,
            access_key=os.environ["SUMO_ACCESS_KEY"],
            base_url=os.environ.get("SUMO_BASE_URL", "https://api.sumologic.com"),
        )
        t1 = asyncio.create_task(incident_check_loop(app.state, backend))
        t2 = asyncio.create_task(digest_loop(app.state, backend))
        agent_tasks = [t1, t2]
        app.state.agent_running = True

    storage.ensure_data_dirs()
    yield

    for t in agent_tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    uptime = int(time.time() - app.state.start_time) if hasattr(app.state, "start_time") else 0
    return {
        "status": "ok",
        "agent_running": getattr(app.state, "agent_running", False),
        "last_incident_check": getattr(app.state, "last_incident_check", None),
        "last_digest": getattr(app.state, "last_digest", None),
        "uptime_seconds": uptime,
    }


@app.get("/status", dependencies=[Depends(verify_token)])
async def status():
    state = storage.read_current_state()
    if state:
        return state
    return _default_status()


@app.get("/services", dependencies=[Depends(verify_token)])
async def services():
    state = storage.read_current_state()
    svc_list = state["services"] if state else _default_status()["services"]
    return sorted(svc_list, key=lambda s: STATE_SEVERITY.get(s.get("state", "calm"), 3))


@app.get("/digest/latest", dependencies=[Depends(verify_token)])
async def digest_latest():
    d = storage.read_latest_digest()
    if not d:
        raise HTTPException(status_code=404, detail="No digests available")
    return d


@app.get("/digests", dependencies=[Depends(verify_token)])
async def digests():
    return {"digests": storage.list_digests()}


@app.get("/digest/{timestamp}", dependencies=[Depends(verify_token)])
async def digest_by_timestamp(timestamp: str):
    d = storage.read_digest(timestamp)
    if not d:
        raise HTTPException(status_code=404, detail="Digest not found")
    return d


@app.get("/incidents", dependencies=[Depends(verify_token)])
async def incidents():
    ts_list = storage.list_incidents()
    items = []
    for ts in ts_list:
        inc = storage.read_incident(ts)
        if inc:
            items.append({
                "timestamp": ts,
                "worst_state": inc.get("worst_state"),
                "root_cause_alert": inc.get("root_cause_alert"),
                "active_alert_count": inc.get("active_alert_count"),
            })
    return {"incidents": items}


@app.get("/incidents/{timestamp}", dependencies=[Depends(verify_token)])
async def incident_by_timestamp(timestamp: str):
    inc = storage.read_incident(timestamp)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return inc


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_token)])
async def status_page(request: Request):
    token = request.query_params.get("token", "")
    return templates.TemplateResponse("status.html", {"request": request, "token": token})


# ---------------------------------------------------------------------------
# Schema (self-documenting API for write clients)
# ---------------------------------------------------------------------------

@app.get("/schema", dependencies=[Depends(verify_token)])
async def schema():
    """Return expected payload shapes for all POST endpoints, with examples."""
    return {
        "endpoints": {
            "POST /status": {
                "description": "Update current system state. Server adds updated_at automatically.",
                "fields": {
                    "worst_state": {"type": "string", "required": True, "enum": list(VALID_STATES)},
                    "triage": {"type": "string|null", "required": True, "description": "Triage prose for on-call engineer, or null if no incidents"},
                    "active_alert_count": {"type": "integer", "required": True},
                    "root_cause_alert": {"type": "string|null", "required": True},
                    "noise_alert_count": {"type": "integer", "required": True},
                    "services": {
                        "type": "array",
                        "required": True,
                        "items": {
                            "id": {"type": "string", "required": True},
                            "display_name": {"type": "string", "required": True},
                            "state": {"type": "string", "required": True, "enum": list(VALID_STATES)},
                            "message": {"type": "string", "required": True},
                            "url": {"type": "string|null", "required": False},
                        },
                    },
                },
                "example": {
                    "worst_state": "squall",
                    "triage": "Gibraltar is seeing elevated 5xx rates from Expedia upstream (root cause). 18 downstream SLO violation alerts are byproduct noise.",
                    "active_alert_count": 19,
                    "root_cause_alert": "Gibraltar-Expedia-5xx",
                    "noise_alert_count": 18,
                    "services": [
                        {"id": "gibraltar", "display_name": "Gibraltar", "state": "squall", "message": "Error rate 8.3%, elevated from baseline 0.2%.", "url": None},
                        {"id": "orderbond", "display_name": "OrderBond", "state": "unsettled", "message": "SLO violation — downstream of Gibraltar Expedia issue.", "url": None},
                        {"id": "unicorn", "display_name": "Unicorn", "state": "calm", "message": "All systems nominal.", "url": None},
                        {"id": "amex-services", "display_name": "Amex Services", "state": "calm", "message": "All systems nominal.", "url": None},
                        {"id": "hotel-services", "display_name": "Hotel Services", "state": "serene", "message": "Error rate below baseline. Response times excellent.", "url": None},
                    ],
                },
            },
            "POST /digest": {
                "description": "Submit a new health digest. Server timestamps it automatically.",
                "fields": {
                    "content": {"type": "string", "required": True, "description": "Markdown digest content"},
                },
                "example": {
                    "content": "## System Health — 14:00 UTC\n\nOverall the system is in good shape. Gibraltar running clean, error rates at 0.2%.\n\nOrderBond latency trending slightly upward since 13:15 UTC.\n\n**One thing to watch:** OrderBond p99 latency creep.",
                },
            },
            "POST /incident": {
                "description": "Submit an incident snapshot. Server timestamps it automatically.",
                "fields": {
                    "worst_state": {"type": "string", "required": True, "enum": list(VALID_STATES)},
                    "triage": {"type": "string", "required": True},
                    "active_alert_count": {"type": "integer", "required": True},
                    "root_cause_alert": {"type": "string", "required": True},
                    "noise_alert_count": {"type": "integer", "required": True},
                },
                "example": {
                    "worst_state": "squall",
                    "triage": "Gibraltar is seeing elevated 5xx rates from Expedia upstream.",
                    "active_alert_count": 19,
                    "root_cause_alert": "Gibraltar-Expedia-5xx",
                    "noise_alert_count": 18,
                },
            },
        },
        "auth": "Include WRITE_TOKEN as ?token=VALUE or Authorization: Bearer VALUE",
        "note": "All POST endpoints add updated_at/generated_at timestamps server-side.",
    }


# ---------------------------------------------------------------------------
# Write endpoints (POST)
# ---------------------------------------------------------------------------

@app.post("/status", dependencies=[Depends(verify_write_token)])
async def post_status(request: Request):
    """Accept a full status payload from an external SRE agent."""
    from datetime import datetime, timezone
    body = await request.json()

    worst_state = body.get("worst_state")
    if worst_state not in VALID_STATES:
        raise HTTPException(status_code=422, detail=f"Invalid worst_state: {worst_state!r}. Must be one of {VALID_STATES}")

    services = body.get("services")
    if not isinstance(services, list) or not services:
        raise HTTPException(status_code=422, detail="services must be a non-empty array")

    for svc in services:
        if svc.get("state") not in VALID_STATES:
            raise HTTPException(status_code=422, detail=f"Invalid service state: {svc.get('state')!r} for {svc.get('id')}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state_data = {
        "worst_state": worst_state,
        "updated_at": now,
        "triage": body.get("triage"),
        "active_alert_count": body.get("active_alert_count", 0),
        "root_cause_alert": body.get("root_cause_alert"),
        "noise_alert_count": body.get("noise_alert_count", 0),
        "services": [
            {
                "id": s["id"],
                "display_name": s["display_name"],
                "state": s["state"],
                "updated_at": now,
                "message": s.get("message", ""),
                "url": s.get("url"),
            }
            for s in services
        ],
    }

    storage.write_current_state(state_data)
    storage.cleanup(INCIDENT_RETENTION_DAYS, DIGEST_RETENTION_DAYS)
    app.state.last_incident_check = now

    return {"ok": True, "updated_at": now}


@app.post("/digest", dependencies=[Depends(verify_write_token)])
async def post_digest(request: Request):
    """Accept a markdown digest from an external SRE agent."""
    from datetime import datetime, timezone
    body = await request.json()

    content = body.get("content")
    if not content or not isinstance(content, str):
        raise HTTPException(status_code=422, detail="content must be a non-empty string")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    storage.write_digest(now, content)
    app.state.last_digest = now

    return {"ok": True, "generated_at": now}


@app.post("/incident", dependencies=[Depends(verify_write_token)])
async def post_incident(request: Request):
    """Accept an incident snapshot from an external SRE agent."""
    from datetime import datetime, timezone
    body = await request.json()

    worst_state = body.get("worst_state")
    if worst_state not in VALID_STATES:
        raise HTTPException(status_code=422, detail=f"Invalid worst_state: {worst_state!r}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    incident_data = {
        "worst_state": worst_state,
        "timestamp": now,
        "triage": body.get("triage"),
        "active_alert_count": body.get("active_alert_count", 0),
        "root_cause_alert": body.get("root_cause_alert"),
        "noise_alert_count": body.get("noise_alert_count", 0),
    }

    storage.write_incident(now, incident_data)

    return {"ok": True, "timestamp": now}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_status() -> dict:
    """Return a calm default when no current-state.json exists."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "worst_state": "calm",
        "updated_at": now,
        "triage": None,
        "active_alert_count": 0,
        "root_cause_alert": None,
        "noise_alert_count": 0,
        "services": [
            {
                "id": s["id"],
                "display_name": s["display_name"],
                "state": "calm",
                "updated_at": now,
                "message": "All systems nominal.",
                "url": None,
            }
            for s in DEFAULT_SERVICES
        ],
    }

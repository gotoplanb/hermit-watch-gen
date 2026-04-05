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

API_TOKEN = os.environ.get("API_TOKEN", "")

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

async def verify_token(request: Request):
    """Check API_TOKEN if set. No-op when unset."""
    if not API_TOKEN:
        return
    token = request.query_params.get("token")
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if token != API_TOKEN:
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

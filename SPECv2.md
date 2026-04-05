# hermit-watch-gen — Course Correction Prompt

## Context

This repo was originally a GitHub Actions static file generator — Python scripts that fetched public status pages and committed JSON files to the repo on a schedule. That approach is being replaced entirely.

Read this entire document before touching any code.

**What this repo becomes:**

A FastAPI service that acts as an AI-powered SRE agent. It runs locally on a work laptop or Mac Mini, exposed via ngrok for private mobile access. It queries an observability stack for active alerts, uses Claude to triage them, generates hourly health digests, and serves everything via a simple API with a built-in status page.

---

## What to remove

- `.github/workflows/` — delete entirely. No more GitHub Actions.
- `generators/` directory — delete entirely.
- `slots/` or `sources/` output directory — delete entirely.
- `config.yml` — delete.
- `run.py` — delete.
- Any static file generation logic.

Keep:
- `requirements.txt` — update it
- `tests/` — gut and rebuild for the new service
- `README.md` — rewrite entirely

---

## What this service is

A stateless FastAPI application with three responsibilities:

1. **Agent loops** — background tasks that query the observability stack and write output files
2. **API endpoints** — serve current state, incidents, digest, and service list to the iOS app and status page
3. **Status page** — simple HTML + Alpine.js page served at `/` showing the same data as the API

The service has no database. All persistent data lives in a local `data/` directory as JSON and markdown files. The service reads and writes files. That's it.

This design means the service can run anywhere Python runs — laptop, Mac Mini, Cloud Run, Fly.io — with no infrastructure dependencies beyond the filesystem.

---

## File structure

```
hermit-watch-gen/
├── main.py                  # FastAPI app, all routes
├── agent.py                 # background agent loops
├── observability/
│   ├── __init__.py
│   ├── base.py              # abstract query interface
│   └── sumo_logic.py        # Sumo Logic implementation
├── prompts/
│   ├── triage.txt           # incident triage prompt template
│   └── digest.txt           # hourly digest prompt template
├── templates/
│   └── status.html          # Alpine.js status page
├── data/                    # runtime output, gitignored
│   ├── current-state.json   # always overwritten
│   ├── incidents/           # timestamped snapshots
│   │   └── 2026-03-31T14:05:00Z.json
│   └── digests/             # timestamped markdown files
│       └── 2026-03-31T14:00:00Z.md
├── tests/
│   ├── test_triage.py
│   ├── test_digest.py
│   └── fixtures/
│       └── sample_alerts.json
├── .env.example             # required environment variables
├── requirements.txt
└── README.md
```

`data/` is gitignored. It is runtime state, not source code.

---

## Environment variables

```bash
# Observability stack
SUMO_ACCESS_ID=
SUMO_ACCESS_KEY=
SUMO_BASE_URL=https://api.sumologic.com

# Anthropic
ANTHROPIC_API_KEY=

# Agent configuration
INCIDENT_CHECK_INTERVAL_SECONDS=300     # 5 minutes
DIGEST_INTERVAL_SECONDS=3600            # 1 hour
DATA_RETENTION_DAYS=7

# Optional: simple auth token for API endpoints
# If set, all API requests must include ?token=VALUE or Authorization: Bearer VALUE
API_TOKEN=
```

---

## Agent loops

Two background tasks started on app startup using FastAPI's `lifespan` context manager.

### Incident check loop (every 5 minutes)

```python
async def incident_check_loop():
    while True:
        await asyncio.sleep(INCIDENT_CHECK_INTERVAL_SECONDS)
        await run_incident_check()
```

`run_incident_check()`:
1. Call `observability.get_active_alerts()` → list of alert dicts
2. If no alerts: write `current-state.json` with state=`calm`, empty triage
3. If alerts exist:
   - Send alert list to Claude with triage prompt
   - Claude returns: worst state enum, triage prose, root cause alert, noise alert count
   - Write timestamped incident snapshot to `data/incidents/`
   - Write updated `current-state.json`
4. During active incident (state >= squall): run every 2 minutes instead of 5

### Digest loop (every hour)

```python
async def digest_loop():
    while True:
        await asyncio.sleep(DIGEST_INTERVAL_SECONDS)
        await run_digest()
```

`run_digest()`:
1. Call `observability.get_recent_metrics()` → trends, latency, error patterns for the last hour
2. Send to Claude with digest prompt
3. Claude returns a markdown narrative — exploratory analysis, not just alert summary
4. Write timestamped digest to `data/digests/`
5. During active incident: runs every 15 minutes

### Data retention

On each agent loop iteration, delete files in `data/incidents/` and `data/digests/` older than `DATA_RETENTION_DAYS`. Simple filename timestamp comparison.

---

## current-state.json schema

Always overwritten by the incident check loop. This is what the iOS complication ultimately reads (via the API, not directly).

```json
{
  "updated_at": "2026-03-31T14:07:00Z",
  "worst_state": "squall",
  "triage": "Gibraltar is seeing elevated 5xx rates from Expedia upstream (root cause). 18 downstream SLO violation alerts are byproduct noise. Focus on Gibraltar-Expedia-5xx alert.",
  "active_alert_count": 19,
  "root_cause_alert": "Gibraltar-Expedia-5xx",
  "noise_alert_count": 18
}
```

`triage` is null when no incidents are active.

---

## API endpoints

### `GET /status`

Returns current system state. Primary endpoint for the iOS app.

Response:
```json
{
  "worst_state": "squall",
  "updated_at": "2026-03-31T14:07:00Z",
  "triage": "Gibraltar is seeing elevated 5xx rates...",
  "services": [
    {
      "id": "gibraltar",
      "display_name": "Gibraltar",
      "state": "squall",
      "updated_at": "2026-03-31T14:07:00Z",
      "message": "Error rate 8.3%, elevated from baseline 0.2%",
      "url": "https://your-sumo-url/..."
    }
  ]
}
```

### `GET /digest/latest`

Returns the most recently generated digest.

Response:
```json
{
  "generated_at": "2026-03-31T14:00:00Z",
  "content": "## System Health — 14:00 UTC\n\nOverall the system is calm..."
}
```

### `GET /digest/{timestamp}`

Returns a specific historical digest by ISO 8601 timestamp. Returns 404 if not found.

### `GET /digests`

Returns list of available digest timestamps, newest first.

```json
{
  "digests": [
    "2026-03-31T15:00:00Z",
    "2026-03-31T14:00:00Z",
    "2026-03-31T13:00:00Z"
  ]
}
```

### `GET /services`

Returns flat list of all monitored services with current state. Sorted worst-first.

Response: array of service objects (same shape as `services` in `/status`).

### `GET /incidents`

Returns list of recent incident snapshots, newest first. Useful for history browsing.

```json
{
  "incidents": [
    {
      "timestamp": "2026-03-31T14:05:00Z",
      "worst_state": "squall",
      "root_cause_alert": "Gibraltar-Expedia-5xx",
      "active_alert_count": 19
    }
  ]
}
```

### `GET /incidents/{timestamp}`

Returns full incident snapshot JSON.

### `GET /health`

Simple liveness check. Returns 200 with `{"status": "ok", "agent_running": true}`.

### `GET /`

Serves the Alpine.js status page HTML.

---

## Optional auth

If `API_TOKEN` is set in environment, all endpoints except `/health` require either:
- Query param: `?token=VALUE`
- Header: `Authorization: Bearer VALUE`

Return 401 if token is missing or invalid. This is the ngrok security boundary — simple enough for personal use, good enough for team use. Replace with proper auth when moving to cloud.

---

## Observability query interface

Abstract base class. Implement once per observability stack. Sumo Logic is the first implementation.

```python
from abc import ABC, abstractmethod

class ObservabilityBackend(ABC):

    @abstractmethod
    async def get_active_alerts(self) -> list[dict]:
        """
        Returns list of active monitor alerts.
        Each dict must contain at minimum:
          - name: str
          - severity: str (e.g. "critical", "warning", "p1" through "p5")
          - service: str
          - triggered_at: str (ISO 8601)
          - description: str (optional but helpful for triage)
        """
        pass

    @abstractmethod
    async def get_recent_metrics(self) -> dict:
        """
        Returns recent metric trends for digest generation.
        Shape is flexible — this gets passed directly to Claude as context.
        Include: error rates by service, latency percentiles, request volumes,
        anything anomalous in the last hour.
        """
        pass
```

### Sumo Logic implementation

`observability/sumo_logic.py` implements `ObservabilityBackend` using the Sumo Logic API.

For `get_active_alerts()`: query the Monitors API for all monitors currently in alert state. Filter to monitors that are triggered (not resolved). Return normalized alert list.

For `get_recent_metrics()`: run a few key log search queries for the last hour — error rate by service, p99 latency by service, top error messages. Return as a structured dict. Keep queries simple and fast — this runs every hour.

---

## Claude integration

Use the Anthropic Python SDK. Two prompt templates in `prompts/`.

### triage.txt

```
You are an SRE reviewing active alerts for a travel company's production systems.
Services monitored: Gibraltar, OrderBond, Unicorn, Amex Services, Hotel Services.

Active alerts:
{alerts_json}

Your job:
1. Identify the root cause alert (the underlying problem, not symptoms)
2. Identify which alerts are downstream noise/byproduct of the root cause
3. Determine the worst state: serene / calm / unsettled / squall / storm
4. Write 2-3 sentences of triage prose for an on-call engineer

Rules:
- SLO violation alerts are almost always downstream noise when a supplier is having issues
- A single supplier outage (e.g. Expedia 5xx) can trigger 10-20 SLO alerts — these are all noise
- "storm" means active user-facing impact requiring immediate attention
- "squall" means degraded but not critical, needs attention within 15 minutes
- "unsettled" means worth watching, no action required yet

Respond in JSON only:
{
  "worst_state": "squall",
  "triage": "...",
  "root_cause_alert": "alert name here",
  "noise_alert_count": 18
}
```

### digest.txt

```
You are an SRE reviewing the last hour of system health for a travel company.
Services: Gibraltar, OrderBond, Unicorn, Amex Services, Hotel Services.

Recent metrics:
{metrics_json}

Write a brief health digest (3-5 paragraphs) covering:
- Overall system state
- Anything trending in the wrong direction, even if not yet alerting
- Any correlations worth noting (latency up + error rate up on same service?)
- One thing worth keeping an eye on in the next hour

Tone: like a junior SRE writing a handoff note. Factual, concise, no fluff.
Write in markdown. Start with a heading: ## System Health — {timestamp}
```

---

## Status page (templates/status.html)

Simple HTML page served at `/`. Uses Alpine.js loaded from CDN. No build step.

Polls `/status` every 30 seconds. Displays:
- Overall state as a large colored indicator
- Triage prose if any incidents active
- Hermit crab SVG if no incidents (resting/calm state)
- Service list as colored rows, worst-first
- Last updated timestamp
- Link to latest digest

Color scheme matches the iOS app exactly — same hex values for each state.

This page is your demo artifact and your internal status page. It should look good enough to show on a screen at the on-site.

---

## main.py structure

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start agent loops on startup
    task1 = asyncio.create_task(incident_check_loop())
    task2 = asyncio.create_task(digest_loop())
    yield
    # Cancel on shutdown
    task1.cancel()
    task2.cancel()

app = FastAPI(lifespan=lifespan)

# All routes defined here
# Auth dependency applied to all routes if API_TOKEN is set
```

---

## Tests

### test_triage.py
- Loads `fixtures/sample_alerts.json` (realistic alert list including root cause + SLO noise)
- Calls triage prompt with mock Claude response
- Validates correct state returned
- Validates noise alerts correctly identified
- Does not make real API calls — mock both Sumo Logic and Anthropic

### test_digest.py
- Validates digest file written with correct timestamp filename
- Validates markdown content starts with expected heading
- Does not make real API calls

### fixtures/sample_alerts.json
Realistic alert payload. Should include:
- One root cause alert (e.g. Gibraltar-Expedia-5xx, severity critical)
- 15-18 SLO violation alerts at warning severity
- Mix of services affected

---

## requirements.txt

```
fastapi>=0.110.0
uvicorn>=0.27.0
anthropic>=0.20.0
httpx>=0.27.0
python-dotenv>=1.0.0
jinja2>=3.1.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

---

## Running locally

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Sumo Logic and Anthropic credentials

# Run
uvicorn main:app --reload --port 8000

# Expose via ngrok
ngrok http 8000
# Copy the https URL into iOS app Settings → Base URL
```

---

## Definition of done

- [ ] GitHub Actions workflow deleted
- [ ] Static generator code deleted
- [ ] FastAPI app starts and serves all endpoints
- [ ] `/health` returns 200
- [ ] `/status` returns valid JSON with correct shape
- [ ] `/digest/latest` returns JSON with generated_at and content
- [ ] `/services` returns sorted service list
- [ ] `GET /` serves status page HTML
- [ ] Status page polls `/status` and updates without reload
- [ ] Incident check loop runs on startup, writes `current-state.json`
- [ ] Digest loop runs on startup, writes timestamped digest files
- [ ] Sumo Logic backend queries active monitors correctly
- [ ] Claude triage prompt returns correct JSON shape
- [ ] Auth token enforced on all endpoints when `API_TOKEN` is set
- [ ] Data retention deletes files older than `DATA_RETENTION_DAYS`
- [ ] All tests pass
- [ ] `.env.example` documents all required variables
- [ ] README covers local setup, ngrok usage, and how to implement a custom observability backend
- [ ] `data/` directory is gitignored

---

## Notes for the Claude Code session

- Start with the FastAPI skeleton and `/health` endpoint before writing any agent code. Confirm the server starts and is reachable.
- Write the file I/O utilities (read/write `current-state.json`, write timestamped files) before the agent loops. Test them in isolation.
- The Sumo Logic integration will need real credentials to test. Use `sample_alerts.json` fixture for unit tests and only test live Sumo Logic queries manually.
- The Alpine.js status page can be built last — it's a consumer of the API, not a dependency of anything.
- Keep `main.py` focused on routing. Agent logic lives in `agent.py`. Observability queries live in `observability/`. Clean separation.
- The service names in the triage prompt (Gibraltar, OrderBond, etc.) are specific to this deployment. Make them configurable via environment variable or a simple config file so others can adapt the prompts for their own services.

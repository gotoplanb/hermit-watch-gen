# Hermit Watch — SRE Agent

A FastAPI service that acts as an AI-powered SRE agent. It queries your observability stack for active alerts, uses Claude to triage them, generates hourly health digests, and serves everything via a simple API with a built-in status page. Designed to run on a work laptop or Mac Mini, exposed via ngrok for private mobile access.

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Sumo Logic and Anthropic credentials

# Run
uvicorn main:app --reload --port 8000

# Expose via ngrok (optional)
ngrok http 8000
# Copy the https URL into iOS app Settings → Base URL
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness check (no auth required) |
| `GET /status` | Current system state — primary endpoint for iOS app |
| `GET /services` | Service list sorted worst-first |
| `GET /digest/latest` | Most recent health digest |
| `GET /digest/{timestamp}` | Specific historical digest |
| `GET /digests` | List of available digest timestamps |
| `GET /incidents` | Recent incident snapshots |
| `GET /incidents/{timestamp}` | Full incident snapshot |
| `GET /` | Built-in status page (Alpine.js) |

### Response Shapes

**`/status`**
```json
{
  "worst_state": "squall",
  "updated_at": "2026-04-05T14:07:00Z",
  "triage": "Gibraltar is seeing elevated 5xx rates...",
  "active_alert_count": 19,
  "root_cause_alert": "Gibraltar-Expedia-5xx",
  "noise_alert_count": 18,
  "services": [
    {
      "id": "gibraltar",
      "display_name": "Gibraltar",
      "state": "squall",
      "updated_at": "2026-04-05T14:07:00Z",
      "message": "Error rate 8.3%, elevated from baseline 0.2%.",
      "url": null
    }
  ]
}
```

**`/digest/latest`**
```json
{
  "generated_at": "2026-04-05T14:00:00Z",
  "content": "## System Health — 14:00 UTC\n\nOverall the system is calm..."
}
```

## State Enum

| State | Color | Meaning |
|-------|-------|---------|
| `serene` | Green | Better than baseline / all clear |
| `calm` | Blue | Nominal / operational |
| `unsettled` | Yellow | Worth watching / degraded |
| `squall` | Orange | Actively degrading / partial outage |
| `storm` | Red | Incident / major outage |

## Agent Behavior

Two background loops start on app startup:

- **Incident check** (every 5 min, every 2 min during active incidents) — queries observability for alerts, sends to Claude for triage, writes `current-state.json` and incident snapshots
- **Digest** (every hour, every 15 min during active incidents) — queries recent metrics, sends to Claude for narrative analysis, writes timestamped markdown

Data retention automatically deletes files older than `DATA_RETENTION_DAYS`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SUMO_ACCESS_ID` | | Sumo Logic access ID |
| `SUMO_ACCESS_KEY` | | Sumo Logic access key |
| `SUMO_BASE_URL` | `https://api.sumologic.com` | Sumo Logic API base URL |
| `ANTHROPIC_API_KEY` | | Anthropic API key |
| `INCIDENT_CHECK_INTERVAL_SECONDS` | `300` | Normal incident check interval |
| `DIGEST_INTERVAL_SECONDS` | `3600` | Normal digest interval |
| `DATA_RETENTION_DAYS` | `7` | Days to keep incident/digest files |
| `API_TOKEN` | | Optional auth token for all endpoints |
| `MONITORED_SERVICES` | `Gibraltar, OrderBond, ...` | Comma-separated service list for prompts |

## Authentication

If `API_TOKEN` is set, all endpoints except `/health` require either:
- Query param: `?token=VALUE`
- Header: `Authorization: Bearer VALUE`

## Custom Observability Backend

Subclass `ObservabilityBackend` in `observability/base.py`:

```python
from observability.base import ObservabilityBackend

class MyBackend(ObservabilityBackend):
    async def get_active_alerts(self) -> list[dict]:
        # Return list of {name, severity, service, triggered_at, description}
        ...

    async def get_recent_metrics(self) -> dict:
        # Return metrics dict — passed directly to Claude for digest
        ...
```

Then update the backend instantiation in `main.py`'s lifespan.

## Architecture

- `main.py` — FastAPI app, all routes, lifespan management
- `agent.py` — Background loops (incident check + digest)
- `claude_client.py` — Claude API integration for triage and digest
- `storage.py` — File-based persistence (atomic writes, cleanup)
- `observability/` — Abstract backend + Sumo Logic implementation
- `prompts/` — Prompt templates for Claude
- `templates/` — Alpine.js status page
- `data/` — Runtime output (gitignored)
- `mocks/` — Mock API responses for iOS development

## Running Tests

```bash
pytest
```

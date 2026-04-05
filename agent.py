"""Background agent loops for incident checking and digest generation."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import claude_client
import storage
from observability.base import ObservabilityBackend

logger = logging.getLogger(__name__)

VALID_STATES = ("serene", "calm", "unsettled", "squall", "storm")

DEFAULT_INCIDENT_INTERVAL = int(os.environ.get("INCIDENT_CHECK_INTERVAL_SECONDS", "300"))
DEFAULT_DIGEST_INTERVAL = int(os.environ.get("DIGEST_INTERVAL_SECONDS", "3600"))
DATA_RETENTION_DAYS = int(os.environ.get("DATA_RETENTION_DAYS", "7"))

ESCALATED_INCIDENT_INTERVAL = 120   # 2 minutes during active incident
ESCALATED_DIGEST_INTERVAL = 900     # 15 minutes during active incident


async def incident_check_loop(app_state, backend: ObservabilityBackend):
    """Run incident checks on a loop. Writes current-state.json and incident snapshots."""
    # Run first check immediately
    await _run_incident_check(app_state, backend)

    while True:
        interval = _get_incident_interval()
        await asyncio.sleep(interval)
        try:
            await _run_incident_check(app_state, backend)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Incident check loop error")


async def digest_loop(app_state, backend: ObservabilityBackend):
    """Run digest generation on a loop. Writes timestamped markdown files."""
    # Wait one interval before first digest
    interval = _get_digest_interval()
    await asyncio.sleep(interval)

    while True:
        try:
            await _run_digest(app_state, backend)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Digest loop error")

        interval = _get_digest_interval()
        await asyncio.sleep(interval)


async def _run_incident_check(app_state, backend: ObservabilityBackend):
    """Single iteration of the incident check."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        alerts = await backend.get_active_alerts()
    except Exception as e:
        logger.error("Failed to fetch alerts: %s", e)
        alerts = []

    if not alerts:
        state_data = _build_calm_state(now)
    else:
        triage = await claude_client.run_triage(alerts)
        state_data = _build_incident_state(now, alerts, triage)

        # Write incident snapshot
        storage.write_incident(now, state_data)

    storage.write_current_state(state_data)
    app_state.last_incident_check = now

    # Cleanup old files
    storage.cleanup_old_files(DATA_RETENTION_DAYS)

    logger.info("Incident check: %s (%d alerts)", state_data["worst_state"], len(alerts))


async def _run_digest(app_state, backend: ObservabilityBackend):
    """Single iteration of digest generation."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        metrics = await backend.get_recent_metrics()
    except Exception as e:
        logger.error("Failed to fetch metrics: %s", e)
        metrics = {"error": str(e)}

    content = await claude_client.run_digest(metrics, now)
    storage.write_digest(now, content)
    app_state.last_digest = now

    logger.info("Digest generated: %s", now)


def _get_incident_interval() -> int:
    """Return check interval — shorter during active incidents."""
    state = storage.read_current_state()
    if state and state.get("worst_state") in ("squall", "storm"):
        return ESCALATED_INCIDENT_INTERVAL
    return DEFAULT_INCIDENT_INTERVAL


def _get_digest_interval() -> int:
    """Return digest interval — shorter during active incidents."""
    state = storage.read_current_state()
    if state and state.get("worst_state") in ("squall", "storm"):
        return ESCALATED_DIGEST_INTERVAL
    return DEFAULT_DIGEST_INTERVAL


def _build_calm_state(now: str) -> dict:
    """Build a calm state dict with all services nominal."""
    from main import DEFAULT_SERVICES
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


def _build_incident_state(now: str, alerts: list[dict], triage: dict) -> dict:
    """Build state dict from alerts and Claude triage response."""
    from main import DEFAULT_SERVICES

    worst_state = triage.get("worst_state", "unsettled")
    if worst_state not in VALID_STATES:
        worst_state = "unsettled"

    # Build per-service state from alerts
    service_alerts: dict[str, list[dict]] = {}
    for alert in alerts:
        svc = alert.get("service", "unknown")
        service_alerts.setdefault(svc, []).append(alert)

    root_cause = triage.get("root_cause_alert", "")

    services = []
    for s in DEFAULT_SERVICES:
        sid = s["id"]
        svc_alerts = service_alerts.get(sid, [])
        if not svc_alerts:
            svc_state = "calm"
            message = "All systems nominal."
        else:
            # Check if this service has the root cause alert
            has_root = any(root_cause in a.get("name", "") for a in svc_alerts)
            severities = [a.get("severity", "") for a in svc_alerts]
            if has_root or "critical" in severities:
                svc_state = worst_state
            elif "warning" in severities:
                svc_state = "unsettled"
            else:
                svc_state = "calm"
            descriptions = [a.get("description", a.get("name", "")) for a in svc_alerts]
            message = "; ".join(d for d in descriptions if d) or "Alert active."

        url = None
        services.append({
            "id": sid,
            "display_name": s["display_name"],
            "state": svc_state,
            "updated_at": now,
            "message": message,
            "url": url,
        })

    return {
        "worst_state": worst_state,
        "updated_at": now,
        "triage": triage.get("triage"),
        "active_alert_count": len(alerts),
        "root_cause_alert": triage.get("root_cause_alert"),
        "noise_alert_count": triage.get("noise_alert_count", 0),
        "services": services,
    }

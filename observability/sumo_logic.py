"""Sumo Logic observability backend."""

from __future__ import annotations

import httpx

from observability.base import ObservabilityBackend


class SumoLogicBackend(ObservabilityBackend):
    """Queries Sumo Logic for active alerts and recent metrics."""

    def __init__(self, access_id: str, access_key: str, base_url: str):
        self.auth = (access_id, access_key)
        self.base_url = base_url.rstrip("/")

    async def get_active_alerts(self) -> list[dict]:
        """Query Sumo Logic Monitors API for triggered monitors."""
        url = f"{self.base_url}/api/v1/monitors/status"
        async with httpx.AsyncClient(auth=self.auth, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        alerts = []
        for monitor in data.get("data", []):
            if monitor.get("status", "").lower() not in ("critical", "warning"):
                continue
            alerts.append({
                "name": monitor.get("name", ""),
                "severity": monitor.get("status", "").lower(),
                "service": _extract_service(monitor.get("name", "")),
                "triggered_at": monitor.get("triggeredAt", ""),
                "description": monitor.get("description", ""),
            })
        return alerts

    async def get_recent_metrics(self) -> dict:
        """Run log search queries for the last hour.

        Returns structured dict with error rates and latency by service.
        Queries are kept simple and fast per spec guidance.
        """
        # Placeholder — real queries depend on the Sumo Logic log schema.
        # This returns the structure Claude expects for digest generation.
        url = f"{self.base_url}/api/v1/logs/summary"
        try:
            async with httpx.AsyncClient(auth=self.auth, timeout=30) as client:
                resp = await client.get(url, params={"timeRange": "-1h"})
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return {"error": "Failed to fetch metrics", "services": {}}


def _extract_service(monitor_name: str) -> str:
    """Extract service name from monitor naming convention.

    Expects monitors named like 'Gibraltar-Expedia-5xx' or
    'OrderBond-SLO-Latency'. Returns the first segment.
    """
    parts = monitor_name.split("-")
    if parts:
        return parts[0].lower()
    return "unknown"

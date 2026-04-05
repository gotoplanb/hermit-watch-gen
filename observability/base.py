"""Abstract observability backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObservabilityBackend(ABC):

    @abstractmethod
    async def get_active_alerts(self) -> list[dict]:
        """Return list of active monitor alerts.

        Each dict must contain at minimum:
          - name: str
          - severity: str (e.g. "critical", "warning", "p1" through "p5")
          - service: str
          - triggered_at: str (ISO 8601)
          - description: str (optional but helpful for triage)
        """

    @abstractmethod
    async def get_recent_metrics(self) -> dict:
        """Return recent metric trends for digest generation.

        Shape is flexible — passed directly to Claude as context.
        Include: error rates by service, latency percentiles, request volumes,
        anything anomalous in the last hour.
        """

"""Claude API integration for triage and digest generation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

DEFAULT_SERVICES = "Gibraltar, OrderBond, Unicorn, Amex Services, Hotel Services"


def _load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template and fill placeholders."""
    path = PROMPTS_DIR / f"{name}.txt"
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)


def _get_services() -> str:
    """Get service list from env or default."""
    return os.environ.get("MONITORED_SERVICES", DEFAULT_SERVICES)


async def run_triage(alerts: list[dict]) -> dict:
    """Send alerts to Claude for triage. Returns parsed JSON dict.

    Returns dict with: worst_state, triage, root_cause_alert, noise_alert_count.
    Falls back to unsettled with error message on failure.
    """
    prompt = _load_prompt(
        "triage",
        services=_get_services(),
        alerts_json=json.dumps(alerts, indent=2),
    )

    try:
        client = anthropic.AsyncAnthropic()
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude triage response: %s", e)
        return {
            "worst_state": "unsettled",
            "triage": f"Triage failed: could not parse Claude response. {len(alerts)} alerts active.",
            "root_cause_alert": alerts[0]["name"] if alerts else None,
            "noise_alert_count": max(0, len(alerts) - 1),
        }
    except Exception as e:
        logger.error("Claude triage call failed: %s", e)
        return {
            "worst_state": "unsettled",
            "triage": f"Triage unavailable: {e}. {len(alerts)} alerts active.",
            "root_cause_alert": alerts[0]["name"] if alerts else None,
            "noise_alert_count": max(0, len(alerts) - 1),
        }


async def run_digest(metrics: dict, timestamp: str) -> str:
    """Send metrics to Claude for digest generation. Returns markdown string."""
    prompt = _load_prompt(
        "digest",
        services=_get_services(),
        metrics_json=json.dumps(metrics, indent=2),
        timestamp=timestamp,
    )

    try:
        client = anthropic.AsyncAnthropic()
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error("Claude digest call failed: %s", e)
        return f"## System Health — {timestamp}\n\nDigest generation failed: {e}"

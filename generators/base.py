"""Shared utilities for all Hermit Watch generators."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

VALID_STATES = ("serene", "calm", "unsettled", "squall", "storm")

NUMERIC_TO_STATE = {
    1: "storm",
    2: "squall",
    3: "unsettled",
    4: "calm",
    5: "serene",
}

STATUSPAGE_INDICATOR_MAP = {
    "none": "serene",
    "minor": "unsettled",
    "major": "squall",
    "critical": "storm",
}

SOURCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sources")


def fetch_json(url: str) -> dict:
    """GET a URL with a 10-second timeout and return parsed JSON."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def normalize_state(raw) -> str:
    """Map any known severity vocabulary to the five-state enum.

    Accepts: named state strings, numeric aliases (1-5), and
    Statuspage indicator values (none/minor/major/critical).
    """
    if isinstance(raw, int):
        if raw in NUMERIC_TO_STATE:
            return NUMERIC_TO_STATE[raw]
        raise ValueError(f"Unknown numeric state: {raw}. Expected 1-5.")

    if isinstance(raw, str):
        lower = raw.lower().strip()
        if lower in VALID_STATES:
            return lower
        if lower in STATUSPAGE_INDICATOR_MAP:
            return STATUSPAGE_INDICATOR_MAP[lower]
        raise ValueError(
            f"Unknown state: {raw!r}. "
            f"Expected one of {VALID_STATES} or a Statuspage indicator."
        )

    raise ValueError(f"State must be a string or int, got {type(raw).__name__}.")


def write_source(filename: str, state: str, display_name: str,
                 message=None, url: str | None = None) -> None:
    """Write a source JSON file to sources/{filename}.json."""
    if state not in VALID_STATES:
        raise ValueError(f"Invalid state: {state!r}")

    os.makedirs(SOURCES_DIR, exist_ok=True)

    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state": state,
        "display_name": display_name,
    }
    if message is not None:
        payload["message"] = message
    if url is not None:
        payload["url"] = url

    path = os.path.join(SOURCES_DIR, f"{filename}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def stale_source(filename: str, last_state: str, reason: str,
                 display_name: str, url: str | None = None) -> None:
    """Preserve last known state but update message to indicate fetch failure."""
    state = last_state if last_state in VALID_STATES else "calm"
    message = f"Stale: {reason}"
    write_source(filename, state, display_name, message=message, url=url)

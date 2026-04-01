"""Generic fetcher for any Statuspage.io v2 API."""

from __future__ import annotations

from generators.base import normalize_state

COMPONENT_STATUS_MAP = {
    "operational": "calm",
    "degraded_performance": "unsettled",
    "partial_outage": "squall",
    "major_outage": "storm",
}


def get_state(api_response: dict, component: str | None = None) -> tuple[str, str]:
    """Extract state and message from a Statuspage API response.

    Args:
        api_response: Parsed JSON from /api/v2/summary.json
        component: Optional component name to filter on.

    Returns:
        (state, message) tuple.
    """
    if component:
        return _from_component(api_response, component)
    return _from_indicator(api_response)


def _from_indicator(api_response: dict) -> tuple[str, str]:
    """Use the top-level status indicator."""
    indicator = api_response["status"]["indicator"]
    state = normalize_state(indicator)
    description = api_response["status"].get("description", "")
    message = _build_message(api_response, description)
    return state, message


def _from_component(api_response: dict, component_name: str) -> tuple[str, str]:
    """Find a specific component and map its status."""
    components = api_response.get("components", [])
    match = None
    for c in components:
        if c["name"] == component_name:
            match = c
            break

    if match is None:
        raise ValueError(
            f"Component {component_name!r} not found. "
            f"Available: {[c['name'] for c in components]}"
        )

    raw_status = match["status"]
    if raw_status not in COMPONENT_STATUS_MAP:
        raise ValueError(f"Unknown component status: {raw_status!r}")

    state = COMPONENT_STATUS_MAP[raw_status]

    # Promote to serene if component is operational AND overall indicator is none
    indicator = api_response["status"]["indicator"]
    if raw_status == "operational" and indicator == "none":
        state = "serene"

    message = _build_message(api_response, f"{component_name}: {raw_status}",
                             component_name=component_name)
    return state, message


def _build_message(api_response: dict, default: str,
                   component_name: str | None = None) -> str:
    """Build message from active incidents, or fall back to default."""
    incidents = api_response.get("incidents", [])
    if not incidents:
        return "All systems operational"

    relevant = []
    for inc in incidents:
        if component_name:
            affected_names = [c["name"] for c in inc.get("components", [])]
            if component_name not in affected_names:
                continue
        relevant.append(inc["name"])

    if not relevant:
        return "All systems operational"

    return "; ".join(relevant)

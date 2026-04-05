"""Tests for triage via Claude (mocked)."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import storage

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "sample_alerts.json")


@pytest.fixture(autouse=True)
def use_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.ensure_data_dirs()


@pytest.fixture
def sample_alerts():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


MOCK_TRIAGE_RESPONSE = {
    "worst_state": "squall",
    "triage": "Gibraltar is seeing elevated 5xx rates from Expedia upstream.",
    "root_cause_alert": "Gibraltar-Expedia-5xx",
    "noise_alert_count": 18,
}


def _mock_claude_response(text: str):
    """Create a mock Anthropic message response."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


@pytest.mark.asyncio
async def test_triage_returns_correct_shape(sample_alerts):
    from claude_client import run_triage

    with patch("claude_client.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_claude_response(json.dumps(MOCK_TRIAGE_RESPONSE))
        )
        result = await run_triage(sample_alerts)

    assert result["worst_state"] == "squall"
    assert result["root_cause_alert"] == "Gibraltar-Expedia-5xx"
    assert result["noise_alert_count"] == 18
    assert "triage" in result


@pytest.mark.asyncio
async def test_triage_fallback_on_invalid_json(sample_alerts):
    from claude_client import run_triage

    with patch("claude_client.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_claude_response("not valid json at all")
        )
        result = await run_triage(sample_alerts)

    assert result["worst_state"] == "unsettled"
    assert "19 alerts active" in result["triage"]


@pytest.mark.asyncio
async def test_triage_fallback_on_api_error(sample_alerts):
    from claude_client import run_triage

    with patch("claude_client.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(side_effect=Exception("API down"))
        result = await run_triage(sample_alerts)

    assert result["worst_state"] == "unsettled"
    assert result["root_cause_alert"] == "Gibraltar-Expedia-5xx"


@pytest.mark.asyncio
async def test_incident_check_writes_state(sample_alerts):
    from agent import _run_incident_check
    from observability.base import ObservabilityBackend

    class MockBackend(ObservabilityBackend):
        async def get_active_alerts(self):
            return sample_alerts
        async def get_recent_metrics(self):
            return {}

    app_state = MagicMock()

    with patch("claude_client.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_claude_response(json.dumps(MOCK_TRIAGE_RESPONSE))
        )
        await _run_incident_check(app_state, MockBackend())

    state = storage.read_current_state()
    assert state is not None
    assert state["worst_state"] == "squall"
    assert state["active_alert_count"] == 19
    assert len(state["services"]) == 5


@pytest.mark.asyncio
async def test_calm_state_when_no_alerts():
    from agent import _run_incident_check
    from observability.base import ObservabilityBackend

    class MockBackend(ObservabilityBackend):
        async def get_active_alerts(self):
            return []
        async def get_recent_metrics(self):
            return {}

    app_state = MagicMock()
    await _run_incident_check(app_state, MockBackend())

    state = storage.read_current_state()
    assert state["worst_state"] == "calm"
    assert state["active_alert_count"] == 0
    assert state["triage"] is None

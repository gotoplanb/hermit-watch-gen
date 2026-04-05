"""Tests for digest generation (mocked)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import storage


@pytest.fixture(autouse=True)
def use_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.ensure_data_dirs()


MOCK_DIGEST_MD = """## System Health — 2026-04-05T14:00:00Z

Overall the system is in good shape. Gibraltar running clean, no anomalies.

OrderBond latency trending slightly upward since 13:15 UTC.

**One thing to watch:** OrderBond p99 latency creep."""


def _mock_claude_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


@pytest.mark.asyncio
async def test_digest_written_with_correct_timestamp():
    from agent import _run_digest
    from observability.base import ObservabilityBackend

    class MockBackend(ObservabilityBackend):
        async def get_active_alerts(self):
            return []
        async def get_recent_metrics(self):
            return {"services": {"gibraltar": {"error_rate": 0.002}}}

    app_state = MagicMock()

    with patch("claude_client.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_claude_response(MOCK_DIGEST_MD)
        )
        await _run_digest(app_state, MockBackend())

    digests = storage.list_digests()
    assert len(digests) == 1

    latest = storage.read_latest_digest()
    assert latest is not None
    assert latest["content"].startswith("## System Health")


@pytest.mark.asyncio
async def test_digest_fallback_on_error():
    from agent import _run_digest
    from observability.base import ObservabilityBackend

    class MockBackend(ObservabilityBackend):
        async def get_active_alerts(self):
            return []
        async def get_recent_metrics(self):
            raise Exception("Sumo Logic down")

    app_state = MagicMock()

    with patch("claude_client.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(
            return_value=_mock_claude_response("## System Health — now\n\nMetrics unavailable.")
        )
        await _run_digest(app_state, MockBackend())

    latest = storage.read_latest_digest()
    assert latest is not None

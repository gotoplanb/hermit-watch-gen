"""Tests for storage module."""

from __future__ import annotations

import pytest

import storage


@pytest.fixture(autouse=True)
def use_tmp_dir(tmp_path, monkeypatch):
    """Redirect storage to a temp directory."""
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.ensure_data_dirs()


class TestCurrentState:
    def test_write_and_read(self):
        data = {"worst_state": "calm", "updated_at": "2026-04-05T14:00:00Z"}
        storage.write_current_state(data)
        result = storage.read_current_state()
        assert result == data

    def test_read_missing_returns_none(self):
        assert storage.read_current_state() is None

    def test_overwrite(self):
        storage.write_current_state({"worst_state": "calm"})
        storage.write_current_state({"worst_state": "squall"})
        assert storage.read_current_state()["worst_state"] == "squall"


class TestIncidents:
    def test_write_and_read(self):
        ts = "2026-04-05T14:05:00Z"
        data = {"worst_state": "squall", "active_alert_count": 19}
        storage.write_incident(ts, data)
        result = storage.read_incident(ts)
        assert result == data

    def test_read_missing_returns_none(self):
        assert storage.read_incident("2026-01-01T00:00:00Z") is None

    def test_list_newest_first(self):
        storage.write_incident("2026-04-05T12:00:00Z", {"a": 1})
        storage.write_incident("2026-04-05T14:00:00Z", {"a": 2})
        storage.write_incident("2026-04-05T13:00:00Z", {"a": 3})
        result = storage.list_incidents()
        assert result == [
            "2026-04-05T14:00:00Z",
            "2026-04-05T13:00:00Z",
            "2026-04-05T12:00:00Z",
        ]


class TestDigests:
    def test_write_and_read(self):
        ts = "2026-04-05T14:00:00Z"
        content = "## System Health — 14:00 UTC\n\nAll good."
        storage.write_digest(ts, content)
        result = storage.read_digest(ts)
        assert result == {"generated_at": ts, "type": "scheduled", "content": content}

    def test_read_missing_returns_none(self):
        assert storage.read_digest("2026-01-01T00:00:00Z") is None

    def test_latest_digest(self):
        storage.write_digest("2026-04-05T12:00:00Z", "older")
        storage.write_digest("2026-04-05T14:00:00Z", "newer")
        result = storage.read_latest_digest()
        assert result["generated_at"] == "2026-04-05T14:00:00Z"
        assert result["content"] == "newer"

    def test_latest_digest_empty(self):
        assert storage.read_latest_digest() is None

    def test_list_newest_first(self):
        storage.write_digest("2026-04-05T12:00:00Z", "a")
        storage.write_digest("2026-04-05T14:00:00Z", "b")
        result = storage.list_digests()
        assert result[0] == "2026-04-05T14:00:00Z"


class TestCleanup:
    def test_cleanup_old_files(self):
        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        storage.write_incident("2020-01-01T00:00:00Z", {"old": True})
        storage.write_incident(now_ts, {"new": True})
        storage.cleanup_old_files(retention_days=7)

        assert storage.read_incident("2020-01-01T00:00:00Z") is None
        assert storage.read_incident(now_ts) is not None

    def test_cleanup_zero_retention_is_noop(self):
        storage.write_incident("2020-01-01T00:00:00Z", {"old": True})
        storage.cleanup_old_files(retention_days=0)
        assert storage.read_incident("2020-01-01T00:00:00Z") is not None

"""Tests for FastAPI API endpoints."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import storage


@pytest.fixture(autouse=True)
def use_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.ensure_data_dirs()
    # Ensure no auth token for most tests
    monkeypatch.setattr("main.READ_TOKEN", "")
    monkeypatch.setattr("main.WRITE_TOKEN", "")


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture
def populated_state():
    """Write a mock current-state.json for endpoint tests."""
    mock_path = os.path.join(os.path.dirname(__file__), "..", "mocks", "mock-status.json")
    with open(mock_path) as f:
        data = json.load(f)
    storage.write_current_state(data)
    return data


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "uptime_seconds" in body

    def test_health_no_auth_required(self, client, monkeypatch):
        monkeypatch.setattr("main.READ_TOKEN", "secret123")
        resp = client.get("/health")
        assert resp.status_code == 200


class TestStatus:
    def test_default_calm_when_no_state(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["worst_state"] == "calm"
        assert body["triage"] is None
        assert len(body["services"]) == 5

    def test_returns_current_state(self, client, populated_state):
        resp = client.get("/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["worst_state"] == "squall"
        assert body["triage"] is not None
        assert len(body["services"]) == 5


class TestServices:
    def test_sorted_worst_first(self, client, populated_state):
        resp = client.get("/services")
        assert resp.status_code == 200
        services = resp.json()
        states = [s["state"] for s in services]
        # squall should come before calm/serene
        assert states.index("squall") < states.index("serene")


class TestDigests:
    def test_latest_404_when_empty(self, client):
        resp = client.get("/digest/latest")
        assert resp.status_code == 404

    def test_latest_returns_digest(self, client):
        storage.write_digest("2026-04-05T14:00:00Z", "## Health\n\nAll good.")
        resp = client.get("/digest/latest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["generated_at"] == "2026-04-05T14:00:00Z"
        assert "Health" in body["content"]

    def test_list_digests(self, client):
        storage.write_digest("2026-04-05T12:00:00Z", "a")
        storage.write_digest("2026-04-05T14:00:00Z", "b")
        resp = client.get("/digests")
        assert resp.status_code == 200
        assert len(resp.json()["digests"]) == 2

    def test_specific_digest(self, client):
        storage.write_digest("2026-04-05T14:00:00Z", "content here")
        resp = client.get("/digest/2026-04-05T14:00:00Z")
        assert resp.status_code == 200

    def test_specific_digest_404(self, client):
        resp = client.get("/digest/2020-01-01T00:00:00Z")
        assert resp.status_code == 404


class TestIncidents:
    def test_empty_incidents(self, client):
        resp = client.get("/incidents")
        assert resp.status_code == 200
        assert resp.json()["incidents"] == []

    def test_list_incidents(self, client):
        storage.write_incident("2026-04-05T14:05:00Z", {
            "worst_state": "squall",
            "root_cause_alert": "Gibraltar-Expedia-5xx",
            "active_alert_count": 19,
        })
        resp = client.get("/incidents")
        assert resp.status_code == 200
        items = resp.json()["incidents"]
        assert len(items) == 1
        assert items[0]["worst_state"] == "squall"

    def test_specific_incident(self, client):
        storage.write_incident("2026-04-05T14:05:00Z", {"worst_state": "squall"})
        resp = client.get("/incidents/2026-04-05T14:05:00Z")
        assert resp.status_code == 200

    def test_specific_incident_404(self, client):
        resp = client.get("/incidents/2020-01-01T00:00:00Z")
        assert resp.status_code == 404


class TestAuth:
    def test_no_token_required_when_unset(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200

    def test_401_when_token_required(self, client, monkeypatch):
        monkeypatch.setattr("main.READ_TOKEN", "secret123")
        resp = client.get("/status")
        assert resp.status_code == 401

    def test_query_param_auth(self, client, monkeypatch):
        monkeypatch.setattr("main.READ_TOKEN", "secret123")
        resp = client.get("/status?token=secret123")
        assert resp.status_code == 200

    def test_bearer_auth(self, client, monkeypatch):
        monkeypatch.setattr("main.READ_TOKEN", "secret123")
        resp = client.get("/status", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200

    def test_wrong_token_401(self, client, monkeypatch):
        monkeypatch.setattr("main.READ_TOKEN", "secret123")
        resp = client.get("/status?token=wrong")
        assert resp.status_code == 401


class TestWriteAuth:
    def test_post_403_when_write_token_not_configured(self, client):
        resp = client.post("/status", json={"worst_state": "calm"})
        assert resp.status_code == 403

    def test_post_401_with_wrong_token(self, client, monkeypatch):
        monkeypatch.setattr("main.WRITE_TOKEN", "writepass")
        resp = client.post("/status", json={"worst_state": "calm"}, params={"token": "wrong"})
        assert resp.status_code == 401

    def test_post_auth_with_query_param(self, client, monkeypatch):
        monkeypatch.setattr("main.WRITE_TOKEN", "writepass")
        resp = client.post("/status?token=writepass", json={
            "worst_state": "calm", "triage": None, "active_alert_count": 0,
            "root_cause_alert": None, "noise_alert_count": 0,
            "services": [{"id": "test", "display_name": "Test", "state": "calm", "message": "ok"}],
        })
        assert resp.status_code == 200

    def test_post_auth_with_bearer(self, client, monkeypatch):
        monkeypatch.setattr("main.WRITE_TOKEN", "writepass")
        resp = client.post("/status", json={
            "worst_state": "calm", "triage": None, "active_alert_count": 0,
            "root_cause_alert": None, "noise_alert_count": 0,
            "services": [{"id": "test", "display_name": "Test", "state": "calm", "message": "ok"}],
        }, headers={"Authorization": "Bearer writepass"})
        assert resp.status_code == 200


class TestPostStatus:
    @pytest.fixture(autouse=True)
    def enable_write(self, monkeypatch):
        monkeypatch.setattr("main.WRITE_TOKEN", "w")

    def test_post_status_writes_state(self, client):
        resp = client.post("/status?token=w", json={
            "worst_state": "squall",
            "triage": "Test triage",
            "active_alert_count": 5,
            "root_cause_alert": "Test-Alert",
            "noise_alert_count": 4,
            "services": [
                {"id": "gibraltar", "display_name": "Gibraltar", "state": "squall", "message": "Error rate high"},
                {"id": "unicorn", "display_name": "Unicorn", "state": "calm", "message": "All systems nominal."},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        state = storage.read_current_state()
        assert state["worst_state"] == "squall"
        assert len(state["services"]) == 2
        assert state["updated_at"] is not None

    def test_post_status_invalid_state(self, client):
        resp = client.post("/status?token=w", json={
            "worst_state": "banana",
            "services": [{"id": "x", "display_name": "X", "state": "calm", "message": "ok"}],
        })
        assert resp.status_code == 422

    def test_post_status_empty_services(self, client):
        resp = client.post("/status?token=w", json={
            "worst_state": "calm", "services": [],
        })
        assert resp.status_code == 422


class TestPostDigest:
    @pytest.fixture(autouse=True)
    def enable_write(self, monkeypatch):
        monkeypatch.setattr("main.WRITE_TOKEN", "w")

    def test_post_digest_writes_file(self, client):
        resp = client.post("/digest?token=w", json={
            "content": "## System Health\n\nAll good.",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["generated_at"] is not None

        latest = storage.read_latest_digest()
        assert "System Health" in latest["content"]

    def test_post_digest_empty_content(self, client):
        resp = client.post("/digest?token=w", json={"content": ""})
        assert resp.status_code == 422


class TestPostIncident:
    @pytest.fixture(autouse=True)
    def enable_write(self, monkeypatch):
        monkeypatch.setattr("main.WRITE_TOKEN", "w")

    def test_post_incident_writes_file(self, client):
        resp = client.post("/incident?token=w", json={
            "worst_state": "storm",
            "triage": "Major outage",
            "active_alert_count": 25,
            "root_cause_alert": "Gibraltar-Down",
            "noise_alert_count": 24,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        incidents = storage.list_incidents()
        assert len(incidents) == 1

    def test_post_incident_invalid_state(self, client):
        resp = client.post("/incident?token=w", json={"worst_state": "invalid"})
        assert resp.status_code == 422


class TestSchema:
    def test_schema_returns_all_endpoints(self, client):
        resp = client.get("/schema")
        assert resp.status_code == 200
        endpoints = resp.json()["endpoints"]
        assert "POST /status" in endpoints
        assert "POST /digest" in endpoints
        assert "POST /incident" in endpoints
        assert "example" in endpoints["POST /status"]

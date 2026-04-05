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
    monkeypatch.setattr("main.API_TOKEN", "")


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
        monkeypatch.setattr("main.API_TOKEN", "secret123")
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
        monkeypatch.setattr("main.API_TOKEN", "secret123")
        resp = client.get("/status")
        assert resp.status_code == 401

    def test_query_param_auth(self, client, monkeypatch):
        monkeypatch.setattr("main.API_TOKEN", "secret123")
        resp = client.get("/status?token=secret123")
        assert resp.status_code == 200

    def test_bearer_auth(self, client, monkeypatch):
        monkeypatch.setattr("main.API_TOKEN", "secret123")
        resp = client.get("/status", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200

    def test_wrong_token_401(self, client, monkeypatch):
        monkeypatch.setattr("main.API_TOKEN", "secret123")
        resp = client.get("/status?token=wrong")
        assert resp.status_code == 401

"""Tests for generators.statuspage using fixture data."""

import copy
import json
import os

import pytest

from generators.statuspage import get_state

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "statuspage_response.json")


@pytest.fixture
def all_operational():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


@pytest.fixture
def degraded(all_operational):
    data = copy.deepcopy(all_operational)
    for c in data["components"]:
        if c["name"] == "Actions":
            c["status"] = "degraded_performance"
    data["status"]["indicator"] = "minor"
    data["status"]["description"] = "Minor System Outage"
    data["incidents"] = [{
        "name": "Degraded performance for Actions",
        "components": [{"name": "Actions"}],
    }]
    return data


@pytest.fixture
def partial_outage(all_operational):
    data = copy.deepcopy(all_operational)
    for c in data["components"]:
        if c["name"] == "Pages":
            c["status"] = "partial_outage"
    data["status"]["indicator"] = "major"
    data["incidents"] = [{
        "name": "Pages builds failing",
        "components": [{"name": "Pages"}],
    }]
    return data


class TestAllOperational:
    def test_component_state(self, all_operational):
        state, message = get_state(all_operational, "Actions")
        assert state == "serene"
        assert message == "All systems operational"

    def test_top_level_indicator(self, all_operational):
        state, message = get_state(all_operational)
        assert state == "serene"
        assert message == "All systems operational"


class TestDegradedComponent:
    def test_degraded_component_state(self, degraded):
        state, message = get_state(degraded, "Actions")
        assert state == "unsettled"
        assert "Degraded performance for Actions" in message

    def test_unaffected_component_calm(self, degraded):
        """An operational component is calm (not serene) when indicator is not none."""
        state, message = get_state(degraded, "Pages")
        assert state == "calm"

    def test_top_level_degraded(self, degraded):
        state, _ = get_state(degraded)
        assert state == "unsettled"


class TestPartialOutage:
    def test_partial_outage_state(self, partial_outage):
        state, message = get_state(partial_outage, "Pages")
        assert state == "squall"
        assert "Pages builds failing" in message

    def test_unaffected_component_message(self, partial_outage):
        state, message = get_state(partial_outage, "Actions")
        assert state == "calm"
        assert message == "All systems operational"


class TestComponentFiltering:
    def test_missing_component_raises(self, all_operational):
        with pytest.raises(ValueError, match="not found"):
            get_state(all_operational, "Nonexistent")

    def test_correct_component_selected(self, all_operational):
        state, _ = get_state(all_operational, "Pull Requests")
        assert state == "serene"


class TestFallbackToIndicator:
    def test_no_component_uses_indicator(self, all_operational):
        state, _ = get_state(all_operational)
        assert state == "serene"

"""Tests for generators.base.normalize_state."""

import pytest

from generators.base import normalize_state


class TestNamedStates:
    @pytest.mark.parametrize("name", ["serene", "calm", "unsettled", "squall", "storm"])
    def test_valid_named_states(self, name):
        assert normalize_state(name) == name

    @pytest.mark.parametrize("name", ["Serene", "CALM", "Unsettled", " squall ", "STORM"])
    def test_case_insensitive_and_stripped(self, name):
        assert normalize_state(name) == name.lower().strip()


class TestNumericAliases:
    @pytest.mark.parametrize("num,expected", [
        (1, "storm"),
        (2, "squall"),
        (3, "unsettled"),
        (4, "calm"),
        (5, "serene"),
    ])
    def test_numeric_aliases(self, num, expected):
        assert normalize_state(num) == expected

    def test_invalid_numeric(self):
        with pytest.raises(ValueError, match="Unknown numeric state: 0"):
            normalize_state(0)

    def test_out_of_range_numeric(self):
        with pytest.raises(ValueError, match="Unknown numeric state: 6"):
            normalize_state(6)


class TestStatuspageIndicators:
    @pytest.mark.parametrize("indicator,expected", [
        ("none", "serene"),
        ("minor", "unsettled"),
        ("major", "squall"),
        ("critical", "storm"),
    ])
    def test_statuspage_indicators(self, indicator, expected):
        assert normalize_state(indicator) == expected


class TestErrors:
    def test_unknown_string(self):
        with pytest.raises(ValueError, match="Unknown state"):
            normalize_state("banana")

    def test_wrong_type(self):
        with pytest.raises(ValueError, match="must be a string or int"):
            normalize_state([1, 2, 3])

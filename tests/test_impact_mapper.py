"""Tests for impact_mapper — event-to-profile impact propagation."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "alerts"))
import impact_mapper as im  # noqa: E402


# ── Helpers ──────────────────────────────────────────


def _make_search_profiles_fn(profiles_by_kind=None):
    """Create a mock search_profiles function."""
    if profiles_by_kind is None:
        profiles_by_kind = {}

    def search_profiles(kind, field, value):
        kind_profiles = profiles_by_kind.get(kind, [])
        return [p for p in kind_profiles
                if value in p.get("exposure", {}).get("countries", [])]

    return search_profiles


def _make_snapshot_fn():
    """Create a mock snapshot function that records calls."""
    calls = []

    def snapshot_fn(kind, entity, type, data, source="", **kw):
        calls.append({"kind": kind, "entity": entity, "type": type,
                       "data": data, "source": source})
        return {"id": f"mock_{len(calls)}", "status": "ok"}

    snapshot_fn.calls = calls
    return snapshot_fn


# ── Tests ────────────────────────────────────────────


class TestShouldPropagate:
    def test_high_severity(self):
        assert im.should_propagate("high") is True

    def test_critical_severity(self):
        assert im.should_propagate("critical") is True

    def test_medium_severity(self):
        assert im.should_propagate("medium") is False

    def test_low_severity(self):
        assert im.should_propagate("low") is False


class TestFindExposedProfiles:
    def test_finds_exposed_stocks(self):
        profiles = {
            "stocks": [
                {"id": "AAPL", "name": "Apple",
                 "exposure": {"countries": ["USA", "CHN"]}},
                {"id": "TSM", "name": "TSMC",
                 "exposure": {"countries": ["TWN", "JPN"]}},
            ],
        }
        search = _make_search_profiles_fn(profiles)
        result = im.find_exposed_profiles(["JPN"], search, kinds=("stocks",))

        assert len(result) == 1
        assert result[0]["id"] == "TSM"
        assert result[0]["kind"] == "stocks"
        assert "JPN" in result[0]["matched_countries"]

    def test_multiple_countries_match(self):
        profiles = {
            "stocks": [
                {"id": "AAPL", "name": "Apple",
                 "exposure": {"countries": ["USA", "CHN", "JPN"]}},
            ],
        }
        search = _make_search_profiles_fn(profiles)
        result = im.find_exposed_profiles(["CHN", "JPN"], search, kinds=("stocks",))

        assert len(result) == 1
        assert result[0]["id"] == "AAPL"
        # Both countries should be in matched_countries
        assert set(result[0]["matched_countries"]) == {"CHN", "JPN"}

    def test_no_match(self):
        profiles = {
            "stocks": [
                {"id": "AAPL", "name": "Apple",
                 "exposure": {"countries": ["USA"]}},
            ],
        }
        search = _make_search_profiles_fn(profiles)
        result = im.find_exposed_profiles(["JPN"], search, kinds=("stocks",))
        assert result == []

    def test_empty_countries(self):
        search = _make_search_profiles_fn()
        result = im.find_exposed_profiles([], search)
        assert result == []

    def test_multiple_kinds(self):
        profiles = {
            "stocks": [
                {"id": "TSM", "name": "TSMC",
                 "exposure": {"countries": ["JPN"]}},
            ],
            "commodities": [
                {"id": "rice", "name": "Rice",
                 "exposure": {"countries": ["JPN", "CHN"]}},
            ],
        }
        search = _make_search_profiles_fn(profiles)
        result = im.find_exposed_profiles(
            ["JPN"], search, kinds=("stocks", "commodities"))

        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert ids == {"TSM", "rice"}

    def test_search_error_handled(self):
        def failing_search(kind, field, value):
            raise RuntimeError("DB down")

        result = im.find_exposed_profiles(["JPN"], failing_search,
                                          kinds=("stocks",))
        assert result == []


class TestPropagateEventImpact:
    def test_creates_impact_snapshots(self):
        profiles = {
            "stocks": [
                {"id": "TSM", "name": "TSMC",
                 "exposure": {"countries": ["JPN"]}},
            ],
        }
        search = _make_search_profiles_fn(profiles)
        snapshot = _make_snapshot_fn()

        meta = {"subtype": "earthquake", "severity": "high",
                "countries": ["JPN"], "entities": [], "region": "east_asia"}
        impacts = im.propagate_event_impact(
            meta, "Major earthquake in Japan", {"magnitude": 7.2},
            search_profiles_fn=search, snapshot_fn=snapshot,
            event_id="evt_123",
        )

        assert len(impacts) == 1
        assert impacts[0]["id"] == "TSM"
        assert "JPN" in impacts[0]["matched_countries"]

        # Check snapshot was stored
        assert len(snapshot.calls) == 1
        snap = snapshot.calls[0]
        assert snap["kind"] == "stocks"
        assert snap["entity"] == "TSM"
        assert snap["type"] == "impact"
        assert snap["source"] == "impact_mapper"
        assert snap["data"]["event_id"] == "evt_123"
        assert snap["data"]["event_severity"] == "high"

    def test_skips_medium_severity(self):
        search = _make_search_profiles_fn()
        snapshot = _make_snapshot_fn()

        meta = {"subtype": "policy_change", "severity": "medium",
                "countries": ["USA"]}
        impacts = im.propagate_event_impact(
            meta, "Policy update", {},
            search_profiles_fn=search, snapshot_fn=snapshot,
        )
        assert impacts == []
        assert len(snapshot.calls) == 0

    def test_skips_no_countries(self):
        search = _make_search_profiles_fn()
        snapshot = _make_snapshot_fn()

        meta = {"subtype": "market_crash", "severity": "critical",
                "countries": []}
        impacts = im.propagate_event_impact(
            meta, "Global market crash", {},
            search_profiles_fn=search, snapshot_fn=snapshot,
        )
        assert impacts == []

    def test_snapshot_error_handled(self):
        profiles = {
            "stocks": [
                {"id": "AAPL", "name": "Apple",
                 "exposure": {"countries": ["USA"]}},
            ],
        }
        search = _make_search_profiles_fn(profiles)

        def failing_snapshot(**kw):
            raise RuntimeError("DB write failed")

        meta = {"subtype": "sanction", "severity": "critical",
                "countries": ["USA"]}
        # Should not raise
        impacts = im.propagate_event_impact(
            meta, "New sanctions", {},
            search_profiles_fn=search, snapshot_fn=failing_snapshot,
        )
        assert impacts == []

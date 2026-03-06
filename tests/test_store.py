"""Tests for the signals store MCP server (src/store/server.py).

Tests profile filesystem operations (no MongoDB needed) and validates
MongoDB-dependent tools with mocked pymongo.

Note: FastMCP @mcp.tool() wraps functions into FunctionTool objects.
We call .fn() to invoke the original function.
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta

# Patch env before importing store module
os.environ.setdefault("MONGO_URI", "mongodb://fake:27017/test")
os.environ.setdefault("PROFILES_DIR", "/tmp/fake_profiles")

import src.store.server as store

# Unwrap MCP tool functions to their original callables
_get_profile = store.get_profile.fn
_put_profile = store.put_profile.fn
_list_profiles = store.list_profiles.fn
_find_profile = store.find_profile.fn
_search_profiles = store.search_profiles.fn
_list_regions = store.list_regions.fn
_rebuild_index = store.rebuild_index.fn
_lint_profiles = store.lint_profiles.fn
_snapshot = store.snapshot.fn
_event = store.event.fn
_history = store.history.fn
_recent_events = store.recent_events.fn
_nearby = store.nearby.fn
_trend = store.trend.fn
_aggregate = store.aggregate.fn
_chart = store.chart.fn
_archive_snapshot = store.archive_snapshot.fn
_archive_history = store.archive_history.fn
_compact = store.compact.fn


# ── Helper & validation tests ────────────────────────


class TestSafeIdRegex:
    def test_valid_ids(self):
        assert store._SAFE_ID.match("AAPL")
        assert store._SAFE_ID.match("DEU")
        assert store._SAFE_ID.match("crude_oil")
        assert store._SAFE_ID.match("ev-batteries")
        assert store._SAFE_ID.match("A123")

    def test_invalid_ids(self):
        assert not store._SAFE_ID.match("")
        assert not store._SAFE_ID.match("../etc")
        assert not store._SAFE_ID.match("a b")
        assert not store._SAFE_ID.match("a/b")
        assert not store._SAFE_ID.match("a.json")


class TestValidKinds:
    def test_expected_kinds_present(self):
        expected = {
            "countries", "stocks", "etfs", "crypto", "indices",
            "sources", "commodities", "crops", "materials",
            "products", "companies",
        }
        assert expected == store.VALID_KINDS

    def test_kinds_is_frozenset(self):
        assert isinstance(store.VALID_KINDS, frozenset)


class TestSer:
    def test_serializes_objectid(self):
        doc = {"_id": "abc123", "data": {"x": 1}}
        result = store._ser(doc)
        assert result["_id"] == "abc123"

    def test_serializes_datetime(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        doc = {"_id": "x", "ts": ts, "data": {}}
        result = store._ser(doc)
        assert result["ts"] == "2025-01-15T12:00:00+00:00"

    def test_flattens_meta(self):
        doc = {"_id": "x", "meta": {"entity": "DEU", "kind": "countries"}, "data": {}}
        result = store._ser(doc)
        assert result["entity"] == "DEU"
        assert result["kind"] == "countries"
        assert "meta" not in result


# ── Profile filesystem tests ─────────────────────────


class TestRegions:
    def test_discovers_regions(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            regions = store._regions()
        assert "europe" in regions
        assert "north_america" in regions
        assert "global" in regions
        assert "SCHEMAS" not in regions

    def test_empty_profiles(self, tmp_path):
        with patch.object(store, "PROFILES", tmp_path / "nonexistent"):
            assert store._regions() == []


class TestFindProfilePath:
    def test_finds_existing_profile(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            p = store._find_profile_path("countries", "DEU")
        assert p is not None
        assert p.name == "DEU.json"

    def test_returns_none_for_missing(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            p = store._find_profile_path("countries", "XYZ")
        assert p is None


class TestSafeProfilePath:
    def test_valid_path(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            p, err = store._safe_profile_path("europe", "countries", "DEU")
        assert err is None
        assert "europe/countries/DEU.json" in str(p)

    def test_rejects_invalid_id(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            _, err = store._safe_profile_path("europe", "countries", "../etc")
        assert err is not None
        assert "invalid id" in err["error"]

    def test_rejects_invalid_region(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            _, err = store._safe_profile_path("../bad", "countries", "DEU")
        assert err is not None
        assert "invalid region" in err["error"]

    def test_rejects_unknown_kind(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            _, err = store._safe_profile_path("europe", "badkind", "DEU")
        assert err is not None
        assert "unknown kind" in err["error"]


# ── Profile tool tests ───────────────────────────────


class TestGetProfile:
    def test_get_existing_with_region(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _get_profile("countries", "DEU", region="europe")
        assert result["name"] == "Germany"
        assert result["iso2"] == "DE"

    def test_get_existing_scan_all_regions(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _get_profile("countries", "USA")
        assert result["name"] == "United States"

    def test_get_nonexistent(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _get_profile("countries", "XYZ")
        assert "error" in result
        assert "not found" in result["error"]

    def test_get_invalid_kind(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _get_profile("badkind", "DEU")
        assert "error" in result
        assert "unknown kind" in result["error"]

    def test_get_invalid_id(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _get_profile("countries", "../etc/passwd")
        assert "error" in result
        assert "invalid id" in result["error"]


class TestPutProfile:
    def test_create_new_profile(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _put_profile("stocks", "MSFT",
                                  {"name": "Microsoft", "sector": "Technology"},
                                  region="north_america")
        assert result["status"] == "ok"
        assert result["region"] == "north_america"
        p = tmp_profiles / "north_america" / "stocks" / "MSFT.json"
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["name"] == "Microsoft"
        assert "_updated" in data

    def test_merge_existing_profile(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _put_profile("countries", "DEU",
                                  {"population": 83_000_000})
        assert result["status"] == "ok"
        assert result["region"] == "europe"
        data = json.loads((tmp_profiles / "europe" / "countries" / "DEU.json").read_text())
        assert data["name"] == "Germany"  # preserved
        assert data["population"] == 83_000_000  # added

    def test_put_invalid_kind(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _put_profile("badkind", "X", {"name": "test"})
        assert "error" in result

    def test_put_invalid_id(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _put_profile("stocks", "../../bad", {"name": "test"})
        assert "error" in result

    def test_default_region_global(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _put_profile("sources", "test_src", {"name": "Test Source"})
        assert result["status"] == "ok"
        assert result["region"] == "global"


class TestListProfiles:
    def test_list_all_stocks(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _list_profiles("stocks")
        ids = [r["id"] for r in result]
        assert "AAPL" in ids
        assert "SAP" in ids

    def test_list_by_region(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _list_profiles("stocks", region="europe")
        ids = [r["id"] for r in result]
        assert "SAP" in ids
        assert "AAPL" not in ids

    def test_list_invalid_kind(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _list_profiles("badkind")
        assert result == []


class TestFindProfile:
    def test_find_by_name(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            store._rebuild_all_indexes()
            result = _find_profile("Germany")
        assert len(result) >= 1
        assert any(r["id"] == "DEU" for r in result)

    def test_find_by_tag(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            store._rebuild_all_indexes()
            result = _find_profile("g7")
        ids = [r["id"] for r in result]
        assert "DEU" in ids
        assert "USA" in ids

    def test_find_by_region_filter(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            store._rebuild_all_indexes()
            result = _find_profile("g7", region="europe")
        ids = [r["id"] for r in result]
        assert "DEU" in ids
        assert "USA" not in ids

    def test_find_no_match(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            store._rebuild_all_indexes()
            result = _find_profile("zzzznonexistent")
        assert result == []


class TestSearchProfiles:
    def test_search_by_sector(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _search_profiles("stocks", "sector", "Technology")
        assert len(result) >= 1
        names = [r["name"] for r in result]
        assert "Apple Inc." in names or "SAP SE" in names

    def test_search_by_tag(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _search_profiles("countries", "tags", "eu")
        assert len(result) == 1
        assert result[0]["name"] == "Germany"


class TestListRegions:
    def test_lists_regions_with_kinds(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _list_regions()
        region_names = [r["region"] for r in result]
        assert "europe" in region_names
        assert "north_america" in region_names
        europe = next(r for r in result if r["region"] == "europe")
        assert "countries" in europe["kinds"]
        assert "stocks" in europe["kinds"]


# ── Index tests ──────────────────────────────────────


class TestIndexOperations:
    def test_rebuild_kind_index(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            entries = store._rebuild_kind_index("countries")
        assert len(entries) == 2
        ids = [e["id"] for e in entries]
        assert "DEU" in ids
        assert "USA" in ids
        idx_path = tmp_profiles / "INDEX_countries.json"
        assert idx_path.exists()

    def test_rebuild_all_indexes(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            total = store._rebuild_all_indexes()
        assert total >= 6  # DEU, USA, AAPL, SAP, crude_oil, faostat

    def test_index_entry_format(self):
        data = {"name": "Test", "tags": ["a", "b"], "sector": "Tech"}
        entry = store._index_entry("stocks", "TST", data, "global")
        assert entry == {
            "id": "TST", "kind": "stocks", "name": "Test",
            "region": "global", "tags": ["a", "b"], "sector": "Tech",
        }

    def test_update_index_incremental(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            store._rebuild_kind_index("stocks")
            store._update_index("stocks", "NEW", {"name": "New Stock"}, "global")
            idx = json.loads((tmp_profiles / "INDEX_stocks.json").read_text())
        ids = [e["id"] for e in idx]
        assert "NEW" in ids
        assert "AAPL" in ids
        assert "SAP" in ids

    def test_rebuild_index_tool(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _rebuild_index("countries")
        assert result["status"] == "ok"
        assert result["kind"] == "countries"
        assert result["entries"] == 2

    def test_rebuild_all_index_tool(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _rebuild_index()
        assert result["status"] == "ok"
        assert "kinds" in result


# ── Lint tests ───────────────────────────────────────


class TestLintProfiles:
    def test_lint_valid_profile(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _lint_profiles("stocks", "SAP")
        assert "stocks/SAP" in result["ok"]
        assert not result["issues"]

    def test_lint_detects_missing_required(self, tmp_profiles):
        bad = tmp_profiles / "global" / "stocks"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "BAD.json").write_text(json.dumps({"ticker": "BAD"}))
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _lint_profiles("stocks", "BAD")
        assert "stocks/BAD" in result["issues"]
        assert any("missing required" in i for i in result["issues"]["stocks/BAD"])

    def test_lint_all_kinds(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _lint_profiles()
        assert len(result["ok"]) >= 4

    def test_lint_nonexistent(self, tmp_profiles):
        with patch.object(store, "PROFILES", tmp_profiles):
            result = _lint_profiles("stocks", "NONEXISTENT")
        assert "stocks/NONEXISTENT" in result["issues"]


# ── Snapshot tool tests (mocked MongoDB) ─────────────


class TestSnapshotTools:
    @pytest.fixture(autouse=True)
    def _reset_store_state(self):
        """Reset module-level state between tests."""
        store._client = None
        store._cols_ready = set()
        yield
        store._client = None
        store._cols_ready = set()

    def test_snapshot_rejects_invalid_kind(self):
        result = _snapshot("badkind", "X", "price", {"close": 100})
        assert "error" in result

    def test_snapshot_inserts_doc(self, mock_mongo):
        client, db = mock_mongo
        mock_col = MagicMock()
        mock_col.insert_one.return_value = MagicMock(inserted_id="abc123")
        db.__getitem__ = MagicMock(return_value=mock_col)
        store._client = client
        store._cols_ready = {"snap_stocks", "snap_stocks_geo"}

        result = _snapshot("stocks", "AAPL", "price",
                           {"close": 150.0, "volume": 1_000_000})
        assert result["status"] == "ok"
        assert result["collection"] == "snap_stocks"
        mock_col.insert_one.assert_called_once()
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["meta"]["entity"] == "AAPL"
        assert doc["data"]["close"] == 150.0

    def test_snapshot_with_geo(self, mock_mongo):
        client, db = mock_mongo
        mock_col = MagicMock()
        mock_col.insert_one.return_value = MagicMock(inserted_id="geo123")
        db.__getitem__ = MagicMock(return_value=mock_col)
        store._client = client
        store._cols_ready = {"snap_countries", "snap_countries_geo"}

        result = _snapshot("countries", "DEU", "indicators",
                           {"gdp": 4.0}, lon=10.45, lat=51.16)
        assert result["status"] == "ok"
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["location"]["type"] == "Point"
        assert doc["location"]["coordinates"] == [10.45, 51.16]

    def test_event_inserts(self, mock_mongo):
        client, db = mock_mongo
        mock_col = MagicMock()
        mock_col.insert_one.return_value = MagicMock(inserted_id="evt1")
        db.__getitem__ = MagicMock(return_value=mock_col)
        db.events = mock_col
        store._client = client
        store._cols_ready = {"events", "events_geo"}

        result = _event("earthquake", "Major earthquake in Turkey",
                        {"magnitude": 7.2}, severity="critical",
                        countries=["TUR"], region="mena")
        assert result["status"] == "ok"
        doc = mock_col.insert_one.call_args[0][0]
        assert doc["meta"]["subtype"] == "earthquake"
        assert doc["meta"]["severity"] == "critical"
        assert doc["summary"] == "Major earthquake in Turkey"

    def test_history_rejects_invalid_kind(self):
        result = _history("badkind", "X")
        assert result[0]["error"]

    def test_aggregate_blocks_write_stages(self, mock_mongo):
        client, db = mock_mongo
        store._client = client
        store._cols_ready = {"snap_stocks", "snap_stocks_geo"}

        for stage in ["$out", "$merge", "$unionWith"]:
            result = _aggregate("stocks", [{stage: "target"}])
            assert result[0]["error"]
            assert "not allowed" in result[0]["error"]

    def test_aggregate_rejects_invalid_kind(self):
        result = _aggregate("badkind", [{"$match": {}}])
        assert result[0]["error"]

    def test_archive_snapshot_rejects_invalid_kind(self):
        result = _archive_snapshot("badkind", "X", "type", {})
        assert "error" in result

    def test_archive_snapshot_inserts(self, mock_mongo):
        client, db = mock_mongo
        mock_col = MagicMock()
        mock_col.insert_one.return_value = MagicMock(inserted_id="arch1")
        db.__getitem__ = MagicMock(return_value=mock_col)
        store._client = client
        store._cols_ready = {"arch_countries"}

        result = _archive_snapshot("countries", "DEU", "indicators",
                                   {"gdp": 3.8}, region="europe")
        assert result["status"] == "ok"
        assert result["collection"] == "arch_countries"

    def test_compact_rejects_invalid_kind(self):
        result = _compact("badkind", "X", "price")
        assert "error" in result

    def test_compact_invalid_bucket(self, mock_mongo):
        client, db = mock_mongo
        mock_col = MagicMock()
        db.__getitem__ = MagicMock(return_value=mock_col)
        store._client = client
        store._cols_ready = {"snap_stocks", "snap_stocks_geo"}

        result = _compact("stocks", "AAPL", "price", bucket="decade")
        assert "error" in result
        assert "invalid bucket" in result["error"]

    def test_chart_rejects_invalid_kind(self, mock_mongo):
        result = _chart("badkind", "X", "price", ["close"])
        assert "Unknown kind" in result

    def test_nearby_rejects_invalid_kind(self):
        result = _nearby("badkind", 10.0, 50.0)
        assert result[0]["error"]

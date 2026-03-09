"""Tests for signals store profile, index, and lint logic.

These tests exercise profile CRUD, search, lint, and seed logic using
mongomock (CI, where pymongo imports) or a lightweight _FakeCollection
fallback (Claude Code sandbox, where pymongo/cffi is broken).
"""
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add src/ to path so we can import the store module's internals
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "store"))

# Prevent module-level MongoClient from connecting
os.environ.setdefault("MONGO_URI_SIGNALS", "mongodb://localhost:27017/test_unused")

# Detect mongomock availability (flag set by conftest.py)
from conftest import _USE_MONGOMOCK
if _USE_MONGOMOCK:
    import mongomock


# ── In-memory MongoDB mock ──────────────────────


class _FakeCollection:
    """In-memory MongoDB collection mock supporting profile and notes queries."""

    def __init__(self):
        self._docs: list[dict] = []
        self._counter = 0

    def insert_one(self, doc):
        self._counter += 1
        doc.setdefault("_id", f"fake_{self._counter}")
        self._docs.append(doc.copy())
        result = MagicMock()
        result.inserted_id = doc["_id"]
        return result

    def find_one(self, filter_, *args):
        for d in self._docs:
            if self._matches(d, filter_):
                out = d.copy()
                return out
        return None

    def update_one(self, filter_, update, upsert=False):
        matched = [d for d in self._docs if self._matches(d, filter_)]
        result = MagicMock()
        if matched:
            doc = matched[0]
            for k, v in update.get("$set", {}).items():
                doc[k] = v
            result.matched_count = 1
            result.upserted_id = None
        elif upsert:
            new_doc = {}
            new_doc.update(update.get("$setOnInsert", {}))
            new_doc.update(update.get("$set", {}))
            self._counter += 1
            new_doc["_id"] = f"fake_{self._counter}"
            self._docs.append(new_doc)
            result.matched_count = 0
            result.upserted_id = new_doc["_id"]
        else:
            result.matched_count = 0
            result.upserted_id = None
        return result

    def delete_one(self, filter_):
        before = len(self._docs)
        self._docs = [d for d in self._docs if not self._matches(d, filter_)]
        result = MagicMock()
        result.deleted_count = before - len(self._docs)
        return result

    def distinct(self, field):
        vals = set()
        for d in self._docs:
            v = d.get(field)
            if v is not None:
                vals.add(v)
        return list(vals)

    def drop(self):
        self._docs.clear()
        self._counter = 0

    def create_index(self, *args, **kwargs):
        pass  # no-op in tests

    def find(self, filter_=None, projection=None):
        filter_ = filter_ or {}
        matches = []
        for d in self._docs:
            if self._matches(d, filter_):
                out = d.copy()
                if projection:
                    # Detect exclusion vs inclusion projection
                    excl_keys = {k for k, v in projection.items() if v == 0}
                    incl_keys = {k for k, v in projection.items() if v != 0}
                    if excl_keys and not incl_keys:
                        # Exclusion: remove specified keys
                        for k in excl_keys:
                            out.pop(k, None)
                    elif incl_keys:
                        # Inclusion: keep only specified keys (+ _id unless excluded)
                        keep = {k: out[k] for k in out if k in incl_keys or (k == "_id" and "_id" not in excl_keys)}
                        out = keep
                matches.append(out)
        return _FakeCursor(matches)

    def _matches(self, doc, filter_):
        for k, v in filter_.items():
            if k == "$text":
                # Simple text search: check if search term in name/tags/sector
                search = v.get("$search", "").lower()
                name = doc.get("name", "").lower()
                tags = " ".join(doc.get("tags", [])).lower()
                sector = (doc.get("sector") or "").lower()
                if search not in name and search not in tags and search not in sector:
                    return False
            elif isinstance(v, re.Pattern):
                doc_val = doc.get(k, "")
                if isinstance(doc_val, str):
                    if not v.search(doc_val):
                        return False
                else:
                    return False
            elif isinstance(v, dict):
                # MongoDB operators like $nearSphere, $in — skip for simplicity
                continue
            else:
                doc_val = doc.get(k)
                if isinstance(doc_val, list) and not isinstance(v, list):
                    if v not in doc_val:
                        return False
                elif doc_val != v:
                    return False
        return True


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, field, direction=1):
        return _FakeCursor(self._docs)

    def limit(self, n):
        return self._docs[:n]

    def __iter__(self):
        return iter(self._docs)


# ── Fixtures ────────────────────────────────────


@pytest.fixture(autouse=True)
def profiles_dir(tmp_path, monkeypatch):
    """Set up a temporary profiles directory and wire up fake MongoDB collections."""
    import server

    monkeypatch.setattr(server, "PROFILES_DIR", tmp_path)

    # Create SCHEMAS dir with a countries schema
    schemas = tmp_path / "SCHEMAS"
    schemas.mkdir()
    schema = {
        "$schema": "Profile schema for countries",
        "required": ["id", "name"],
        "properties": {
            "id": "ISO3 country code",
            "name": "Full country name",
            "tags": "Array of group memberships",
        },
    }
    (schemas / "countries.schema.json").write_text(json.dumps(schema))

    # Create seed data directories for seed_profiles tests
    for region in ("europe", "north_america", "global"):
        for kind in ("countries", "stocks", "sources"):
            (tmp_path / region / kind).mkdir(parents=True)

    # Wire up mock collections for profiles_{kind}
    if _USE_MONGOMOCK:
        # CI: use mongomock (full pymongo API compatibility)
        mock_client = mongomock.MongoClient()
        mock_db = mock_client["test_profiles"]

        def fake_profiles_col(kind):
            return mock_db[f"profiles_{kind}"]
    else:
        # Sandbox fallback: lightweight custom mock
        _profile_cols: dict[str, _FakeCollection] = {}

        def fake_profiles_col(kind):
            if kind not in _profile_cols:
                _profile_cols[kind] = _FakeCollection()
            return _profile_cols[kind]

    monkeypatch.setattr(server, "_profiles_col", fake_profiles_col)

    yield tmp_path

    if _USE_MONGOMOCK:
        mock_client.close()


@pytest.fixture
def store():
    import server
    return server


# ── Profile validation ──────────────────────────


class TestValidateProfileArgs:
    def test_valid_args(self, store):
        assert store._validate_profile_args("countries", "DEU") is None

    def test_invalid_id_rejected(self, store):
        err = store._validate_profile_args("countries", "../etc/passwd")
        assert err is not None
        assert "invalid id" in err["error"]

    def test_invalid_region_rejected(self, store):
        err = store._validate_profile_args("countries", "DEU", "../../etc")
        assert err is not None
        assert "invalid region" in err["error"]

    def test_unknown_kind_rejected(self, store):
        err = store._validate_profile_args("weapons", "AK47")
        assert err is not None
        assert "unknown kind" in err["error"]


# ── get_profile ──────────────────────────────────


class TestGetProfile:
    def test_reads_existing_profile(self, store, profiles_dir):
        store.put_profile("countries", "DEU", {"id": "DEU", "name": "Germany"},
                          region="europe")
        result = store.get_profile("countries", "DEU")
        assert result["name"] == "Germany"

    def test_finds_without_region(self, store, profiles_dir):
        store.put_profile("countries", "USA", {"id": "USA", "name": "United States"},
                          region="north_america")
        result = store.get_profile("countries", "USA")
        assert result["name"] == "United States"

    def test_not_found_returns_error(self, store):
        result = store.get_profile("countries", "ZZZ")
        assert "error" in result

    def test_invalid_kind_returns_error(self, store):
        result = store.get_profile("invalid_kind", "FOO")
        assert "error" in result

    def test_invalid_id_returns_error(self, store):
        result = store.get_profile("countries", "../hack")
        assert "error" in result


# ── put_profile ──────────────────────────────────


class TestPutProfile:
    def test_creates_new_profile(self, store, profiles_dir):
        result = store.put_profile("countries", "FRA",
                                   {"id": "FRA", "name": "France"},
                                   region="europe")
        assert result["status"] == "ok"
        assert result["region"] == "europe"
        prof = store.get_profile("countries", "FRA")
        assert prof["name"] == "France"
        assert "_updated" in prof

    def test_merges_with_existing(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany", "currency": "EUR"},
                          region="europe")
        result = store.put_profile("countries", "DEU",
                                   {"population": 83_000_000})
        assert result["status"] == "ok"
        prof = store.get_profile("countries", "DEU")
        assert prof["currency"] == "EUR"
        assert prof["population"] == 83_000_000

    def test_updates_in_existing_region(self, store, profiles_dir):
        """If profile exists in europe, put_profile with region=global still uses europe."""
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany"}, region="europe")
        result = store.put_profile("countries", "DEU",
                                   {"capital": "Berlin"}, region="global")
        assert result["region"] == "europe"

    def test_defaults_to_global_region(self, store, profiles_dir):
        result = store.put_profile("sources", "test_src",
                                   {"id": "test_src", "name": "Test Source"})
        assert result["region"] == "global"

    def test_rejects_invalid_id(self, store):
        result = store.put_profile("countries", "../bad", {"name": "bad"})
        assert "error" in result

    def test_geo_location_stored(self, store):
        result = store.put_profile("countries", "JPN",
                                   {"id": "JPN", "name": "Japan"},
                                   region="east_asia", lon=139.6917, lat=35.6895)
        assert result["status"] == "ok"
        prof = store.get_profile("countries", "JPN")
        assert prof["location"]["type"] == "Point"
        assert prof["location"]["coordinates"] == [139.6917, 35.6895]


# ── list_profiles ────────────────────────────────


class TestListProfiles:
    def test_lists_all_regions(self, store, profiles_dir):
        store.put_profile("countries", "DEU", {"id": "DEU", "name": "Germany"},
                          region="europe")
        store.put_profile("countries", "USA", {"id": "USA", "name": "United States"},
                          region="north_america")
        result = store.list_profiles("countries")
        ids = [e["id"] for e in result]
        assert "DEU" in ids
        assert "USA" in ids

    def test_filters_by_region(self, store, profiles_dir):
        store.put_profile("countries", "DEU", {"id": "DEU", "name": "Germany"},
                          region="europe")
        store.put_profile("countries", "USA", {"id": "USA", "name": "United States"},
                          region="north_america")
        result = store.list_profiles("countries", region="europe")
        ids = [e["id"] for e in result]
        assert "DEU" in ids
        assert "USA" not in ids

    def test_unknown_kind_returns_empty(self, store):
        result = store.list_profiles("nonexistent")
        assert result == []


# ── find_profile (cross-kind search) ────────────


class TestFindProfile:
    def test_finds_by_name(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany"},
                          region="europe")
        result = store.find_profile("Germany")
        assert any(e["id"] == "DEU" for e in result)

    def test_finds_by_id(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany"},
                          region="europe")
        result = store.find_profile("DEU")
        assert any(e["id"] == "DEU" for e in result)

    def test_finds_by_tag(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany", "tags": ["EU", "G7"]},
                          region="europe")
        result = store.find_profile("EU")
        assert any(e["id"] == "DEU" for e in result)

    def test_filters_by_region(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany"},
                          region="europe")
        result = store.find_profile("DEU", region="north_america")
        assert not any(e["id"] == "DEU" for e in result)


# ── list_regions ─────────────────────────────────


class TestListRegions:
    def test_returns_regions_with_kinds(self, store, profiles_dir):
        store.put_profile("countries", "DEU", {"id": "DEU", "name": "Germany"},
                          region="europe")
        store.put_profile("stocks", "SAP", {"id": "SAP", "name": "SAP SE"},
                          region="europe")
        result = store.list_regions()
        region_names = [r["region"] for r in result]
        assert "europe" in region_names
        europe = next(r for r in result if r["region"] == "europe")
        assert "countries" in europe["kinds"]
        assert "stocks" in europe["kinds"]


# ── lint_profiles ────────────────────────────────


class TestLintProfiles:
    def test_valid_profile_passes(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany"},
                          region="europe")
        result = store.lint_profiles("countries", "DEU")
        assert "countries/DEU" in result["ok"]
        assert "countries/DEU" not in result["issues"]

    def test_missing_required_field_flagged(self, store, profiles_dir):
        # Profile without "name" (required by schema)
        store.put_profile("countries", "BAD", {"id": "BAD"}, region="europe")
        result = store.lint_profiles("countries", "BAD")
        assert "countries/BAD" in result["issues"]
        issues = result["issues"]["countries/BAD"]
        assert any("name" in i for i in issues)

    def test_lint_all_of_kind(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany"}, region="europe")
        store.put_profile("countries", "BAD", {"id": "BAD"}, region="europe")
        result = store.lint_profiles("countries")
        assert "countries/DEU" in result["ok"]
        assert "countries/BAD" in result["issues"]

    def test_no_schema_means_no_issues(self, store, profiles_dir):
        store.put_profile("stocks", "AAPL",
                          {"id": "AAPL", "name": "Apple"},
                          region="north_america")
        result = store.lint_profiles("stocks", "AAPL")
        assert "stocks/AAPL" in result["ok"]


# ── _lint_one internals ──────────────────────────


class TestLintOne:
    def test_type_mismatch_detected(self, store):
        schema = {
            "required": [],
            "properties": {
                "trade": {"top_exports": "exports"},
            },
        }
        issues = store._lint_one("countries", "X",
                                 {"trade": "not_a_dict"}, schema)
        assert any("trade" in i for i in issues)

    def test_array_type_mismatch(self, store):
        schema = {
            "required": [],
            "properties": {
                "tags": "Array of values",
            },
        }
        issues = store._lint_one("countries", "X",
                                 {"tags": "not_an_array"}, schema)
        assert any("tags" in i for i in issues)


# ── search_profiles ──────────────────────────────


class TestSearchProfiles:
    def test_search_by_string_field(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany", "currency": "EUR"},
                          region="europe")
        result = store.search_profiles("countries", "currency", "EUR")
        assert any(p.get("_id_str") == "DEU" or p.get("id") == "DEU" for p in result)

    def test_search_by_list_membership(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany",
                           "tags": ["EU", "G7", "NATO"]},
                          region="europe")
        result = store.search_profiles("countries", "tags", "EU")
        assert len(result) >= 1

    def test_search_no_match(self, store, profiles_dir):
        store.put_profile("countries", "DEU",
                          {"id": "DEU", "name": "Germany", "currency": "EUR"},
                          region="europe")
        result = store.search_profiles("countries", "currency", "USD")
        assert len(result) == 0


# ── VALID_KINDS ──────────────────────────────────


class TestValidKinds:
    def test_all_expected_kinds_present(self, store):
        expected = {"countries", "stocks", "etfs", "crypto", "indices",
                    "sources", "commodities", "crops", "materials",
                    "products", "companies", "regions"}
        assert store.VALID_KINDS == expected

    def test_blocked_agg_stages(self, store):
        for stage in ("$out", "$merge", "$unionWith"):
            assert stage in store._BLOCKED_STAGES


# ── User context helpers ────────────────────────


class TestGetUserId:
    def test_returns_empty_when_no_headers(self, store):
        uid = store._get_user_id()
        assert isinstance(uid, str)

    def test_env_fallback(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "user-from-env")
        uid = store._get_user_id()
        assert uid == "user-from-env"

    def test_header_takes_priority(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "env-user")
        fake_headers = {"x-user-id": "header-user"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        uid = store._get_user_id()
        assert uid == "header-user"


class TestGetUserKey:
    def test_returns_empty_without_headers(self, store):
        key = store._get_user_key("x-broker-key")
        assert key == ""

    def test_reads_header(self, store, monkeypatch):
        fake_headers = {"x-broker-key": "my-secret-key"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        key = store._get_user_key("x-broker-key")
        assert key == "my-secret-key"


# ── Risk gate ───────────────────────────────────


class TestRiskGate:
    def test_blocks_without_user(self, store, monkeypatch):
        monkeypatch.delenv("LIBRECHAT_USER_ID", raising=False)
        result = store._risk_check("buy", {"symbol": "AAPL"})
        assert result is not None
        assert "user not identified" in result["error"]

    def test_dry_run_blocks_by_default(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "test-user")
        result = store._risk_check("buy", {"symbol": "AAPL"})
        assert result is not None
        assert result["blocked"] == "dry_run"

    def test_passes_when_confirmed(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "test-user")
        store._user_action_counts.clear()
        result = store._risk_check("buy", {"symbol": "AAPL"}, dry_run=False)
        assert result is None

    def test_daily_limit_enforced(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "limit-user")
        store._user_action_counts["limit-user"] = store._DAILY_ACTION_LIMIT_DEFAULT
        result = store._risk_check("buy", {"symbol": "AAPL"}, dry_run=False)
        assert result is not None
        assert "daily action limit" in result["error"]
        store._user_action_counts.clear()

    def test_live_trading_header_overrides_dry_run(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "live-user")
        store._user_action_counts.clear()
        fake_headers = {"x-user-id": "live-user", "x-risk-live-trading": "yes"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        result = store._risk_check("buy", {"symbol": "AAPL"}, dry_run=True)
        assert result is None
        store._user_action_counts.clear()

    def test_custom_daily_limit_from_header(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "custom-limit")
        fake_headers = {"x-user-id": "custom-limit", "x-risk-daily-limit": "3"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        store._user_action_counts["custom-limit"] = 3
        result = store._risk_check("buy", {"symbol": "AAPL"}, dry_run=False)
        assert result is not None
        assert "daily action limit (3)" in result["error"]
        store._user_action_counts.clear()

    def test_risk_status_tool(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "status-user")
        store._user_action_counts["status-user"] = 5
        result = store.risk_status()
        assert result["actions_today"] == 5
        assert result["daily_limit"] == store._DAILY_ACTION_LIMIT_DEFAULT
        assert result["remaining"] == store._DAILY_ACTION_LIMIT_DEFAULT - 5
        assert result["live_trading"] is False
        assert result["broker_key_set"] is False
        store._user_action_counts.clear()

    def test_risk_status_with_broker(self, store, monkeypatch):
        fake_headers = {
            "x-user-id": "broker-user",
            "x-broker-name": "alpaca",
            "x-broker-key": "PKTEST123",
            "x-risk-live-trading": "yes",
            "x-risk-daily-limit": "10",
        }
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        store._user_action_counts["broker-user"] = 2
        result = store.risk_status()
        assert result["broker"] == "alpaca"
        assert result["broker_key_set"] is True
        assert result["live_trading"] is True
        assert result["daily_limit"] == 10
        assert result["actions_today"] == 2
        assert result["remaining"] == 8
        store._user_action_counts.clear()


# ── Seed profiles ───────────────────────────────


class TestSeedProfiles:
    def test_seeds_from_disk(self, store, profiles_dir):
        # Write seed profiles
        (profiles_dir / "europe" / "countries" / "DEU.json").write_text(
            json.dumps({"id": "DEU", "name": "Germany"})
        )
        (profiles_dir / "north_america" / "countries" / "USA.json").write_text(
            json.dumps({"id": "USA", "name": "United States"})
        )
        result = store.seed_profiles(str(profiles_dir))
        assert result["countries"]["seeded"] == 2
        # Verify they're queryable
        prof = store.get_profile("countries", "DEU")
        assert prof["name"] == "Germany"

    def test_no_overwrite_on_reseed(self, store, profiles_dir):
        (profiles_dir / "europe" / "countries" / "DEU.json").write_text(
            json.dumps({"id": "DEU", "name": "Germany"})
        )
        store.seed_profiles(str(profiles_dir))
        # Modify the profile via put_profile (user edit)
        store.put_profile("countries", "DEU", {"capital": "Berlin"})
        # Re-seed — should NOT overwrite user edit
        result = store.seed_profiles(str(profiles_dir))
        assert result["countries"]["skipped"] == 1
        assert result["countries"]["seeded"] == 0
        prof = store.get_profile("countries", "DEU")
        assert prof["capital"] == "Berlin"

    def test_clear_reinit(self, store, profiles_dir):
        (profiles_dir / "europe" / "countries" / "DEU.json").write_text(
            json.dumps({"id": "DEU", "name": "Germany"})
        )
        store.seed_profiles(str(profiles_dir))
        store.put_profile("countries", "FRA", {"id": "FRA", "name": "France"},
                          region="europe")
        # Clear + reseed: user data (FRA) is lost, seed data (DEU) reloaded
        result = store.seed_profiles(str(profiles_dir), clear=True)
        assert result["countries"]["seeded"] == 1
        assert store.get_profile("countries", "FRA").get("error")  # gone
        assert store.get_profile("countries", "DEU")["name"] == "Germany"

    def test_skips_underscore_and_schema(self, store, profiles_dir):
        schemas = profiles_dir / "SCHEMAS" / "countries"
        schemas.mkdir(parents=True, exist_ok=True)
        (schemas / "FAKE.json").write_text(json.dumps({"id": "FAKE"}))
        (profiles_dir / "europe" / "countries" / "_template.json").write_text(
            json.dumps({"id": "_template"})
        )
        result = store.seed_profiles(str(profiles_dir))
        assert result.get("countries", {}).get("seeded", 0) == 0


# ── Notes tools ─────────────────────────────────


class TestNoteKinds:
    @pytest.fixture(autouse=True)
    def setup_memory(self, store, monkeypatch):
        self.col = _FakeCollection()
        monkeypatch.setattr(store, "_notes_col", lambda: self.col)
        fake_headers = {"x-user-id": "note-user"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)

    def test_save_note_with_kind(self, store):
        r = store.save_note("My Plan", "trade AAPL", kind="plan")
        assert r["status"] == "ok"
        notes = store.get_notes(kind="plan")
        assert len(notes) == 1
        assert notes[0]["kind"] == "plan"

    def test_notes_filter_by_kind(self, store):
        store.save_note("A", "content", kind="note")
        store.save_note("B", "content", kind="plan")
        store.save_note("C", "content", kind="watchlist")
        assert len(store.get_notes(kind="plan")) == 1
        assert len(store.get_notes()) == 3


# ── Shared research notes ────────────────────────


class TestResearchTools:
    @pytest.fixture(autouse=True)
    def setup_research(self, store, monkeypatch):
        self.col = _FakeCollection()
        monkeypatch.setattr(store, "_shared_notes_col", lambda: self.col)

    def test_save_research_creates(self, store):
        r = store.save_research("Oil Market Brief", "Brent up 3%")
        assert r["status"] == "created"
        assert r["title"] == "Oil Market Brief"

    def test_save_research_overwrites(self, store):
        store.save_research("Weekly Macro", "v1")
        r = store.save_research("Weekly Macro", "v2")
        assert r["status"] == "updated"
        notes = store.get_research(title="Weekly Macro")
        assert len(notes) == 1
        assert notes[0]["content"] == "v2"

    def test_save_research_custom_kind(self, store):
        store.save_research("Alert", "high vol", kind="alert")
        notes = store.get_research(kind="alert")
        assert len(notes) == 1
        assert notes[0]["kind"] == "alert"

    def test_get_research_all(self, store):
        store.save_research("A", "1")
        store.save_research("B", "2")
        notes = store.get_research()
        assert len(notes) == 2

    def test_get_research_by_tag(self, store):
        store.save_research("A", "1", tags=["macro"])
        store.save_research("B", "2", tags=["sector"])
        notes = store.get_research(tag="macro")
        assert len(notes) == 1

    def test_update_research(self, store):
        store.save_research("Edit Me", "original")
        r = store.update_research("Edit Me", content="revised")
        assert r["status"] == "updated"
        notes = store.get_research(title="Edit Me")
        assert notes[0]["content"] == "revised"

    def test_update_research_not_found(self, store):
        r = store.update_research("Ghost")
        assert "error" in r

    def test_delete_research(self, store):
        store.save_research("Delete Me", "bye")
        r = store.delete_research("Delete Me")
        assert r["status"] == "deleted"
        assert len(store.get_research(title="Delete Me")) == 0

    def test_delete_research_not_found(self, store):
        r = store.delete_research("nonexistent")
        assert "error" in r

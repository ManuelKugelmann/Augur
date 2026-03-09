"""Integration tests for the signals store against a real MongoDB instance.

Requires MONGO_URI or MONGO_URI_SIGNALS pointing to a live database.
Uses a dedicated 'test_signals' database and cleans up after itself.
Marked with pytest.mark.integration to exclude from normal CI.

Note: store functions are synchronous (not async), so we call them directly.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

MONGO_URI = os.environ.get("MONGO_URI_SIGNALS", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not MONGO_URI, reason="MONGO_URI_SIGNALS not set"),
]


def _check_mongo_connection():
    """Verify MongoDB is reachable; skip tests if not (e.g. IP not allowlisted)."""
    try:
        import pymongo
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        client.close()
    except Exception as exc:
        pytest.skip(f"MongoDB not reachable: {exc}")


class TestStoreLive:
    """Test signals store profile + snapshot tools against real MongoDB."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo_connection()

        # Point store at temp profiles dir and real MongoDB
        os.environ["PROFILES_DIR"] = str(tmp_path / "profiles")
        os.environ.setdefault("MONGO_URI_SIGNALS", MONGO_URI)

        # Create a minimal profile structure
        p = tmp_path / "profiles" / "europe" / "countries"
        p.mkdir(parents=True)
        (p / "DEU.json").write_text(
            '{"id":"DEU","name":"Germany","kind":"countries",'
            '"region":"europe","tags":["eu","g7"]}'
        )

        # Ensure real pymongo is loaded (conftest.py may have mocked it)
        if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
            del sys.modules["pymongo"]
            import pymongo  # noqa: F401

        # Force-reimport the store module fresh
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "store"))
        if "server" in sys.modules:
            importlib.reload(sys.modules["server"])

        import server
        server._client = None
        server._cols_ready = set()
        server.PROFILES = Path(os.environ["PROFILES_DIR"])
        self.s = server

        # Seed disk profiles into MongoDB so get/list/find work
        server.seed_profiles(str(tmp_path / "profiles"), clear=True)

        yield

        # Cleanup: drop test collections
        try:
            db = server._db()
            for name in db.list_collection_names():
                if (name.startswith("snap_") or name.startswith("arch_")
                        or name.startswith("profiles_") or name == "events"):
                    db.drop_collection(name)
        except Exception:
            pass
        server._client = None
        server._cols_ready = set()

    # ── Profile tools ────────────────────────────────

    def test_get_profile(self):
        result = self.s.get_profile(kind="countries", id="DEU")
        assert result["id"] == "DEU"
        assert result["name"] == "Germany"

    def test_put_and_get_profile(self):
        self.s.put_profile(
            kind="countries", id="FRA", region="europe",
            data={"name": "France", "tags": ["eu", "g7"]})
        result = self.s.get_profile(kind="countries", id="FRA")
        assert result["name"] == "France"

    def test_list_profiles(self):
        result = self.s.list_profiles(kind="countries", region="europe")
        assert any(p["id"] == "DEU" for p in result)

    def test_find_profile(self):
        result = self.s.find_profile(query="Germany")
        assert any(p["id"] == "DEU" for p in result)

    # ── Snapshot tools ───────────────────────────────

    def test_snapshot_and_history(self):
        result = self.s.snapshot(
            kind="countries", entity="DEU", type="gdp",
            data={"value": 4.2, "unit": "trillion_usd"},
            region="europe")
        assert "inserted" in result or "id" in str(result).lower()

        hist = self.s.history(kind="countries", entity="DEU", type="gdp")
        assert isinstance(hist, list)
        assert len(hist) >= 1

    def test_trend(self):
        for val in [4.0, 4.1, 4.2]:
            self.s.snapshot(
                kind="countries", entity="DEU", type="gdp_trend_test",
                data={"value": val}, region="europe")
        result = self.s.trend(
            kind="countries", entity="DEU",
            type="gdp_trend_test", field="value", periods=3)
        assert isinstance(result, (dict, list))

    def test_event_and_recent(self):
        result = self.s.event(
            subtype="test_event", summary="Integration test event",
            data={"detail": "testing"}, region="europe")
        assert "inserted" in result or "id" in str(result).lower()

        events = self.s.recent_events(subtype="test_event")
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_archive_snapshot_and_history(self):
        result = self.s.archive_snapshot(
            kind="countries", entity="DEU", type="annual_gdp",
            data={"value": 4.0, "year": 2023}, region="europe")
        assert "inserted" in result or "id" in str(result).lower()

        hist = self.s.archive_history(
            kind="countries", entity="DEU", type="annual_gdp")
        assert isinstance(hist, list)

    def test_aggregate(self):
        self.s.snapshot(
            kind="countries", entity="DEU", type="agg_test",
            data={"value": 1}, region="europe")
        result = self.s.aggregate(
            kind="countries",
            pipeline=[{"$limit": 5}])
        assert isinstance(result, list)

    # ── Nearby (geo) ─────────────────────────────────

    def test_nearby(self):
        self.s.snapshot(
            kind="countries", entity="DEU", type="geo_test",
            data={"value": 1}, region="europe",
            lon=11.58, lat=48.14)
        result = self.s.nearby(
            kind="countries", lon=11.58, lat=48.14, max_km=100)
        assert isinstance(result, list)

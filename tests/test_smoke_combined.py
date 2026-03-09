"""Smoke test — combined trading server starts, mounts all namespaces, and
store tools work against a real MongoDB Atlas instance.

Requires MONGO_URI_SIGNALS in environment (GitHub secret).
Optionally checks MONGO_URI_LIBRECHAT (LibreChat database) connectivity.
Marked with pytest.mark.integration so it's excluded from normal CI.
"""
import importlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

MONGO_URI = os.environ.get("MONGO_URI_SIGNALS", "")
LIBRECHAT_MONGO_URI = os.environ.get("MONGO_URI_LIBRECHAT", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not MONGO_URI, reason="MONGO_URI_SIGNALS not set"),
]

skip_no_librechat_mongo = pytest.mark.skipif(
    not LIBRECHAT_MONGO_URI, reason="MONGO_URI_LIBRECHAT not set"
)

# Namespaces that combined_server.py mounts
EXPECTED_NAMESPACES = {
    "store", "weather", "disaster", "econ", "agri", "conflict",
    "commodity", "health", "politics", "transport", "water",
    "humanitarian", "infra",
}


def _ensure_real_pymongo():
    """Unmock pymongo if conftest.py mocked it."""
    if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
        del sys.modules["pymongo"]
    import pymongo  # noqa: F401
    return pymongo


def _check_mongo_connection(uri):
    """Verify MongoDB is reachable; skip tests if not (e.g. IP not allowlisted)."""
    if not uri:
        return
    try:
        pymongo = _ensure_real_pymongo()
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        client.close()
    except Exception as exc:
        pytest.skip(f"MongoDB not reachable: {exc}")


def _fresh_import_combined(tmp_path):
    """Import combined_server.py with real pymongo, return the root mcp."""
    # Point at a temp profiles dir so file-based tools don't fail
    profiles = tmp_path / "profiles" / "global" / "countries"
    profiles.mkdir(parents=True)
    (profiles / "TST.json").write_text(
        '{"id":"TST","name":"Testland","kind":"countries","region":"global","tags":["test"]}'
    )
    os.environ["PROFILES_DIR"] = str(tmp_path / "profiles")
    os.environ.setdefault("MONGO_URI_SIGNALS", MONGO_URI)

    _ensure_real_pymongo()

    # Add server dirs to path
    servers_dir = str(Path(__file__).resolve().parent.parent / "src" / "servers")
    store_dir = str(Path(__file__).resolve().parent.parent / "src" / "store")
    for d in (servers_dir, store_dir):
        if d not in sys.path:
            sys.path.insert(0, d)

    # Force-reimport to pick up real MongoDB
    for mod_name in list(sys.modules):
        if mod_name in ("server", "combined_server") or mod_name.endswith("_server"):
            del sys.modules[mod_name]

    import combined_server
    return combined_server.mcp


def _cleanup_signals_db():
    """Drop all test collections from the signals DB."""
    try:
        import server
        db = server._db()
        for name in db.list_collection_names():
            if (name.startswith("snap_") or name.startswith("arch_")
                    or name in ("events", "user_notes", "shared_notes")):
                db.drop_collection(name)
        server._client = None
        server._cols_ready = set()
    except Exception:
        pass


class TestCombinedSmoke:
    """Verify the combined server imports, mounts all namespaces, and
    store tools actually round-trip through MongoDB Atlas."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo_connection(MONGO_URI)
        self.mcp = _fresh_import_combined(tmp_path)
        self.tmp = tmp_path
        yield
        _cleanup_signals_db()

    # ── Import / mount checks ─────────────────────

    @pytest.mark.asyncio
    async def test_all_namespaces_mounted(self):
        """Combined server must mount all 13 namespaces."""
        tools = await self.mcp.list_tools()
        tool_names = {t.name for t in tools}
        for ns in EXPECTED_NAMESPACES:
            matching = [t for t in tool_names if t.startswith(f"{ns}_")]
            assert matching, f"No tools found for namespace '{ns}' — mount failed"

    @pytest.mark.asyncio
    async def test_tool_count_minimum(self):
        """Combined server should expose 50+ tools total."""
        tools = await self.mcp.list_tools()
        assert len(tools) >= 50, f"Only {len(tools)} tools found, expected 50+"

    # ── Store tools against real Atlas ────────────

    def test_store_put_get_profile(self):
        """Write a profile and read it back (file-based, no MongoDB)."""
        import server
        server.PROFILES = Path(os.environ["PROFILES_DIR"])

        server.put_profile(
            kind="countries", id="SMK", region="global",
            data={"name": "Smokeland", "tags": ["test"]})
        result = server.get_profile(kind="countries", id="SMK")
        assert result["name"] == "Smokeland"

    def test_store_snapshot_roundtrip(self):
        """Write a snapshot to Atlas and read it back."""
        import server
        server.PROFILES = Path(os.environ["PROFILES_DIR"])

        result = server.snapshot(
            kind="countries", entity="TST", type="smoke_test",
            data={"value": 42, "source": "ci_smoke"}, region="global")
        assert "inserted" in str(result).lower() or "id" in str(result).lower()

        hist = server.history(kind="countries", entity="TST", type="smoke_test")
        assert isinstance(hist, list)
        assert len(hist) >= 1
        assert hist[0]["data"]["value"] == 42

    def test_store_event_roundtrip(self):
        """Log an event to Atlas and query it back."""
        import server
        result = server.event(
            subtype="ci_smoke", summary="Smoke test event",
            data={"source": "github_ci"}, region="global")
        assert "inserted" in str(result).lower() or "id" in str(result).lower()

        events = server.recent_events(subtype="ci_smoke")
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_store_aggregate(self):
        """Run a basic aggregation pipeline against Atlas."""
        import server
        server.snapshot(
            kind="countries", entity="TST", type="agg_smoke",
            data={"value": 1}, region="global")
        result = server.aggregate(
            kind="countries", pipeline=[{"$limit": 5}])
        assert isinstance(result, list)

    # ── MongoDB connection health ─────────────────

    def test_atlas_connection_healthy(self):
        """Verify Atlas M0 responds to ping."""
        import server
        db = server._db()
        result = db.command("ping")
        assert result.get("ok") == 1.0

    # ── Compact (cron daily task) ─────────────────

    def test_compact_nothing_to_compact(self):
        """compact() returns 'nothing_to_compact' when no old data exists."""
        import server
        server.snapshot(
            kind="countries", entity="TST", type="compact_test",
            data={"value": 1}, region="global")
        result = server.compact(
            kind="countries", entity="TST", type="compact_test",
            older_than_days=90)
        assert result["status"] == "nothing_to_compact"

    def test_compact_with_old_data(self):
        """compact() archives old snapshots and returns bucket count."""
        import server
        col = server._snap_col("countries")
        old_ts = datetime.now(timezone.utc) - timedelta(days=120)
        for i in range(3):
            doc = {
                "ts": old_ts + timedelta(days=i),
                "meta": {"entity": "TST", "kind": "countries",
                         "type": "compact_old_test", "region": "global",
                         "source": "ci"},
                "data": {"value": float(i), "label": "test"},
            }
            col.insert_one(doc)

        result = server.compact(
            kind="countries", entity="TST", type="compact_old_test",
            older_than_days=90, bucket="month")
        assert result["status"] == "ok"
        assert result["buckets_created"] >= 1
        # Time-series delete_many may report deleted_count=0 on some Atlas
        # versions even when docs were deleted, so verify via archive instead
        arch = server.archive_history(
            kind="countries", entity="TST", type="compact_old_test")
        assert len(arch) >= 1

    # ── Cron entrypoint simulation ────────────────

    def test_cron_compact_python_block_runs(self):
        """The inline Python block from 'ta cron' compact logic runs without errors."""
        import server
        server.snapshot(
            kind="countries", entity="TST", type="cron_block_test",
            data={"value": 99}, region="global")

        repo_root = Path(__file__).resolve().parent.parent
        script = f"""\
import os, sys
sys.path.insert(0, {str(repo_root / "src" / "store")!r})
sys.path.insert(0, {str(repo_root / "src" / "servers")!r})
os.environ["MONGO_URI_SIGNALS"] = {MONGO_URI!r}
os.environ["PROFILES_DIR"] = {os.environ["PROFILES_DIR"]!r}
from server import compact, _snap_col, VALID_KINDS
for kind in VALID_KINDS:
    try:
        col = _snap_col(kind)
    except Exception as e:
        print(f"skip {{kind}}: {{e}}")
        continue
    pipeline = [{{"$group": {{"_id": {{"entity": "$meta.entity", "type": "$meta.type"}}}}}}]
    try:
        combos = list(col.aggregate(pipeline))
    except Exception as e:
        print(f"skip {{kind}}: {{e}}")
        continue
    for c in combos:
        eid = c["_id"]["entity"]
        etype = c["_id"]["type"]
        result = compact(kind, eid, etype, older_than_days=90, bucket="month")
        print(f"{{kind}}/{{eid}}/{{etype}}: {{result.get('status', 'error')}}")
print("CRON_COMPACT_OK")
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert "CRON_COMPACT_OK" in proc.stdout


# ── Per-user notes (T4 cron-planner / L5 live-chat) ─


class TestPerUserNotes:
    """Test per-user note CRUD against real Atlas — simulates T4/L5 agent
    workflows (plans, watchlists, journal entries scoped by user)."""

    CI_USER = "ci-test-user-001"

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo_connection(MONGO_URI)
        _fresh_import_combined(tmp_path)
        yield
        _cleanup_signals_db()

    def _with_user(self, user_id=None):
        """Patch _get_user_id to return a test user."""
        uid = user_id or self.CI_USER
        import server
        return patch.object(server, "_get_user_id", return_value=uid)

    def test_save_and_get_note(self):
        import server
        with self._with_user():
            result = server.save_note(
                title="CI smoke note", content="Testing notes against Atlas",
                tags=["ci", "smoke"], kind="note")
            assert result["status"] == "ok"
            note_id = result["id"]

            notes = server.get_notes()
            assert isinstance(notes, list)
            assert any(n["title"] == "CI smoke note" for n in notes)

            # Cleanup
            server.delete_note(note_id)

    def test_save_plan_and_filter_by_kind(self):
        """T4 cron-planner saves plans; filter by kind='plan'."""
        import server
        with self._with_user():
            r1 = server.save_note(
                title="Buy AAPL dip", content="Watch for entry below $170",
                tags=["trade"], kind="plan")
            r2 = server.save_note(
                title="Daily log", content="Markets flat today",
                tags=["daily"], kind="journal")

            plans = server.get_notes(kind="plan")
            assert any(n["title"] == "Buy AAPL dip" for n in plans)
            assert not any(n["title"] == "Daily log" for n in plans)

            journals = server.get_notes(kind="journal")
            assert any(n["title"] == "Daily log" for n in journals)

            server.delete_note(r1["id"])
            server.delete_note(r2["id"])

    def test_update_note(self):
        import server
        with self._with_user():
            r = server.save_note(
                title="Watchlist v1", content="AAPL, NVDA",
                tags=["watch"], kind="watchlist")
            note_id = r["id"]

            server.update_note(note_id, content="AAPL, NVDA, MSFT",
                               tags=["watch", "updated"])
            notes = server.get_notes(kind="watchlist")
            updated = next(n for n in notes if n["title"] == "Watchlist v1")
            assert "MSFT" in updated["content"]
            assert "updated" in updated["tags"]

            server.delete_note(note_id)

    def test_user_isolation(self):
        """User A's notes are invisible to user B."""
        import server
        with self._with_user("user-alice"):
            ra = server.save_note(title="Alice secret", content="classified",
                                  kind="note")
        with self._with_user("user-bob"):
            bob_notes = server.get_notes()
            assert not any(n["title"] == "Alice secret" for n in bob_notes)

        # Cleanup as alice
        with self._with_user("user-alice"):
            server.delete_note(ra["id"])

    def test_note_without_user_returns_error(self):
        """Notes require user identification."""
        import server
        with patch.object(server, "_get_user_id", return_value=""):
            result = server.save_note(title="fail", content="no user")
            assert "error" in result


# ── Shared research (cross-agent, no user tracking) ─


class TestSharedResearch:
    """Test shared research CRUD against real Atlas — simulates L2/L3
    analyst agents writing research accessible to all users/agents."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo_connection(MONGO_URI)
        _fresh_import_combined(tmp_path)
        yield
        _cleanup_signals_db()

    def test_save_and_get_research(self):
        import server
        result = server.save_research(
            title="CI smoke research", content="Testing shared notes against Atlas",
            tags=["ci", "smoke"], kind="research")
        assert result["status"] == "created"

        notes = server.get_research(title="CI smoke research")
        assert len(notes) == 1
        assert notes[0]["content"] == "Testing shared notes against Atlas"

        server.delete_research("CI smoke research")

    def test_research_upsert(self):
        """save_research with same title overwrites (upsert)."""
        import server
        server.save_research(title="Upsert test", content="v1", tags=["ci"])
        r2 = server.save_research(title="Upsert test", content="v2", tags=["ci"])
        assert r2["status"] == "updated"

        notes = server.get_research(title="Upsert test")
        assert len(notes) == 1
        assert notes[0]["content"] == "v2"

        server.delete_research("Upsert test")

    def test_research_kinds(self):
        """Research supports kind: research, report, briefing, alert."""
        import server
        for kind in ("research", "report", "briefing", "alert"):
            server.save_research(
                title=f"CI {kind}", content=f"Testing {kind}",
                kind=kind, tags=["ci"])

        reports = server.get_research(kind="report")
        assert any(n["title"] == "CI report" for n in reports)

        alerts = server.get_research(kind="alert")
        assert any(n["title"] == "CI alert" for n in alerts)

        for kind in ("research", "report", "briefing", "alert"):
            server.delete_research(f"CI {kind}")

    def test_update_research(self):
        import server
        server.save_research(title="Update target", content="original",
                             tags=["ci"])
        result = server.update_research("Update target", content="modified",
                                        tags=["ci", "updated"])
        assert result["status"] == "updated"

        notes = server.get_research(title="Update target")
        assert notes[0]["content"] == "modified"
        assert "updated" in notes[0]["tags"]

        server.delete_research("Update target")

    def test_research_shared_across_users(self):
        """Research is shared — no user scoping, accessible to all agents."""
        import server
        server.save_research(
            title="Shared finding", content="Cross-agent data",
            tags=["shared"])

        # Research doesn't use _get_user_id — all reads return all data
        notes = server.get_research(title="Shared finding")
        assert len(notes) == 1

        server.delete_research("Shared finding")


# ── LibreChat MongoDB connectivity ───────────────


@skip_no_librechat_mongo
class TestLibreChatMongo:
    """Verify the LibreChat MongoDB Atlas database is reachable."""

    def test_librechat_atlas_ping(self):
        """LibreChat's MONGO_URI_LIBRECHAT responds to ping."""
        _check_mongo_connection(LIBRECHAT_MONGO_URI)
        _ensure_real_pymongo()
        from pymongo import MongoClient
        client = MongoClient(LIBRECHAT_MONGO_URI, serverSelectionTimeoutMS=5000)
        try:
            result = client.admin.command("ping")
            assert result.get("ok") == 1.0
        finally:
            client.close()

    def test_librechat_database_exists(self):
        """LibreChat database is accessible (may be empty on fresh setup)."""
        _check_mongo_connection(LIBRECHAT_MONGO_URI)
        _ensure_real_pymongo()
        from pymongo import MongoClient
        client = MongoClient(LIBRECHAT_MONGO_URI, serverSelectionTimeoutMS=5000)
        try:
            db_names = client.list_database_names()
            assert isinstance(db_names, list)
            assert len(db_names) >= 1  # At least admin exists
        finally:
            client.close()

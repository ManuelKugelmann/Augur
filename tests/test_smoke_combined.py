"""Smoke test — combined trading server starts, mounts all namespaces, and
store tools work against a real MongoDB Atlas instance.

Requires MONGO_URI_SIGNALS in environment (GitHub secret).
Optionally checks MONGO_URI (LibreChat database) connectivity.
Marked with pytest.mark.integration so it's excluded from normal CI.
"""
import importlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

MONGO_URI = os.environ.get("MONGO_URI_SIGNALS", "")
LIBRECHAT_MONGO_URI = os.environ.get("MONGO_URI", "")
skip_no_mongo = pytest.mark.skipif(not MONGO_URI, reason="MONGO_URI_SIGNALS not set")
skip_no_librechat_mongo = pytest.mark.skipif(
    not LIBRECHAT_MONGO_URI, reason="MONGO_URI (LibreChat) not set"
)

# Namespaces that combined_server.py mounts
EXPECTED_NAMESPACES = {
    "store", "weather", "disaster", "econ", "agri", "conflict",
    "commodity", "health", "politics", "transport", "water",
    "humanitarian", "infra",
}


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

    # Ensure real pymongo is loaded (conftest mocks it)
    if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
        del sys.modules["pymongo"]
        import pymongo  # noqa: F401

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


@skip_no_mongo
class TestCombinedSmoke:
    """Verify the combined server imports, mounts all namespaces, and
    store tools actually round-trip through MongoDB Atlas."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.mcp = _fresh_import_combined(tmp_path)
        self.tmp = tmp_path

        yield

        # Cleanup: drop test collections from signals DB
        try:
            import server
            db = server._db()
            for name in db.list_collection_names():
                if name.startswith("snap_") or name.startswith("arch_") or name == "events":
                    db.drop_collection(name)
            server._client = None
            server._cols_ready = set()
        except Exception:
            pass

    # ── Import / mount checks ─────────────────────

    @pytest.mark.asyncio
    async def test_all_namespaces_mounted(self):
        """Combined server must mount all 13 namespaces."""
        tools = await self.mcp.list_tools()
        tool_names = {t.name for t in tools}
        # Each namespace contributes at least one tool prefixed with its name
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
        # Insert a recent snapshot (not older than 90 days)
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
        from pymongo import MongoClient
        # Insert backdated snapshots directly into MongoDB
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
        assert result["snapshots_deleted"] >= 3

    # ── Cron entrypoint simulation ────────────────

    def test_cron_compact_python_block_runs(self):
        """The inline Python block from 'ta cron' compact logic runs without errors."""
        import server
        # Insert a snapshot so the compact loop has something to iterate
        server.snapshot(
            kind="countries", entity="TST", type="cron_block_test",
            data={"value": 99}, region="global")

        # Run the same Python logic that ta cron executes (minus dotenv)
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


# ── LibreChat MongoDB connectivity ───────────────


@skip_no_librechat_mongo
class TestLibreChatMongo:
    """Verify the LibreChat MongoDB Atlas database is reachable."""

    def test_librechat_atlas_ping(self):
        """LibreChat's MONGO_URI responds to ping."""
        # Ensure real pymongo
        if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
            del sys.modules["pymongo"]
        from pymongo import MongoClient
        client = MongoClient(LIBRECHAT_MONGO_URI, serverSelectionTimeoutMS=5000)
        try:
            result = client.admin.command("ping")
            assert result.get("ok") == 1.0
        finally:
            client.close()

    def test_librechat_database_exists(self):
        """LibreChat database is accessible (may be empty on fresh setup)."""
        if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
            del sys.modules["pymongo"]
        from pymongo import MongoClient
        client = MongoClient(LIBRECHAT_MONGO_URI, serverSelectionTimeoutMS=5000)
        try:
            db_names = client.list_database_names()
            # Atlas always has admin; LibreChat DB may not exist yet on fresh setup
            assert isinstance(db_names, list)
            assert len(db_names) >= 1  # At least admin exists
        finally:
            client.close()

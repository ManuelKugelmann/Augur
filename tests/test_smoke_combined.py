"""Smoke test — combined trading server starts, mounts all namespaces, and
store tools work against a real MongoDB Atlas instance.

Requires MONGO_URI_SIGNALS in environment (GitHub secret).
Marked with pytest.mark.integration so it's excluded from normal CI.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

MONGO_URI = os.environ.get("MONGO_URI_SIGNALS", "")
skip_no_mongo = pytest.mark.skipif(not MONGO_URI, reason="MONGO_URI_SIGNALS not set")

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

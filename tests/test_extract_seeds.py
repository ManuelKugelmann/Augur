"""Tests for extract-seeds.py — profile extraction from MongoDB to seed files.

Tests the script's logic using mongomock (CI) or mocked pymongo (sandbox).
"""
import json
import os
import sys
import importlib

import pytest

# Add the script directory to path
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
sys.path.insert(0, SCRIPT_DIR)

# Import with hyphen-safe name
extract = importlib.import_module("extract-seeds")


# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def profiles_dir(tmp_path):
    """Provide a temporary profiles directory."""
    return tmp_path


@pytest.fixture
def mock_db():
    """Create a mock MongoDB database with test profile data."""
    try:
        import mongomock
        client = mongomock.MongoClient()
    except ImportError:
        from unittest.mock import MagicMock
        client = MagicMock()
        # Can't run DB-dependent tests without mongomock
        pytest.skip("mongomock not available")

    db = client["signals"]

    # Insert test profiles
    db["profiles_countries"].insert_many([
        {
            "_id_str": "USA",
            "kind": "countries",
            "region": "north_america",
            "id": "USA",
            "name": "United States",
            "iso2": "US",
            "tags": ["G7", "NATO"],
            "_seeded": "2026-01-01",
        },
        {
            "_id_str": "DEU",
            "kind": "countries",
            "region": "europe",
            "id": "DEU",
            "name": "Germany",
            "iso2": "DE",
            "tags": ["G7", "EU"],
            "_seeded": "2026-01-01",
        },
    ])

    db["profiles_stocks"].insert_many([
        {
            "_id_str": "AAPL",
            "kind": "stocks",
            "region": "north_america",
            "id": "AAPL",
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "_seeded": "2026-01-01",
        },
    ])

    return db


# ── Extraction tests ──────────────────────────────


class TestExtractProfiles:
    """Test the extract_profiles function."""

    def test_extracts_countries(self, mock_db, profiles_dir):
        results = extract.extract_profiles(mock_db, profiles_dir)
        assert "countries" in results
        assert results["countries"]["total"] == 2
        assert results["countries"]["written"] == 2

    def test_extracts_stocks(self, mock_db, profiles_dir):
        results = extract.extract_profiles(mock_db, profiles_dir)
        assert "stocks" in results
        assert results["stocks"]["total"] == 1

    def test_creates_correct_file_paths(self, mock_db, profiles_dir):
        extract.extract_profiles(mock_db, profiles_dir)
        assert (profiles_dir / "north_america" / "countries" / "USA.json").exists()
        assert (profiles_dir / "europe" / "countries" / "DEU.json").exists()
        assert (profiles_dir / "north_america" / "stocks" / "AAPL.json").exists()

    def test_json_format_sorted_keys(self, mock_db, profiles_dir):
        extract.extract_profiles(mock_db, profiles_dir)
        path = profiles_dir / "north_america" / "countries" / "USA.json"
        content = path.read_text()
        data = json.loads(content)
        # Keys should be sorted in the JSON file
        keys = list(data.keys())
        assert keys == sorted(keys)

    def test_json_format_indented(self, mock_db, profiles_dir):
        extract.extract_profiles(mock_db, profiles_dir)
        path = profiles_dir / "north_america" / "countries" / "USA.json"
        content = path.read_text()
        # Should be pretty-printed with 2-space indent
        assert "\n  " in content
        # Should end with newline
        assert content.endswith("\n")

    def test_strips_internal_fields(self, mock_db, profiles_dir):
        extract.extract_profiles(mock_db, profiles_dir)
        path = profiles_dir / "north_america" / "countries" / "USA.json"
        data = json.loads(path.read_text())
        assert "_id" not in data
        assert "_id_str" not in data
        assert "_seeded" not in data

    def test_preserves_data_fields(self, mock_db, profiles_dir):
        extract.extract_profiles(mock_db, profiles_dir)
        path = profiles_dir / "north_america" / "countries" / "USA.json"
        data = json.loads(path.read_text())
        assert data["id"] == "USA"
        assert data["name"] == "United States"
        assert data["iso2"] == "US"
        assert data["tags"] == ["G7", "NATO"]

    def test_skips_unchanged_files(self, mock_db, profiles_dir):
        # First extraction
        extract.extract_profiles(mock_db, profiles_dir)
        # Second extraction — nothing should change
        results = extract.extract_profiles(mock_db, profiles_dir)
        assert results["countries"]["written"] == 0
        assert results["countries"]["unchanged"] == 2

    def test_overwrites_changed_files(self, mock_db, profiles_dir):
        # First extraction
        extract.extract_profiles(mock_db, profiles_dir)
        # Modify file on disk
        path = profiles_dir / "north_america" / "countries" / "USA.json"
        path.write_text('{"stale": true}\n')
        # Second extraction — should overwrite
        results = extract.extract_profiles(mock_db, profiles_dir)
        assert results["countries"]["written"] == 1
        assert results["countries"]["unchanged"] == 1

    def test_dry_run_no_writes(self, mock_db, profiles_dir):
        results = extract.extract_profiles(mock_db, profiles_dir, dry_run=True)
        assert results["countries"]["written"] == 2
        # But no files should exist
        assert not (profiles_dir / "north_america" / "countries" / "USA.json").exists()

    def test_empty_collection_skipped(self, mock_db, profiles_dir):
        results = extract.extract_profiles(mock_db, profiles_dir)
        # Crypto collection was not populated
        assert "crypto" not in results

    def test_missing_region_defaults_global(self, mock_db, profiles_dir):
        mock_db["profiles_crypto"].insert_one({
            "_id_str": "BTC",
            "kind": "crypto",
            "id": "BTC",
            "name": "Bitcoin",
        })
        extract.extract_profiles(mock_db, profiles_dir)
        assert (profiles_dir / "global" / "crypto" / "BTC.json").exists()

    def test_skips_docs_without_id(self, mock_db, profiles_dir):
        mock_db["profiles_crypto"].insert_one({
            "kind": "crypto",
            "name": "Unknown",
        })
        results = extract.extract_profiles(mock_db, profiles_dir)
        # Should not crash, doc without _id_str is skipped
        if "crypto" in results:
            assert results["crypto"]["total"] <= 1


# ── STRIP_FIELDS tests ──────────────────────────


class TestStripFields:
    """Test that the correct fields are stripped."""

    def test_strip_fields_includes_id(self):
        assert "_id" in extract.STRIP_FIELDS

    def test_strip_fields_includes_id_str(self):
        assert "_id_str" in extract.STRIP_FIELDS

    def test_strip_fields_includes_seeded(self):
        assert "_seeded" in extract.STRIP_FIELDS


# ── VALID_KINDS consistency ──────────────────────


class TestConsistency:
    """Test that extract-seeds.py is consistent with server.py."""

    def test_valid_kinds_matches_server(self):
        """VALID_KINDS should match the server's VALID_KINDS (parsed from source)."""
        # Parse VALID_KINDS from server.py source to avoid import issues
        server_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "src", "store", "server.py",
        )
        import re
        source = open(server_path).read()
        # Extract the frozenset literal from the source
        match = re.search(r'VALID_KINDS\s*=\s*frozenset\(\{([^}]+)\}\)', source)
        assert match, "Could not find VALID_KINDS in server.py"
        kinds_str = match.group(1)
        # Parse quoted strings
        server_kinds = frozenset(re.findall(r'"([^"]+)"', kinds_str))
        assert extract.VALID_KINDS == server_kinds

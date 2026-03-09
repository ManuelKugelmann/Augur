"""Tests for bootstrap-data.py — profile data bootstrapping via LibreChat Agents API.

Tests the script's logic without requiring a running LibreChat instance.
"""

import json
import os
import sys
import tempfile

import pytest

# Add the script directory to path so we can import bootstrap-data
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "librechat-uberspace",
    "scripts",
)
sys.path.insert(0, SCRIPT_DIR)

# Import with hyphen in filename
import importlib

bootstrap = importlib.import_module("bootstrap-data")


# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def targets():
    """Load the real bootstrap-targets.json."""
    return bootstrap.load_targets(bootstrap.TARGETS_FILE)


@pytest.fixture
def profiles_dir(tmp_path):
    """Create a temporary profiles directory with some existing profiles."""
    # Create region/kind directories
    (tmp_path / "north_america" / "countries").mkdir(parents=True)
    (tmp_path / "europe" / "countries").mkdir(parents=True)
    (tmp_path / "north_america" / "stocks").mkdir(parents=True)
    (tmp_path / "global" / "etfs").mkdir(parents=True)
    (tmp_path / "global" / "sources").mkdir(parents=True)

    # Write some existing profiles
    (tmp_path / "north_america" / "countries" / "USA.json").write_text(
        json.dumps({"id": "USA", "name": "United States", "_placeholder": True})
    )
    (tmp_path / "europe" / "countries" / "DEU.json").write_text(
        json.dumps({"id": "DEU", "name": "Germany", "_placeholder": True})
    )
    (tmp_path / "north_america" / "stocks" / "AAPL.json").write_text(
        json.dumps({"id": "AAPL", "name": "Apple Inc.", "_placeholder": True})
    )
    (tmp_path / "global" / "etfs" / "VWO.json").write_text(
        json.dumps({"id": "VWO", "name": "Vanguard FTSE Emerging Markets", "_placeholder": True})
    )
    return tmp_path


# ── Target validation tests ──────────────────────


class TestTargets:
    """Test bootstrap-targets.json structure and data."""

    def test_targets_file_exists(self):
        assert os.path.exists(bootstrap.TARGETS_FILE)

    def test_targets_loads(self, targets):
        assert isinstance(targets, dict)
        assert len(targets) > 0

    def test_all_kinds_valid(self, targets):
        for kind in targets:
            assert kind in bootstrap.VALID_KINDS, f"Invalid kind in targets: {kind}"

    def test_all_target_entries_have_id_and_region(self, targets):
        for kind, entries in targets.items():
            for entry in entries:
                assert "id" in entry, f"Missing 'id' in {kind} target: {entry}"
                assert "region" in entry, f"Missing 'region' in {kind} target: {entry}"

    def test_target_ids_follow_conventions(self, targets):
        """IDs should match the naming conventions from CLAUDE.md."""
        uppercase_kinds = {"countries", "stocks", "etfs", "crypto", "indices"}
        lowercase_kinds = {"commodities", "crops", "materials", "products", "companies", "sources"}

        for kind, entries in targets.items():
            for entry in entries:
                eid = entry["id"]
                if kind in uppercase_kinds:
                    # These should be uppercase (or numeric for some stock tickers)
                    assert eid == eid.upper() or eid.isdigit() or "-" in eid, \
                        f"{kind}/{eid}: expected uppercase ID"
                elif kind in lowercase_kinds:
                    assert eid == eid.lower() or "-" in eid, \
                        f"{kind}/{eid}: expected lowercase slug ID"

    def test_valid_regions(self, targets):
        valid_regions = {
            "north_america", "latin_america", "europe", "mena",
            "sub_saharan_africa", "south_asia", "east_asia",
            "southeast_asia", "central_asia", "oceania",
            "arctic", "antarctic", "global",
        }
        for kind, entries in targets.items():
            for entry in entries:
                assert entry["region"] in valid_regions, \
                    f"Invalid region '{entry['region']}' for {kind}/{entry['id']}"

    def test_no_duplicate_ids_per_kind(self, targets):
        for kind, entries in targets.items():
            ids = [e["id"] for e in entries]
            dupes = [eid for eid in ids if ids.count(eid) > 1]
            assert len(dupes) == 0, f"Duplicate IDs in {kind}: {set(dupes)}"

    def test_minimum_targets_per_kind(self, targets):
        """Each kind should have at least 10 targets."""
        for kind, entries in targets.items():
            assert len(entries) >= 10, f"{kind} has only {len(entries)} targets, expected >= 10"

    def test_schema_required_covers_all_kinds(self):
        for kind in bootstrap.VALID_KINDS:
            assert kind in bootstrap.SCHEMA_REQUIRED, \
                f"Missing SCHEMA_REQUIRED entry for {kind}"

    def test_kind_instructions_covers_all_kinds(self):
        for kind in bootstrap.VALID_KINDS:
            assert kind in bootstrap.KIND_INSTRUCTIONS, \
                f"Missing KIND_INSTRUCTIONS entry for {kind}"


# ── Profile discovery tests ──────────────────────


class TestExistingProfiles:
    """Test the find_existing_profiles function."""

    def test_finds_existing_countries(self, profiles_dir):
        existing = bootstrap.find_existing_profiles(str(profiles_dir), "countries")
        assert "USA" in existing
        assert "DEU" in existing

    def test_finds_existing_stocks(self, profiles_dir):
        existing = bootstrap.find_existing_profiles(str(profiles_dir), "stocks")
        assert "AAPL" in existing

    def test_finds_existing_etfs(self, profiles_dir):
        existing = bootstrap.find_existing_profiles(str(profiles_dir), "etfs")
        assert "VWO" in existing

    def test_empty_for_missing_kind(self, profiles_dir):
        existing = bootstrap.find_existing_profiles(str(profiles_dir), "crypto")
        assert len(existing) == 0

    def test_skips_hidden_and_schema_dirs(self, profiles_dir):
        (profiles_dir / "SCHEMAS" / "countries").mkdir(parents=True)
        (profiles_dir / "SCHEMAS" / "countries" / "FAKE.json").write_text("{}")
        existing = bootstrap.find_existing_profiles(str(profiles_dir), "countries")
        assert "FAKE" not in existing

    def test_skips_underscore_files(self, profiles_dir):
        (profiles_dir / "north_america" / "countries" / "_template.json").write_text("{}")
        existing = bootstrap.find_existing_profiles(str(profiles_dir), "countries")
        assert "_template" not in existing


# ── Prompt generation tests ──────────────────────


class TestPromptGeneration:
    """Test the build_prompt function."""

    def test_prompt_contains_kind(self):
        targets = [{"id": "USA", "region": "north_america"}]
        prompt = bootstrap.build_prompt("countries", targets, set())
        assert "countries" in prompt

    def test_prompt_marks_new_entities(self):
        targets = [{"id": "CHN", "region": "east_asia"}]
        prompt = bootstrap.build_prompt("countries", targets, set())
        assert "CREATE" in prompt
        assert "CHN" in prompt

    def test_prompt_marks_enrichment(self):
        targets = [{"id": "USA", "region": "north_america"}]
        prompt = bootstrap.build_prompt("countries", targets, {"USA"})
        assert "ENRICH" in prompt
        assert "USA" in prompt

    def test_prompt_includes_both_new_and_enrich(self):
        targets = [
            {"id": "USA", "region": "north_america"},
            {"id": "CHN", "region": "east_asia"},
        ]
        prompt = bootstrap.build_prompt("countries", targets, {"USA"})
        assert "ENRICH" in prompt
        assert "CREATE" in prompt

    def test_prompt_includes_required_fields(self):
        targets = [{"id": "BTC", "region": "global"}]
        prompt = bootstrap.build_prompt("crypto", targets, set())
        for field in bootstrap.SCHEMA_REQUIRED["crypto"]:
            assert field in prompt

    def test_prompt_includes_kind_instructions(self):
        targets = [{"id": "crude_oil", "region": "global"}]
        prompt = bootstrap.build_prompt("commodities", targets, set())
        assert "eia" in prompt.lower() or "faostat" in prompt.lower()

    def test_prompt_includes_put_profile_instruction(self):
        targets = [{"id": "AAPL", "region": "north_america"}]
        prompt = bootstrap.build_prompt("stocks", targets, set())
        assert "store_put_profile" in prompt

    def test_prompt_discourages_placeholder(self):
        targets = [{"id": "AAPL", "region": "north_america"}]
        prompt = bootstrap.build_prompt("stocks", targets, set())
        # Prompt should instruct agent NOT to use placeholder flag
        assert "NOT" in prompt and "_placeholder" in prompt


# ── Batch splitting tests ────────────────────────


class TestBatching:
    """Test the batch_targets function."""

    def test_single_batch(self):
        targets = [{"id": f"T{i}"} for i in range(5)]
        batches = bootstrap.batch_targets(targets, 10)
        assert len(batches) == 1
        assert len(batches[0]) == 5

    def test_exact_split(self):
        targets = [{"id": f"T{i}"} for i in range(20)]
        batches = bootstrap.batch_targets(targets, 10)
        assert len(batches) == 2
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10

    def test_remainder_batch(self):
        targets = [{"id": f"T{i}"} for i in range(15)]
        batches = bootstrap.batch_targets(targets, 10)
        assert len(batches) == 2
        assert len(batches[0]) == 10
        assert len(batches[1]) == 5

    def test_empty_targets(self):
        batches = bootstrap.batch_targets([], 10)
        assert len(batches) == 0

    def test_batch_size_one(self):
        targets = [{"id": f"T{i}"} for i in range(3)]
        batches = bootstrap.batch_targets(targets, 1)
        assert len(batches) == 3


# ── SSE parsing tests ────────────────────────────


class TestSSEParsing:
    """Test SSE response handling (via mocked httpx)."""

    def test_send_bootstrap_handles_timeout(self):
        """Verify timeout produces proper error result."""
        # Create a client that will fail (no server running)
        client = bootstrap.httpx.Client(base_url="http://127.0.0.1:1", timeout=0.1)
        result = bootstrap.send_bootstrap_message(client, "test-agent", "test prompt", timeout=0.1)
        assert result["status"] in ("error", "timeout")
        client.close()


# ── Dry run integration test ─────────────────────


class TestDryRun:
    """Test the dry run mode end-to-end."""

    def test_dry_run_all_kinds(self, targets, profiles_dir, capsys):
        client = bootstrap.httpx.Client(base_url="http://localhost:1")
        stats = bootstrap.run_bootstrap(
            client=client,
            agent_id="dry-run",
            targets=targets,
            profiles_dir=str(profiles_dir),
            dry_run=True,
        )
        client.close()

        assert stats["kinds"] == len(targets)
        assert stats["errors"] == 0
        assert stats["ok"] > 0

    def test_dry_run_single_kind(self, targets, profiles_dir):
        client = bootstrap.httpx.Client(base_url="http://localhost:1")
        stats = bootstrap.run_bootstrap(
            client=client,
            agent_id="dry-run",
            targets=targets,
            profiles_dir=str(profiles_dir),
            kind_filter="countries",
            dry_run=True,
        )
        client.close()

        assert stats["kinds"] == 1
        assert stats["errors"] == 0

    def test_dry_run_invalid_kind(self, targets, profiles_dir):
        client = bootstrap.httpx.Client(base_url="http://localhost:1")
        stats = bootstrap.run_bootstrap(
            client=client,
            agent_id="dry-run",
            targets=targets,
            profiles_dir=str(profiles_dir),
            kind_filter="invalid_kind",
            dry_run=True,
        )
        client.close()

        assert stats["kinds"] == 0


# ── E2E: bootstrap dry-run ─────────────────────


class TestE2EBootstrap:
    """End-to-end test: bootstrap dry-run with real targets."""

    def test_e2e_dry_run_single_kind(self, profiles_dir, targets):
        """Dry-run bootstrap for a single kind, verify stats."""
        client = bootstrap.httpx.Client(base_url="http://localhost:1")
        stats = bootstrap.run_bootstrap(
            client=client,
            agent_id="dry-run",
            targets=targets,
            profiles_dir=str(profiles_dir),
            kind_filter="countries",
            dry_run=True,
        )
        client.close()
        assert stats["kinds"] == 1
        assert stats["errors"] == 0
        assert stats["targets"] > 0

    def test_e2e_dry_run_all_kinds(self, profiles_dir, targets):
        """Dry-run all kinds, verify no errors."""
        client = bootstrap.httpx.Client(base_url="http://localhost:1")
        stats = bootstrap.run_bootstrap(
            client=client,
            agent_id="dry-run",
            targets=targets,
            profiles_dir=str(profiles_dir),
            dry_run=True,
        )
        client.close()

        assert stats["kinds"] == len(targets)
        assert stats["errors"] == 0

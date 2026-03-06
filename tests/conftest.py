"""Shared test fixtures for MCP server tests."""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def tmp_profiles(tmp_path):
    """Create a temporary profiles directory with sample data."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    # Create SCHEMAS dir
    schemas = profiles_dir / "SCHEMAS"
    schemas.mkdir()
    schemas_json = {
        "required": ["name"],
        "properties": {
            "name": "string",
            "tags": "array of strings",
            "exposure": {"countries": "array"},
        },
    }
    (schemas / "stocks.schema.json").write_text(json.dumps(schemas_json))
    (schemas / "countries.schema.json").write_text(json.dumps({
        "required": ["name", "iso2"],
        "properties": {"name": "string", "iso2": "string", "tags": "array"},
    }))

    # Create region/kind structure
    europe = profiles_dir / "europe"
    europe.mkdir()
    (europe / "countries").mkdir()
    (europe / "stocks").mkdir()

    na = profiles_dir / "north_america"
    na.mkdir()
    (na / "countries").mkdir()
    (na / "stocks").mkdir()

    global_dir = profiles_dir / "global"
    global_dir.mkdir()
    (global_dir / "commodities").mkdir()
    (global_dir / "sources").mkdir()

    # Sample profiles
    (europe / "countries" / "DEU.json").write_text(json.dumps({
        "name": "Germany",
        "iso2": "DE",
        "iso3": "DEU",
        "tags": ["eu", "g7", "eurozone"],
    }))
    (europe / "stocks" / "SAP.json").write_text(json.dumps({
        "name": "SAP SE",
        "ticker": "SAP",
        "sector": "Technology",
        "tags": ["dax", "software"],
    }))
    (na / "countries" / "USA.json").write_text(json.dumps({
        "name": "United States",
        "iso2": "US",
        "iso3": "USA",
        "tags": ["g7", "nato"],
    }))
    (na / "stocks" / "AAPL.json").write_text(json.dumps({
        "name": "Apple Inc.",
        "ticker": "AAPL",
        "sector": "Technology",
        "tags": ["sp500", "nasdaq"],
    }))
    (global_dir / "commodities" / "crude_oil.json").write_text(json.dumps({
        "name": "Crude Oil (WTI)",
        "tags": ["energy", "fossil"],
    }))
    (global_dir / "sources" / "faostat.json").write_text(json.dumps({
        "name": "FAOSTAT",
        "url": "https://www.fao.org/faostat",
        "tags": ["agriculture", "food"],
    }))

    return profiles_dir


@pytest.fixture
def mock_mongo():
    """Create a mock MongoDB client that returns mock collections."""
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_client.signals = mock_db

    # Default: empty list_collection_names so _ensure_ts tries to create
    mock_db.list_collection_names.return_value = []

    return mock_client, mock_db


@pytest.fixture
def mock_httpx_response():
    """Factory to create mock httpx responses."""
    def _make(json_data=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.text = text or json.dumps(json_data or {})
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp
    return _make

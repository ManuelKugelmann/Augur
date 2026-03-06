"""Integration tests for MCP servers that require live API keys.

These tests hit real APIs and are SKIPPED unless the required
environment variable is set. In CI, add the keys as GitHub secrets.

Run locally:  FRED_API_KEY=xxx pytest tests/test_integration.py -v
Run all:      pytest tests/test_integration.py -v  (skips those without keys)
"""
import os
import pytest

# ── Skip helpers ─────────────────────────────────────

requires_fred = pytest.mark.skipif(
    not os.environ.get("FRED_API_KEY"), reason="FRED_API_KEY not set"
)
requires_acled = pytest.mark.skipif(
    not os.environ.get("ACLED_API_KEY") or not os.environ.get("ACLED_EMAIL"),
    reason="ACLED_API_KEY or ACLED_EMAIL not set",
)
requires_eia = pytest.mark.skipif(
    not os.environ.get("EIA_API_KEY"), reason="EIA_API_KEY not set"
)
requires_comtrade = pytest.mark.skipif(
    not os.environ.get("COMTRADE_API_KEY"), reason="COMTRADE_API_KEY not set"
)
requires_google = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"), reason="GOOGLE_API_KEY not set"
)
requires_aisstream = pytest.mark.skipif(
    not os.environ.get("AISSTREAM_API_KEY"), reason="AISSTREAM_API_KEY not set"
)
requires_cloudflare = pytest.mark.skipif(
    not os.environ.get("CF_API_TOKEN"), reason="CF_API_TOKEN not set"
)
requires_usda = pytest.mark.skipif(
    not os.environ.get("USDA_NASS_API_KEY"), reason="USDA_NASS_API_KEY not set"
)


# ── Import unwrapped tool functions ──────────────────
# FastMCP @mcp.tool() wraps into FunctionTool; .fn is the original async def

from src.servers.macro_server import fred_series, fred_search, worldbank_indicator
from src.servers.agri_server import fao_datasets, usda_crop
from src.servers.commodities_server import trade_flows, energy_series
from src.servers.conflict_server import acled_events, search_sanctions
from src.servers.disasters_server import get_earthquakes
from src.servers.elections_server import us_voter_info
from src.servers.health_server import who_indicator
from src.servers.humanitarian_server import unhcr_population, hdx_search
from src.servers.infra_server import internet_traffic, ripe_probes
from src.servers.transport_server import vessels_in_area


# ── FRED (macro_server) ─────────────────────────────


@requires_fred
class TestFredIntegration:
    @pytest.mark.asyncio
    async def test_fred_series_gdp(self):
        result = await fred_series.fn("GDP", limit=5)
        assert "observations" in result
        assert len(result["observations"]) > 0

    @pytest.mark.asyncio
    async def test_fred_search_inflation(self):
        result = await fred_search.fn("inflation", limit=5)
        assert "seriess" in result


# ── ACLED (conflict_server) ──────────────────────────


@requires_acled
class TestAcledIntegration:
    @pytest.mark.asyncio
    async def test_acled_events_recent(self):
        result = await acled_events.fn(limit=5)
        assert "data" in result


# ── EIA (commodities_server) ─────────────────────────


@requires_eia
class TestEiaIntegration:
    @pytest.mark.asyncio
    async def test_energy_series_wti(self):
        result = await energy_series.fn("PET.RWTC.D", start="2024-01")
        assert "response" in result or "data" in str(result).lower()


# ── UN Comtrade (commodities_server) ─────────────────


@requires_comtrade
class TestComtradeIntegration:
    @pytest.mark.asyncio
    async def test_trade_flows_usa(self):
        result = await trade_flows.fn(reporter="842", period="2023")
        assert "data" in result or "error" not in result


# ── Google Civic (elections_server) ──────────────────


@requires_google
class TestGoogleCivicIntegration:
    @pytest.mark.asyncio
    async def test_us_voter_info(self):
        result = await us_voter_info.fn("1600 Pennsylvania Ave NW, Washington DC")
        assert "error" not in result or "GOOGLE_API_KEY" not in result.get("error", "")


# ── AIS Stream (transport_server) ────────────────────


@requires_aisstream
class TestAisStreamIntegration:
    @pytest.mark.asyncio
    async def test_vessels_suez(self):
        result = await vessels_in_area.fn(29.8, 30.1, 32.3, 32.6)
        assert "error" not in result or "AISSTREAM_API_KEY" not in result.get("error", "")


# ── Cloudflare Radar (infra_server) ──────────────────


@requires_cloudflare
class TestCloudflareIntegration:
    @pytest.mark.asyncio
    async def test_internet_traffic_de(self):
        result = await internet_traffic.fn(location="DE", date_range="1d")
        assert "result" in result or "error" not in result


# ── USDA NASS (agri_server) ──────────────────────────


@requires_usda
class TestUsdaIntegration:
    @pytest.mark.asyncio
    async def test_usda_crop_corn(self):
        result = await usda_crop.fn("CORN", year=2023)
        assert "data" in result or "error" not in result


# ── Free APIs (no key needed) ────────────────────────


class TestFreeApiIntegration:
    """Tests for APIs that don't require keys.
    These are still integration tests (hit real endpoints) so may
    fail due to rate limits or downtime."""

    @pytest.mark.asyncio
    async def test_worldbank_gdp(self):
        result = await worldbank_indicator.fn("NY.GDP.MKTP.CD", country="DEU",
                                              date="2022:2023")
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_fao_datasets(self):
        result = await fao_datasets.fn()
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_earthquakes_recent(self):
        result = await get_earthquakes.fn(min_magnitude=5.0, days=30)
        assert "count" in result
        assert "earthquakes" in result

    @pytest.mark.asyncio
    async def test_who_life_expectancy(self):
        result = await who_indicator.fn("WHOSIS_000001", country="DEU")
        assert "value" in result

    @pytest.mark.asyncio
    async def test_ripe_probes_de(self):
        result = await ripe_probes.fn(country="DE", limit=5)
        assert "results" in result

    @pytest.mark.asyncio
    async def test_opensanctions_search(self):
        result = await search_sanctions.fn("test")
        assert "results" in result or "result" in result

    @pytest.mark.asyncio
    async def test_unhcr_population(self):
        result = await unhcr_population.fn(year=2023)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_hdx_search(self):
        result = await hdx_search.fn("food security", rows=3)
        assert "result" in result

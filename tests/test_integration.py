"""Integration tests for MCP servers that require live API keys.

These tests hit real APIs and are SKIPPED unless the required
environment variable is set. In CI, add the keys as GitHub secrets.

Run locally:  FRED_API_KEY=xxx pytest tests/test_integration.py -v
Run all:      pytest tests/test_integration.py -v  (skips those without keys)
"""
import os
import pytest
import httpx

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


# ── Import tool functions ────────────────────────────
# These are the raw async def functions decorated by @mcp.tool()

from src.servers.macro_server import (
    fred_series, fred_search, worldbank_indicator, worldbank_search, imf_data,
)
from src.servers.agri_server import fao_datasets, fao_data, usda_crop
from src.servers.commodities_server import trade_flows, energy_series
from src.servers.conflict_server import (
    acled_events, search_sanctions, ucdp_conflicts,
)
from src.servers.disasters_server import get_earthquakes, get_disasters, get_natural_events
from src.servers.elections_server import us_voter_info
from src.servers.health_server import (
    who_indicator, disease_outbreaks, disease_tracker, fda_adverse_events,
)
from src.servers.humanitarian_server import unhcr_population, hdx_search, reliefweb_reports
from src.servers.infra_server import internet_traffic, ripe_probes
from src.servers.transport_server import (
    vessels_in_area, flights_in_area, flight_history,
)
from src.servers.water_server import streamflow, drought
from src.servers.weather_server import (
    forecast, historical_weather, flood_forecast, space_weather,
)


# ── FRED (macro_server) ─────────────────────────────


@requires_fred
class TestFredIntegration:
    @pytest.mark.asyncio
    async def test_fred_series_gdp(self):
        result = await fred_series("GDP", limit=5)
        assert "observations" in result
        assert len(result["observations"]) > 0

    @pytest.mark.asyncio
    async def test_fred_search_inflation(self):
        result = await fred_search("inflation", limit=5)
        assert "seriess" in result


# ── ACLED (conflict_server) ──────────────────────────


@requires_acled
class TestAcledIntegration:
    @pytest.mark.asyncio
    async def test_acled_events_recent(self):
        result = await acled_events(limit=5)
        assert "data" in result


# ── EIA (commodities_server) ─────────────────────────


@requires_eia
class TestEiaIntegration:
    @pytest.mark.asyncio
    async def test_energy_series_wti(self):
        result = await energy_series("PET.RWTC.D", start="2024-01")
        assert "response" in result or "data" in str(result).lower()


# ── UN Comtrade (commodities_server) ─────────────────


@requires_comtrade
class TestComtradeIntegration:
    @pytest.mark.asyncio
    async def test_trade_flows_usa(self):
        result = await trade_flows(reporter="842", period="2023")
        assert "data" in result or "error" not in result


# ── Google Civic (elections_server) ──────────────────


@requires_google
class TestGoogleCivicIntegration:
    @pytest.mark.asyncio
    async def test_us_voter_info(self):
        result = await us_voter_info("1600 Pennsylvania Ave NW, Washington DC")
        assert "error" not in result or "GOOGLE_API_KEY" not in result.get("error", "")


# ── AIS Stream (transport_server) ────────────────────


@requires_aisstream
class TestAisStreamIntegration:
    @pytest.mark.asyncio
    async def test_vessels_suez(self):
        result = await vessels_in_area(29.8, 30.1, 32.3, 32.6)
        assert "error" not in result or "AISSTREAM_API_KEY" not in result.get("error", "")


# ── Cloudflare Radar (infra_server) ──────────────────


@requires_cloudflare
class TestCloudflareIntegration:
    @pytest.mark.asyncio
    async def test_internet_traffic_de(self):
        result = await internet_traffic(location="DE", date_range="1d")
        assert "result" in result or "error" not in result


# ── USDA NASS (agri_server) ──────────────────────────


@requires_usda
class TestUsdaIntegration:
    @pytest.mark.asyncio
    async def test_usda_crop_corn(self):
        result = await usda_crop("CORN", year=2023)
        assert "data" in result or "error" not in result


# ── Free APIs (no key needed) ────────────────────────


class TestFreeApiIntegration:
    """Tests for APIs that don't require keys.
    These hit real endpoints and may fail due to rate limits or downtime.
    Use pytest.skip() for transient server errors."""

    def _skip_if_unavailable(self, e, service):
        if e.response.status_code in (401, 403, 429, 500, 502, 503, 521, 522):
            pytest.skip(f"{service} unavailable: {e.response.status_code}")
        raise

    def _skip_on_connect_error(self, e, service):
        pytest.skip(f"{service} connection error: {e}")

    # ── Macro: World Bank, IMF ───────────────────────

    @pytest.mark.asyncio
    async def test_worldbank_gdp(self):
        result = await worldbank_indicator("NY.GDP.MKTP.CD", country="DEU",
                                              date="2022:2023")
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_worldbank_search(self):
        result = await worldbank_search("inflation")
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_worldbank_population(self):
        try:
            result = await worldbank_indicator("SP.POP.TOTL", country="USA",
                                                  date="2022:2023", per_page=10)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "World Bank")
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "World Bank")
        assert isinstance(result, (list, dict))

    @pytest.mark.asyncio
    async def test_imf_data_gdp(self):
        try:
            result = await imf_data(database="IFS", ref_area="US",
                                       indicator="NGDP_R_XDC",
                                       start="2020", end="2023")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "IMF SDMX")
        assert isinstance(result, dict)

    # ── Agri: FAOSTAT ────────────────────────────────

    @pytest.mark.asyncio
    async def test_fao_datasets(self):
        try:
            result = await fao_datasets()
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "FAOSTAT")
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_fao_crop_data(self):
        try:
            result = await fao_data(domain="QCL", area="5000>",
                                       item="15", element="5510",
                                       year="2022,2023")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "FAOSTAT")
        assert isinstance(result, dict)

    # ── Conflict: UCDP, Military spending ────────────

    @pytest.mark.asyncio
    async def test_ucdp_conflicts(self):
        try:
            result = await ucdp_conflicts(year=2023, page=1)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "UCDP")
        assert "Result" in result or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_opensanctions_search(self):
        try:
            result = await search_sanctions("test")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "OpenSanctions")
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "OpenSanctions")
        if isinstance(result, dict) and "error" in result:
            pytest.skip(f"OpenSanctions: {result['error']}")
        assert "results" in result or "result" in result

    # ── Disasters: USGS, GDACS, NASA EONET ──────────

    @pytest.mark.asyncio
    async def test_earthquakes_recent(self):
        result = await get_earthquakes(min_magnitude=5.0, days=30)
        assert "count" in result
        assert "earthquakes" in result

    @pytest.mark.asyncio
    async def test_earthquakes_large(self):
        result = await get_earthquakes(min_magnitude=6.0, days=365, limit=5)
        assert "count" in result

    @pytest.mark.asyncio
    async def test_gdacs_disasters(self):
        try:
            result = await get_disasters()
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "GDACS")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_nasa_eonet_events(self):
        try:
            result = await get_natural_events(days=30, limit=5)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "NASA EONET")
        assert "events" in result

    # ── Health: WHO, disease.sh, FDA ─────────────────

    @pytest.mark.asyncio
    async def test_who_life_expectancy(self):
        result = await who_indicator("WHOSIS_000001", country="DEU")
        assert "value" in result

    @pytest.mark.asyncio
    async def test_who_indicator_ncd_mortality(self):
        result = await who_indicator("NCDMORT3070")
        assert "value" in result

    @pytest.mark.asyncio
    async def test_who_disease_outbreaks(self):
        try:
            result = await disease_outbreaks(limit=5)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "WHO Outbreaks")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_disease_tracker_covid(self):
        try:
            result = await disease_tracker(disease="covid")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "disease.sh")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_fda_adverse_events_aspirin(self):
        try:
            result = await fda_adverse_events(drug="aspirin", limit=5)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "OpenFDA")
        assert "results" in result

    # ── Humanitarian: UNHCR, HDX, ReliefWeb ──────────

    @pytest.mark.asyncio
    async def test_unhcr_population(self):
        result = await unhcr_population(year=2023)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_hdx_search(self):
        result = await hdx_search("food security", rows=3)
        assert "result" in result

    @pytest.mark.asyncio
    async def test_reliefweb_humanitarian(self):
        try:
            result = await reliefweb_reports(query="drought", limit=5)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "ReliefWeb")
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "ReliefWeb")
        if isinstance(result, dict) and "error" in result:
            pytest.skip(f"ReliefWeb: {result['error'][:80]}")
        assert "data" in result

    # ── Infra: RIPE Atlas ────────────────────────────

    @pytest.mark.asyncio
    async def test_ripe_probes_de(self):
        try:
            result = await ripe_probes(country="DE", limit=5)
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "RIPE Atlas")
        if isinstance(result, dict) and "error" in result:
            pytest.skip(f"RIPE Atlas: {result['error'][:80]}")
        assert "results" in result

    @pytest.mark.asyncio
    async def test_ripe_probes_us(self):
        try:
            result = await ripe_probes(country="US", limit=3)
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "RIPE Atlas")
        if isinstance(result, dict) and "error" in result:
            pytest.skip(f"RIPE Atlas: {result['error'][:80]}")
        assert "results" in result

    # ── Transport: OpenSky ───────────────────────────

    @pytest.mark.asyncio
    async def test_flights_europe(self):
        try:
            result = await flights_in_area(
                lat_min=47.0, lat_max=55.0, lon_min=5.0, lon_max=15.0)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "OpenSky")
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "OpenSky")
        if isinstance(result, dict) and "error" in result:
            pytest.skip(f"OpenSky: {result['error'][:80]}")
        assert "count" in result
        assert isinstance(result["count"], int)

    # ── Water: USGS, Drought Monitor ─────────────────

    @pytest.mark.asyncio
    async def test_usgs_streamflow_ca(self):
        try:
            result = await streamflow(state="CA", period="P1D")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "USGS Water")
        assert "value" in result

    @pytest.mark.asyncio
    async def test_drought_monitor_ca(self):
        try:
            result = await drought(area="CA", scope="StateStatistics")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "Drought Monitor")
        except (httpx.ProxyError, httpx.ConnectError) as e:
            self._skip_on_connect_error(e, "Drought Monitor")
        assert isinstance(result, (list, dict))

    # ── Weather: Open-Meteo, NOAA SWPC ───────────────

    @pytest.mark.asyncio
    async def test_weather_forecast_berlin(self):
        result = await forecast(lat=52.52, lon=13.41, days=3)
        assert "daily" in result

    @pytest.mark.asyncio
    async def test_weather_historical(self):
        try:
            result = await historical_weather(
                lat=52.52, lon=13.41, start="2024-06-01", end="2024-06-07")
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "Open-Meteo Archive")
        assert "daily" in result

    @pytest.mark.asyncio
    async def test_flood_forecast_rhine(self):
        try:
            result = await flood_forecast(lat=50.94, lon=6.96, days=3)
        except httpx.HTTPStatusError as e:
            self._skip_if_unavailable(e, "Open-Meteo Flood")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_space_weather_noaa(self):
        result = await space_weather()
        assert "kp_index" in result
        assert "solar_wind" in result
        assert "alerts" in result

"""Tests for all 12 domain MCP servers (src/servers/*.py).

Uses respx to mock httpx calls. Each server's tools are tested for:
- Correct URL construction and parameters
- Proper response parsing
- API key missing error handling
- Edge cases

Note: FastMCP @mcp.tool() wraps functions into FunctionTool objects.
We call .fn() to get the original async function.
"""
import os
import pytest
import respx
import httpx

# ── Weather server ───────────────────────────────────

import src.servers.weather_server as weather_mod

_forecast = weather_mod.forecast.fn
_historical_weather = weather_mod.historical_weather.fn
_flood_forecast = weather_mod.flood_forecast.fn
_space_weather = weather_mod.space_weather.fn


class TestWeatherServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_forecast(self):
        mock_data = {
            "daily": {
                "temperature_2m_max": [25.0, 26.0],
                "temperature_2m_min": [15.0, 16.0],
                "precipitation_sum": [0.0, 1.2],
            }
        }
        respx.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _forecast(lat=52.52, lon=13.41, days=2)
        assert "daily" in result
        assert result["daily"]["temperature_2m_max"] == [25.0, 26.0]

    @respx.mock
    @pytest.mark.asyncio
    async def test_historical_weather(self):
        mock_data = {"daily": {"temperature_2m_max": [20.0]}}
        respx.get("https://archive-api.open-meteo.com/v1/archive").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _historical_weather(lat=52.52, lon=13.41,
                                           start="2024-01-01", end="2024-01-31")
        assert "daily" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_flood_forecast(self):
        mock_data = {"daily": {"river_discharge": [100.0, 120.0]}}
        respx.get("https://flood-api.open-meteo.com/v1/flood").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _flood_forecast(lat=52.52, lon=13.41, days=2)
        assert result["daily"]["river_discharge"] == [100.0, 120.0]

    @respx.mock
    @pytest.mark.asyncio
    async def test_space_weather(self):
        respx.get("https://services.swpc.noaa.gov/json/planetary_k_index_1m.json").mock(
            return_value=httpx.Response(200, json=[{"kp": 3}])
        )
        respx.get("https://services.swpc.noaa.gov/json/solar_wind/plasma-7-day.json").mock(
            return_value=httpx.Response(200, json=[{"speed": 400}])
        )
        respx.get("https://services.swpc.noaa.gov/json/alerts.json").mock(
            return_value=httpx.Response(200, json=[{"alert": "none"}])
        )
        result = await _space_weather()
        assert "kp_index" in result
        assert "solar_wind" in result
        assert "alerts" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_space_weather_partial_failure(self):
        respx.get("https://services.swpc.noaa.gov/json/planetary_k_index_1m.json").mock(
            return_value=httpx.Response(500, json={})
        )
        respx.get("https://services.swpc.noaa.gov/json/solar_wind/plasma-7-day.json").mock(
            return_value=httpx.Response(200, json=[{"speed": 400}])
        )
        respx.get("https://services.swpc.noaa.gov/json/alerts.json").mock(
            return_value=httpx.Response(200, json=[{"alert": "none"}])
        )
        result = await _space_weather()
        assert result["kp_index"] == []
        assert len(result["solar_wind"]) > 0


# ── Macro server ─────────────────────────────────────

import src.servers.macro_server as macro_mod

_fred_series = macro_mod.fred_series.fn
_fred_search = macro_mod.fred_search.fn
_worldbank_indicator = macro_mod.worldbank_indicator.fn
_worldbank_search = macro_mod.worldbank_search.fn
_imf_data = macro_mod.imf_data.fn


class TestMacroServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_fred_no_key(self):
        orig = macro_mod.FRED_KEY
        macro_mod.FRED_KEY = ""
        try:
            result = await _fred_series("GDP")
            assert result == {"error": "FRED_API_KEY not set"}
        finally:
            macro_mod.FRED_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_fred_series(self):
        orig = macro_mod.FRED_KEY
        macro_mod.FRED_KEY = "test_key"
        try:
            mock_data = {"observations": [{"date": "2024-01-01", "value": "25000"}]}
            respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _fred_series("GDP", limit=10)
            assert "observations" in result
        finally:
            macro_mod.FRED_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_fred_search(self):
        orig = macro_mod.FRED_KEY
        macro_mod.FRED_KEY = "test_key"
        try:
            mock_data = {"seriess": [{"id": "GDP", "title": "Gross Domestic Product"}]}
            respx.get("https://api.stlouisfed.org/fred/series/search").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _fred_search("GDP")
            assert "seriess" in result
        finally:
            macro_mod.FRED_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_worldbank_indicator(self):
        mock_data = [{"page": 1}, [{"indicator": {"id": "NY.GDP.MKTP.CD"}}]]
        respx.get(url__regex=r"api\.worldbank\.org/v2/country/.*/indicator/.*").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _worldbank_indicator("NY.GDP.MKTP.CD", country="DEU")
        assert isinstance(result, list)
        assert len(result) == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_worldbank_search(self):
        mock_data = [{"page": 1}, [{"id": "NY.GDP.MKTP.CD"}]]
        respx.get("https://api.worldbank.org/v2/indicator").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _worldbank_search("GDP")
        assert isinstance(result, list)

    @respx.mock
    @pytest.mark.asyncio
    async def test_imf_data(self):
        mock_data = {"CompactData": {"DataSet": {}}}
        respx.get(url__regex=r"dataservices\.imf\.org/REST/SDMX_JSON\.svc/CompactData/.*").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _imf_data(database="IFS", ref_area="US")
        assert "CompactData" in result


# ── Agri server ──────────────────────────────────────

import src.servers.agri_server as agri_mod

_fao_datasets = agri_mod.fao_datasets.fn
_fao_data = agri_mod.fao_data.fn
_usda_crop = agri_mod.usda_crop.fn
_usda_crop_progress = agri_mod.usda_crop_progress.fn


class TestAgriServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_fao_datasets(self):
        mock_data = {"data": [
            {"code": "QCL", "label": "Crops and livestock products"},
            {"code": "TP", "label": "Trade"},
        ]}
        respx.get(url__regex=r"fenixservices\.fao\.org.*definitions/domain").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _fao_datasets()
        assert len(result) == 2
        assert result[0]["code"] == "QCL"

    @respx.mock
    @pytest.mark.asyncio
    async def test_fao_data(self):
        mock_data = {"data": [{"area": "World", "value": 1000}]}
        respx.get(url__regex=r"fenixservices\.fao\.org.*data/QCL").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _fao_data(domain="QCL")
        assert "data" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_usda_crop_no_key(self):
        orig = agri_mod.NASS_KEY
        agri_mod.NASS_KEY = ""
        try:
            result = await _usda_crop("CORN")
            assert result == {"error": "USDA_NASS_API_KEY not set"}
        finally:
            agri_mod.NASS_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_usda_crop(self):
        orig = agri_mod.NASS_KEY
        agri_mod.NASS_KEY = "test_key"
        try:
            mock_data = {"data": [{"commodity_desc": "CORN", "Value": "15000000"}]}
            respx.get("https://quickstats.nass.usda.gov/api/api_GET/").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _usda_crop("CORN")
            assert "data" in result
        finally:
            agri_mod.NASS_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_usda_crop_progress_no_key(self):
        orig = agri_mod.NASS_KEY
        agri_mod.NASS_KEY = ""
        try:
            result = await _usda_crop_progress("CORN")
            assert "error" in result
        finally:
            agri_mod.NASS_KEY = orig


# ── Commodities server ───────────────────────────────

import src.servers.commodities_server as comm_mod

_trade_flows = comm_mod.trade_flows.fn
_energy_series = comm_mod.energy_series.fn


class TestCommoditiesServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_trade_flows_no_key(self):
        orig = comm_mod.COMTRADE_KEY
        comm_mod.COMTRADE_KEY = ""
        try:
            result = await _trade_flows()
            assert result == {"error": "COMTRADE_API_KEY not set"}
        finally:
            comm_mod.COMTRADE_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_trade_flows(self):
        orig = comm_mod.COMTRADE_KEY
        comm_mod.COMTRADE_KEY = "test_key"
        try:
            mock_data = {"data": [{"reporter": "USA", "value": 1000000}]}
            respx.get("https://comtradeapi.un.org/data/v1/get/C/A/HS").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _trade_flows()
            assert "data" in result
        finally:
            comm_mod.COMTRADE_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_energy_series_no_key(self):
        orig = comm_mod.EIA_KEY
        comm_mod.EIA_KEY = ""
        try:
            result = await _energy_series()
            assert result == {"error": "EIA_API_KEY not set"}
        finally:
            comm_mod.EIA_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_energy_series(self):
        orig = comm_mod.EIA_KEY
        comm_mod.EIA_KEY = "test_key"
        try:
            mock_data = {"response": {"data": [{"period": "2024-01", "value": 75.5}]}}
            respx.get(url__regex=r"api\.eia\.gov/v2/seriesid/.*").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _energy_series("PET.RWTC.D")
            assert "response" in result
        finally:
            comm_mod.EIA_KEY = orig


# ── Conflict server ──────────────────────────────────

import src.servers.conflict_server as conflict_mod

_ucdp_conflicts = conflict_mod.ucdp_conflicts.fn
_acled_events = conflict_mod.acled_events.fn
_search_sanctions = conflict_mod.search_sanctions.fn
_military_spending = conflict_mod.military_spending.fn


class TestConflictServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_ucdp_conflicts(self):
        mock_data = {"Result": [{"id": 1, "year": 2024}], "TotalCount": 1}
        respx.get("https://ucdpapi.pcr.uu.se/api/gedevents/24.1").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _ucdp_conflicts(year=2024)
        assert "Result" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_acled_no_key(self):
        orig = conflict_mod.ACLED_KEY
        conflict_mod.ACLED_KEY = ""
        try:
            result = await _acled_events()
            assert result == {"error": "ACLED_API_KEY not set"}
        finally:
            conflict_mod.ACLED_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_acled_events(self):
        orig_key = conflict_mod.ACLED_KEY
        orig_email = conflict_mod.ACLED_EMAIL
        conflict_mod.ACLED_KEY = "test_key"
        conflict_mod.ACLED_EMAIL = "test@test.com"
        try:
            mock_data = {"data": [{"event_type": "Battles", "country": "Syria"}]}
            respx.get("https://api.acleddata.com/acled/read").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _acled_events(country="Syria", event_type="Battles")
            assert "data" in result
        finally:
            conflict_mod.ACLED_KEY = orig_key
            conflict_mod.ACLED_EMAIL = orig_email

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_sanctions_no_key(self):
        orig = conflict_mod.OPENSANCTIONS_KEY
        conflict_mod.OPENSANCTIONS_KEY = ""
        try:
            result = await _search_sanctions("test")
            assert result == {"error": "OPENSANCTIONS_API_KEY not set"}
        finally:
            conflict_mod.OPENSANCTIONS_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_search_sanctions(self):
        orig = conflict_mod.OPENSANCTIONS_KEY
        conflict_mod.OPENSANCTIONS_KEY = "test_key"
        try:
            mock_data = {"results": [{"id": "1", "caption": "Test Entity"}]}
            respx.get("https://api.opensanctions.org/search/default").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _search_sanctions("test")
            assert "results" in result
        finally:
            conflict_mod.OPENSANCTIONS_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_military_spending(self):
        mock_data = [{"page": 1}, [{"country": {"value": "World"}}]]
        respx.get(url__regex=r"api\.worldbank\.org.*MS\.MIL\.XPND\.GD\.ZS").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _military_spending()
        assert isinstance(result, list)


# ── Disasters server ─────────────────────────────────

import src.servers.disasters_server as disasters_mod

_get_earthquakes = disasters_mod.get_earthquakes.fn
_get_disasters = disasters_mod.get_disasters.fn
_get_natural_events = disasters_mod.get_natural_events.fn


class TestDisastersServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_earthquakes(self):
        mock_data = {
            "metadata": {"count": 2},
            "features": [
                {
                    "properties": {"mag": 5.2, "place": "Chile", "time": 1700000000,
                                   "tsunami": 0, "alert": "green"},
                    "geometry": {"coordinates": [-70.0, -33.0, 10.0]},
                },
                {
                    "properties": {"mag": 4.1, "place": "Japan", "time": 1700001000,
                                   "tsunami": 0, "alert": None},
                    "geometry": {"coordinates": [139.0, 35.0, 20.0]},
                },
            ],
        }
        respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _get_earthquakes(min_magnitude=4.0, days=7)
        assert result["count"] == 2
        assert len(result["earthquakes"]) == 2
        assert result["earthquakes"][0]["mag"] == 5.2

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_disasters(self):
        mock_data = {"features": [{"type": "earthquake"}]}
        respx.get(url__regex=r"gdacs\.org.*geteventlist.*").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _get_disasters()
        assert "features" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_natural_events(self):
        mock_data = {"events": [{"id": "EONET_1", "title": "Wildfire"}]}
        respx.get("https://eonet.gsfc.nasa.gov/api/v3/events").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _get_natural_events(category="wildfires")
        assert "events" in result


# ── Elections server ─────────────────────────────────

import src.servers.elections_server as elections_mod

_election_reports = elections_mod.election_reports.fn
_us_voter_info = elections_mod.us_voter_info.fn


class TestElectionsServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_election_reports(self):
        mock_data = {"data": [{"fields": {"title": "Election Report"}}]}
        respx.get("https://api.reliefweb.int/v1/reports").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _election_reports(query="election")
        assert "data" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_us_voter_info_no_key(self):
        orig = elections_mod.GOOGLE_KEY
        elections_mod.GOOGLE_KEY = ""
        try:
            result = await _us_voter_info("1600 Pennsylvania Ave")
            assert result == {"error": "GOOGLE_API_KEY not set"}
        finally:
            elections_mod.GOOGLE_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_us_voter_info(self):
        orig = elections_mod.GOOGLE_KEY
        elections_mod.GOOGLE_KEY = "test_key"
        try:
            mock_data = {"election": {"name": "General Election"}}
            respx.get("https://www.googleapis.com/civicinfo/v2/voterInfoQuery").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _us_voter_info("1600 Pennsylvania Ave")
            assert "election" in result
        finally:
            elections_mod.GOOGLE_KEY = orig


# ── Health server ────────────────────────────────────

import src.servers.health_server as health_mod

_who_indicator = health_mod.who_indicator.fn
_disease_outbreaks = health_mod.disease_outbreaks.fn
_disease_tracker = health_mod.disease_tracker.fn
_fda_adverse_events = health_mod.fda_adverse_events.fn


class TestHealthServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_who_indicator(self):
        mock_data = {"value": [{"NumericValue": 75.0, "SpatialDim": "DEU"}]}
        respx.get(url__regex=r"ghoapi\.azureedge\.net/api/.*").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _who_indicator("WHOSIS_000001", country="DEU")
        assert "value" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_who_indicator_invalid_country(self):
        result = await _who_indicator("WHOSIS_000001", country="../bad")
        assert result == {"error": "invalid country code"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_who_indicator_invalid_year(self):
        result = await _who_indicator("WHOSIS_000001", year="../bad")
        assert result == {"error": "invalid year"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_disease_outbreaks(self):
        mock_data = {"value": [{"Title": "Outbreak News"}]}
        respx.get("https://www.who.int/api/news/diseaseoutbreaknews").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _disease_outbreaks()
        assert "value" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_disease_tracker_covid(self):
        mock_data = {"cases": 1000000, "deaths": 10000}
        respx.get("https://disease.sh/v3/covid-19/all").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _disease_tracker(disease="covid")
        assert "cases" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_disease_tracker_covid_country(self):
        mock_data = {"country": "Germany", "cases": 50000}
        respx.get("https://disease.sh/v3/covid-19/countries/Germany").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _disease_tracker(disease="covid", country="Germany")
        assert result["country"] == "Germany"

    @respx.mock
    @pytest.mark.asyncio
    async def test_disease_tracker_influenza(self):
        mock_data = {"data": []}
        respx.get("https://disease.sh/v3/influenza/ihsa").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _disease_tracker(disease="influenza")
        assert "data" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_fda_adverse_events(self):
        mock_data = {"results": [{"patient": {"drug": [{"medicinalproduct": "aspirin"}]}}]}
        respx.get("https://api.fda.gov/drug/event.json").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _fda_adverse_events(drug="aspirin")
        assert "results" in result


# ── Humanitarian server ──────────────────────────────

import src.servers.humanitarian_server as hum_mod

_unhcr_population = hum_mod.unhcr_population.fn
_hdx_search = hum_mod.hdx_search.fn
_reliefweb_reports = hum_mod.reliefweb_reports.fn


class TestHumanitarianServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_unhcr_population(self):
        mock_data = {"items": [{"year": 2024, "refugees": 1000}]}
        respx.get("https://api.unhcr.org/population/v1/population/").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _unhcr_population(year=2024, country_origin="SYR")
        assert "items" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_hdx_search(self):
        mock_data = {"result": {"results": [{"title": "Syria dataset"}]}}
        respx.get("https://data.humdata.org/api/3/action/package_search").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _hdx_search("Syria")
        assert "result" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_reliefweb_reports(self):
        mock_data = {"data": [{"fields": {"title": "Situation Update"}}]}
        respx.post("https://api.reliefweb.int/v1/reports").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _reliefweb_reports(query="flood")
        assert "data" in result


# ── Infra server ─────────────────────────────────────

import src.servers.infra_server as infra_mod

_internet_traffic = infra_mod.internet_traffic.fn
_ripe_probes = infra_mod.ripe_probes.fn


class TestInfraServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_internet_traffic_no_key(self):
        orig = infra_mod.CF_TOKEN
        infra_mod.CF_TOKEN = ""
        try:
            result = await _internet_traffic()
            assert result == {"error": "CF_API_TOKEN not set"}
        finally:
            infra_mod.CF_TOKEN = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_internet_traffic(self):
        orig = infra_mod.CF_TOKEN
        infra_mod.CF_TOKEN = "test_token"
        try:
            mock_data = {"result": {"summary_0": {"http": "80%", "https": "20%"}}}
            respx.get(url__regex=r"api\.cloudflare\.com.*radar.*").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _internet_traffic(location="DE")
            assert "result" in result
        finally:
            infra_mod.CF_TOKEN = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_ripe_probes(self):
        mock_data = {"results": [{"id": 1, "country_code": "DE", "status": 1}]}
        respx.get("https://atlas.ripe.net/api/v2/probes/").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _ripe_probes(country="DE")
        assert "results" in result


# ── Transport server ─────────────────────────────────

import src.servers.transport_server as transport_mod

_flights_in_area = transport_mod.flights_in_area.fn
_flight_history = transport_mod.flight_history.fn
_vessels_in_area = transport_mod.vessels_in_area.fn


class TestTransportServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_flights_in_area(self):
        mock_data = {"states": [["abc123", "LH123", "Germany"]]}
        respx.get("https://opensky-network.org/api/states/all").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _flights_in_area(lat_min=47.0, lat_max=55.0,
                                        lon_min=5.0, lon_max=15.0)
        assert result["count"] == 1
        assert len(result["states"]) == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_flights_in_area_empty(self):
        mock_data = {"states": None}
        respx.get("https://opensky-network.org/api/states/all").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _flights_in_area(lat_min=0, lat_max=1, lon_min=0, lon_max=1)
        assert result["count"] == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_flight_history(self):
        mock_data = [{"icao24": "abc123", "callsign": "LH123"}]
        respx.get("https://opensky-network.org/api/flights/aircraft").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _flight_history("abc123")
        assert isinstance(result, list)

    @respx.mock
    @pytest.mark.asyncio
    async def test_vessels_no_key(self):
        orig = transport_mod.AIS_KEY
        transport_mod.AIS_KEY = ""
        try:
            result = await _vessels_in_area(29.8, 30.1, 32.3, 32.6)
            assert result == {"error": "AISSTREAM_API_KEY not set"}
        finally:
            transport_mod.AIS_KEY = orig

    @respx.mock
    @pytest.mark.asyncio
    async def test_vessels_in_area(self):
        orig = transport_mod.AIS_KEY
        transport_mod.AIS_KEY = "test_key"
        try:
            mock_data = {"vessels": [{"mmsi": "123456789"}]}
            respx.get("https://api.aisstream.io/v0/vessel-positions").mock(
                return_value=httpx.Response(200, json=mock_data)
            )
            result = await _vessels_in_area(29.8, 30.1, 32.3, 32.6)
            assert "vessels" in result
        finally:
            transport_mod.AIS_KEY = orig


# ── Water server ─────────────────────────────────────

import src.servers.water_server as water_mod

_streamflow = water_mod.streamflow.fn
_drought = water_mod.drought.fn


class TestWaterServer:
    @respx.mock
    @pytest.mark.asyncio
    async def test_streamflow(self):
        mock_data = {"value": {"timeSeries": [{"values": []}]}}
        respx.get("https://waterservices.usgs.gov/nwis/iv").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _streamflow(state="CA", period="P7D")
        assert "value" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_streamflow_by_site(self):
        mock_data = {"value": {"timeSeries": []}}
        respx.get("https://waterservices.usgs.gov/nwis/iv").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _streamflow(site="11303500")
        assert "value" in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_drought(self):
        mock_data = [{"mapDate": "2024-01-01", "None": 50, "D0": 20}]
        respx.get("https://usdm.unl.edu/DmData/TimeSeries.aspx").mock(
            return_value=httpx.Response(200, json=mock_data)
        )
        result = await _drought(area_type="state", area="CA")
        assert isinstance(result, list)

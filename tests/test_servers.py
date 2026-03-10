"""Tests for the 12 domain MCP servers.

Each server is an async httpx-based tool. Tests mock httpx.AsyncClient to verify:
- Correct URL/param construction
- API key checks (return error dict when missing)
- Response transformation (e.g., earthquake flattening)
- Input validation (e.g., health _SAFE_ODATA)
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("httpx", reason="httpx required for server tests")

# Add servers dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "servers"))


# ── Helpers ──────────────────────────────────────

def _mock_response(data, status_code=200):
    """Create a mock httpx.Response.

    httpx.Response.json() and .raise_for_status() are sync methods,
    so we use MagicMock (not AsyncMock) for those.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _patch_httpx_get(response):
    """Return a patch context for httpx.AsyncClient that returns response on get()."""
    client = AsyncMock()
    client.get.return_value = response
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=client), client


# ── Weather Server ────────────────────────────────


class TestWeatherServer:
    @pytest.fixture(autouse=True)
    def _import(self):
        import weather_server
        self.mod = weather_server

    @pytest.mark.asyncio
    async def test_forecast_calls_open_meteo(self):
        resp = _mock_response({"daily": {"temperature_2m_max": [20]}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.forecast(lat=52.5, lon=13.4, days=3)
        assert result["daily"]["temperature_2m_max"] == [20]
        url = client.get.call_args[0][0]
        assert "open-meteo.com" in url
        assert client.get.call_args[1]["params"]["forecast_days"] == 3

    @pytest.mark.asyncio
    async def test_historical_weather_params(self):
        resp = _mock_response({"daily": {}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.historical_weather(lat=40, lon=-74, start="2023-01-01", end="2023-12-31")
        params = client.get.call_args[1]["params"]
        assert params["start_date"] == "2023-01-01"
        assert params["end_date"] == "2023-12-31"

    @pytest.mark.asyncio
    async def test_flood_forecast(self):
        resp = _mock_response({"daily": {"river_discharge": [100]}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.flood_forecast(lat=51, lon=7)
        assert "daily" in result
        assert "flood-api.open-meteo.com" in client.get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_space_weather_aggregates(self):
        kp_resp = _mock_response([{"kp": 3}] * 10)
        solar_resp = _mock_response([{"speed": 400}] * 10)
        alerts_resp = _mock_response([{"alert": "G1"}] * 3)
        client = AsyncMock()
        client.get = AsyncMock(side_effect=[kp_resp, solar_resp, alerts_resp])
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            result = await self.mod.space_weather()
        assert len(result["kp_index"]) == 5
        assert len(result["solar_wind"]) == 5
        assert len(result["alerts"]) == 3


# ── Macro Server ──────────────────────────────────


class TestMacroServer:
    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test_key")
        # Reimport to pick up env
        if "macro_server" in sys.modules:
            del sys.modules["macro_server"]
        import macro_server
        self.mod = macro_server

    @pytest.mark.asyncio
    async def test_fred_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "FRED_KEY", "")
        result = await self.mod.fred_series("GDP")
        assert result["error"] == "FRED_API_KEY not set"

    @pytest.mark.asyncio
    async def test_fred_series_params(self):
        resp = _mock_response({"observations": [{"value": "100"}]})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.fred_series("UNRATE", limit=50)
        params = client.get.call_args[1]["params"]
        assert params["series_id"] == "UNRATE"
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_worldbank_indicator(self):
        resp = _mock_response([{}, [{"value": 4000}]])
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.worldbank_indicator(country="DEU")
        url = client.get.call_args[0][0]
        assert "DEU" in url
        assert "worldbank.org" in url

    @pytest.mark.asyncio
    async def test_imf_data_url(self):
        resp = _mock_response({"data": {}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.imf_data(database="IFS", ref_area="DE", indicator="NGDP_R_XDC")
        url = client.get.call_args[0][0]
        assert "IFS" in url
        assert "DE" in url
        assert "NGDP_R_XDC" in url


# ── Disasters Server ─────────────────────────────


class TestDisastersServer:
    @pytest.fixture(autouse=True)
    def _import(self):
        import disasters_server
        self.mod = disasters_server

    @pytest.mark.asyncio
    async def test_earthquakes_transform(self):
        raw = {
            "metadata": {"count": 1},
            "features": [{
                "properties": {"mag": 5.2, "place": "Tokyo", "time": 1234567890,
                               "tsunami": 0, "alert": "green"},
                "geometry": {"coordinates": [139.7, 35.7, 10]}
            }]
        }
        resp = _mock_response(raw)
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.get_earthquakes(min_magnitude=4.0, days=7)
        assert result["count"] == 1
        assert result["earthquakes"][0]["mag"] == 5.2
        assert result["earthquakes"][0]["place"] == "Tokyo"
        assert result["earthquakes"][0]["coords"] == [139.7, 35.7, 10]

    @pytest.mark.asyncio
    async def test_earthquakes_alert_filter(self):
        raw = {"metadata": {"count": 0}, "features": []}
        resp = _mock_response(raw)
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.get_earthquakes(alert_level="red")
        params = client.get.call_args[1]["params"]
        assert params["alertlevel"] == "red"

    @pytest.mark.asyncio
    async def test_natural_events_category(self):
        resp = _mock_response({"events": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.get_natural_events(category="wildfires", days=14)
        params = client.get.call_args[1]["params"]
        assert params["category"] == "wildfires"
        assert params["days"] == 14


# ── Health Server ─────────────────────────────────


class TestHealthServer:
    @pytest.fixture(autouse=True)
    def _import(self):
        import health_server
        self.mod = health_server

    def test_safe_odata_regex(self):
        assert self.mod._SAFE_ODATA.match("DEU")
        assert self.mod._SAFE_ODATA.match("2024")
        assert not self.mod._SAFE_ODATA.match("'; DROP TABLE --")
        assert not self.mod._SAFE_ODATA.match("a b")
        assert not self.mod._SAFE_ODATA.match("")

    @pytest.mark.asyncio
    async def test_who_rejects_injection(self):
        result = await self.mod.who_indicator(country="'; DROP TABLE")
        assert result["error"] == "invalid country code"

    @pytest.mark.asyncio
    async def test_who_rejects_invalid_year(self):
        result = await self.mod.who_indicator(year="2024; DROP")
        assert result["error"] == "invalid year"

    @pytest.mark.asyncio
    async def test_who_rejects_invalid_indicator(self):
        result = await self.mod.who_indicator(indicator="../../etc/passwd")
        assert result["error"] == "invalid indicator code"

    @pytest.mark.asyncio
    async def test_disease_tracker_rejects_bad_country(self):
        result = await self.mod.disease_tracker(country="../../admin")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_disease_tracker_rejects_bad_disease(self):
        result = await self.mod.disease_tracker(disease="malware")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fda_rejects_bad_drug(self):
        result = await self.mod.fda_adverse_events(drug="aspirin'; DROP TABLE")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_who_indicator_builds_filter(self):
        resp = _mock_response({"value": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.who_indicator(indicator="WHOSIS_000001", country="DEU", year="2022")
        params = client.get.call_args[1]["params"]
        assert "SpatialDim eq 'DEU'" in params["$filter"]
        assert "TimeDim eq 2022" in params["$filter"]

    @pytest.mark.asyncio
    async def test_disease_tracker_covid_url(self):
        resp = _mock_response({"cases": 1000})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.disease_tracker(disease="covid", country="Germany")
        url = client.get.call_args[0][0]
        assert "covid-19" in url
        assert "Germany" in url

    @pytest.mark.asyncio
    async def test_disease_tracker_all(self):
        resp = _mock_response({"cases": 1000})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.disease_tracker(disease="covid")
        url = client.get.call_args[0][0]
        assert url.endswith("/all")


# ── Agri Server ───────────────────────────────────


class TestAgriServer:
    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        monkeypatch.setenv("USDA_NASS_API_KEY", "test_key")
        if "agri_server" in sys.modules:
            del sys.modules["agri_server"]
        import agri_server
        self.mod = agri_server

    @pytest.mark.asyncio
    async def test_fao_datasets_transforms(self):
        raw = {"data": [{"code": "QCL", "label": "Crops"}, {"code": "TP", "label": "Trade"}]}
        resp = _mock_response(raw)
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.fao_datasets()
        assert result == {"datasets": [{"code": "QCL", "label": "Crops"}, {"code": "TP", "label": "Trade"}]}

    @pytest.mark.asyncio
    async def test_usda_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "NASS_KEY", "")
        result = await self.mod.usda_crop("CORN")
        assert result["error"] == "USDA_NASS_API_KEY not set"

    @pytest.mark.asyncio
    async def test_usda_crop_uppercases(self):
        resp = _mock_response({"data": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.usda_crop("corn")
        params = client.get.call_args[1]["params"]
        assert params["commodity_desc"] == "CORN"


# ── Commodities Server ───────────────────────────


class TestCommoditiesServer:
    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        monkeypatch.setenv("COMTRADE_API_KEY", "test_ct_key")
        monkeypatch.setenv("EIA_API_KEY", "test_eia_key")
        if "commodities_server" in sys.modules:
            del sys.modules["commodities_server"]
        import commodities_server
        self.mod = commodities_server

    @pytest.mark.asyncio
    async def test_trade_flows_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "COMTRADE_KEY", "")
        result = await self.mod.trade_flows()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_energy_series_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "EIA_KEY", "")
        result = await self.mod.energy_series()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_energy_series_url(self):
        resp = _mock_response({"response": {"data": []}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.energy_series(series="PET.RWTC.D")
        url = client.get.call_args[0][0]
        assert "PET.RWTC.D" in url


# ── Conflict Server ──────────────────────────────


class TestConflictServer:
    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        monkeypatch.setenv("ACLED_EMAIL", "test@test.com")
        monkeypatch.setenv("ACLED_PASSWORD", "test_pass")
        monkeypatch.setenv("UCDP_ACCESS_TOKEN", "test_ucdp_token")
        if "conflict_server" in sys.modules:
            del sys.modules["conflict_server"]
        import conflict_server
        self.mod = conflict_server

    @pytest.mark.asyncio
    async def test_acled_missing_credentials(self, monkeypatch):
        monkeypatch.setattr(self.mod, "ACLED_EMAIL", "")
        monkeypatch.setattr(self.mod, "ACLED_PASSWORD", "")
        monkeypatch.setattr(self.mod, "_acled_token", "")
        result = await self.mod.acled_events()
        assert "error" in result
        assert "ACLED_EMAIL" in result["error"]

    @pytest.mark.asyncio
    async def test_acled_date_filter(self, monkeypatch):
        import time as _time
        monkeypatch.setattr(self.mod, "_acled_token", "cached-token")
        monkeypatch.setattr(self.mod, "_acled_token_exp", _time.time() + 9999)
        resp = _mock_response({"data": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.acled_events(event_date_start="2024-01-01")
        params = client.get.call_args[1]["params"]
        assert params["event_date"] == "2024-01-01|"
        assert "Bearer" in client.get.call_args[1]["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_ucdp_sends_token(self):
        resp = _mock_response({"Result": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.ucdp_conflicts(year=2024)
        headers = client.get.call_args[1]["headers"]
        assert headers["x-ucdp-access-token"] == "test_ucdp_token"
        url = client.get.call_args[0][0]
        assert "25.1" in url

    @pytest.mark.asyncio
    async def test_ucdp_custom_version(self):
        resp = _mock_response({"Result": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.ucdp_conflicts(year=2023, version="24.1")
        url = client.get.call_args[0][0]
        assert "24.1" in url

    @pytest.mark.asyncio
    async def test_ucdp_candidate_events(self):
        resp = _mock_response({"Result": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.ucdp_candidate_events(country="Syria")
        params = client.get.call_args[1]["params"]
        assert params["Country"] == "Syria"
        url = client.get.call_args[0][0]
        assert "26.0.1" in url
        headers = client.get.call_args[1]["headers"]
        assert headers["x-ucdp-access-token"] == "test_ucdp_token"

    @pytest.mark.asyncio
    async def test_views_forecast_params(self):
        resp = _mock_response({"data": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.views_forecast(
                iso="ukr", level="cm", violence_type="sb",
                date_start="2025-01-01"
            )
        url = client.get.call_args[0][0]
        assert "/current/cm/sb" in url
        assert "api.viewsforecasting.org" in url
        params = client.get.call_args[1]["params"]
        assert params["iso"] == "UKR"
        assert params["date_start"] == "2025-01-01"

    @pytest.mark.asyncio
    async def test_views_forecast_pgm(self):
        resp = _mock_response({"data": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.views_forecast(level="pgm", violence_type="ns")
        url = client.get.call_args[0][0]
        assert "/current/pgm/ns" in url

    @pytest.mark.asyncio
    async def test_sanctions_search(self):
        old_key = self.mod.OPENSANCTIONS_KEY
        self.mod.OPENSANCTIONS_KEY = "test-key"
        try:
            resp = _mock_response({"results": []})
            patcher, client = _patch_httpx_get(resp)
            with patcher:
                await self.mod.search_sanctions("Putin", schema="Person")
            params = client.get.call_args[1]["params"]
            assert params["q"] == "Putin"
            assert params["schema"] == "Person"
            assert "ApiKey test-key" in client.get.call_args[1]["headers"]["Authorization"]
        finally:
            self.mod.OPENSANCTIONS_KEY = old_key

    @pytest.mark.asyncio
    async def test_sanctions_no_key(self):
        old_key = self.mod.OPENSANCTIONS_KEY
        self.mod.OPENSANCTIONS_KEY = ""
        try:
            result = await self.mod.search_sanctions("Putin")
            assert "error" in result
            assert "OPENSANCTIONS_API_KEY" in result["error"]
        finally:
            self.mod.OPENSANCTIONS_KEY = old_key


# ── Elections Server ─────────────────────────────


class TestElectionsServer:
    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "test_google")
        if "elections_server" in sys.modules:
            del sys.modules["elections_server"]
        import elections_server
        self.mod = elections_server

    @pytest.mark.asyncio
    async def test_heads_of_state_country(self):
        search_resp = _mock_response({"search": [{"id": "Q183"}]})
        sparql_resp = _mock_response({"results": {"bindings": []}})
        patcher, client = _patch_httpx_get(search_resp)
        client.get.side_effect = [search_resp, sparql_resp]
        with patcher:
            await self.mod.heads_of_state(country="Germany", limit=5)
        sparql_call = client.get.call_args_list[1]
        assert "Q183" in sparql_call[1]["params"]["query"]

    @pytest.mark.asyncio
    async def test_voter_info_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "GOOGLE_KEY", "")
        result = await self.mod.us_voter_info("123 Main St")
        assert result["error"] == "GOOGLE_API_KEY not set"

    @pytest.mark.asyncio
    async def test_global_elections_rejects_sparql_injection(self):
        result = await self.mod.global_elections(country='")}\nDELETE{?s ?p ?o}#')
        assert "error" in result

    @pytest.mark.asyncio
    async def test_global_elections_rejects_bad_year(self):
        result = await self.mod.global_elections(year="2025; DROP")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_heads_of_state_rejects_sparql_injection(self):
        result = await self.mod.heads_of_state(country='")}\nDELETE{?s ?p ?o}#')
        assert "error" in result

    @pytest.mark.asyncio
    async def test_global_elections_wikidata(self):
        search_resp = _mock_response({"search": [{"id": "Q183"}]})
        sparql_resp = _mock_response({"results": {"bindings": [
            {"electionLabel": {"value": "2025 German federal election"},
             "countryLabel": {"value": "Germany"},
             "date": {"value": "2025-02-23"},
             "typeLabel": {"value": "general election"}}
        ]}})
        patcher, client = _patch_httpx_get(search_resp)
        client.get.side_effect = [search_resp, sparql_resp]
        with patcher:
            result = await self.mod.global_elections(country="Germany", year="2025")
        assert len(result["elections"]) == 1
        assert result["elections"][0]["country"] == "Germany"
        sparql_url = client.get.call_args_list[1][0][0]
        assert "wikidata.org" in sparql_url

    @pytest.mark.asyncio
    async def test_heads_of_state_params(self):
        search_resp = _mock_response({"search": [{"id": "Q183"}]})
        sparql_resp = _mock_response({"results": {"bindings": [
            {"personLabel": {"value": "Friedrich Merz"},
             "countryLabel": {"value": "Germany"},
             "positionLabel": {"value": "Chancellor"},
             "start": {"value": "2025-05-06"}}
        ]}})
        patcher, client = _patch_httpx_get(search_resp)
        client.get.side_effect = [search_resp, sparql_resp]
        with patcher:
            result = await self.mod.heads_of_state(country="Germany")
        assert result["leaders"][0]["person"] == "Friedrich Merz"
        assert result["leaders"][0]["position"] == "Chancellor"

    @pytest.mark.asyncio
    async def test_eu_parliament_meps_country(self):
        resp = _mock_response({"data": [{"id": "1", "name": "Test MEP"}]})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.eu_parliament_meps(country="DE")
        params = client.get.call_args[1]["params"]
        assert params["country-of-representation"] == "DE"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_eu_parliament_votes_year(self):
        resp = _mock_response({"data": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.eu_parliament_votes(year="2024")
        params = client.get.call_args[1]["params"]
        assert params["year"] == "2024"

    # us_representatives tests removed — Google Civic Representatives API was
    # permanently shut down April 30, 2025. Tool removed from elections_server.py.

    @pytest.mark.asyncio
    async def test_us_voter_info_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "GOOGLE_KEY", "")
        result = await self.mod.us_voter_info("123 Main St")
        assert result["error"] == "GOOGLE_API_KEY not set"


# ── Humanitarian Server (via conflict import — legacy) ──


class TestHumanitarianViaConflict:
    """These tests were originally importing conflict_server for humanitarian
    tools — the humanitarian_server tests below are the correct ones."""

    @pytest.fixture(autouse=True)
    def _import(self):
        import humanitarian_server
        self.mod = humanitarian_server

    @pytest.mark.asyncio
    async def test_unhcr_filters(self):
        resp = _mock_response({"items": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.unhcr_population(country_origin="SYR", country_asylum="DEU")
        params = client.get.call_args[1]["params"]
        assert params["coo"] == "SYR"
        assert params["coa"] == "DEU"

    @pytest.mark.asyncio
    async def test_reliefweb_uses_post(self):
        old = self.mod.RELIEFWEB_APPNAME
        self.mod.RELIEFWEB_APPNAME = "test-app"
        try:
            resp = _mock_response({"data": []})
            patcher, client = _patch_httpx_get(resp)
            with patcher:
                await self.mod.reliefweb_reports(query="flood", country="Bangladesh")
            # Should use POST
            client.post.assert_called_once()
            body = client.post.call_args[1]["json"]
            assert body["query"]["value"] == "flood"
            assert body["filter"]["value"] == ["Bangladesh"]
        finally:
            self.mod.RELIEFWEB_APPNAME = old


# ── Transport Server ─────────────────────────────


class TestTransportServer:
    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        monkeypatch.setenv("AISSTREAM_API_KEY", "test_ais")
        if "transport_server" in sys.modules:
            del sys.modules["transport_server"]
        import transport_server
        self.mod = transport_server
        # Reset cached OAuth2 token between tests
        self.mod._opensky_token = ""
        self.mod._opensky_token_exp = 0

    @pytest.mark.asyncio
    async def test_flights_in_area_truncates(self):
        states = [[f"plane_{i}"] for i in range(100)]
        resp = _mock_response({"time": 1000, "states": states})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.flights_in_area(
                lat_min=40, lat_max=42, lon_min=-75, lon_max=-73
            )
        assert result["count"] == 100
        assert len(result["states"]) == 50  # truncated
        # States are labelled dicts now
        assert isinstance(result["states"][0], dict)

    @pytest.mark.asyncio
    async def test_flights_in_area_extended(self):
        resp = _mock_response({"time": 1000, "states": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.flights_in_area(
                lat_min=40, lat_max=42, lon_min=-75, lon_max=-73, extended=True
            )
        params = client.get.call_args[1]["params"]
        assert params["extended"] == 1

    @pytest.mark.asyncio
    async def test_flights_in_area_labels_states(self):
        raw = ["abc123", "DLH123 ", "Germany", 1000, 1001,
               8.5, 50.1, 10000, False, 250, 90, 0, None, 10100,
               "1234", False, 0, 2]
        resp = _mock_response({"time": 1000, "states": [raw]})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            result = await self.mod.flights_in_area(
                lat_min=49, lat_max=51, lon_min=7, lon_max=9
            )
        s = result["states"][0]
        assert s["icao24"] == "abc123"
        assert s["callsign"] == "DLH123 "
        assert s["latitude"] == 50.1
        # None values are excluded
        assert "sensors" not in s

    @pytest.mark.asyncio
    async def test_vessels_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "AIS_KEY", "")
        result = await self.mod.vessels_in_area(
            lat_min=29.8, lat_max=30.1, lon_min=32.3, lon_max=32.6
        )
        assert result["error"] == "AISSTREAM_API_KEY not set"

    @pytest.mark.asyncio
    async def test_flight_history_lowercases_icao(self):
        resp = _mock_response([])
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.flight_history(icao24="ABC123", begin=1000, end=2000)
        params = client.get.call_args[1]["params"]
        assert params["icao24"] == "abc123"
        assert params["begin"] == 1000
        assert params["end"] == 2000

    @pytest.mark.asyncio
    async def test_oauth2_with_secret(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "test-client")
        monkeypatch.setattr(oauth, "_secret", "test-secret")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "tok123", "expires_in": 1800})
        patcher, client = _patch_httpx_get(token_resp)
        with patcher:
            headers = await oauth.headers()
        assert headers == {"Authorization": "Bearer tok123"}
        post_data = client.post.call_args[1]["data"]
        assert post_data["client_id"] == "test-client"
        assert post_data["client_secret"] == "test-secret"
        assert post_data["grant_type"] == "client_credentials"

    @pytest.mark.asyncio
    async def test_oauth2_public_client(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "pub-client")
        monkeypatch.setattr(oauth, "_secret", "")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "tok456", "expires_in": 1800})
        patcher, client = _patch_httpx_get(token_resp)
        with patcher:
            headers = await oauth.headers()
        assert headers == {"Authorization": "Bearer tok456"}
        post_data = client.post.call_args[1]["data"]
        assert "client_secret" not in post_data

    @pytest.mark.asyncio
    async def test_oauth2_no_credentials(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "")
        headers = await oauth.headers()
        assert headers == {}

    @pytest.mark.asyncio
    async def test_oauth2_caches_token(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "test-client")
        monkeypatch.setattr(oauth, "_secret", "sec")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "cached", "expires_in": 1800})
        patcher, client = _patch_httpx_get(token_resp)
        with patcher:
            h1 = await oauth.headers()
            h2 = await oauth.headers()
        assert h1 == h2 == {"Authorization": "Bearer cached"}
        assert client.post.call_count == 1  # only one token request

    @pytest.mark.asyncio
    async def test_own_states_requires_auth(self, monkeypatch):
        monkeypatch.setattr(self.mod, "OPENSKY_CLIENT_ID", "")
        result = await self.mod.own_states()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_own_states_params(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "c")
        monkeypatch.setattr(oauth, "_secret", "s")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "t", "expires_in": 1800})
        states_resp = _mock_response({"time": 1, "states": []})
        client = AsyncMock()
        client.post.return_value = token_resp
        client.get.return_value = states_resp
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            await self.mod.own_states(icao24="abc", serials="123,456")
        params = client.get.call_args[1]["params"]
        assert params["icao24"] == "abc"
        assert params["serials"] == "123,456"

    @pytest.mark.asyncio
    async def test_all_flights_requires_auth(self, monkeypatch):
        monkeypatch.setattr(self.mod, "OPENSKY_CLIENT_ID", "")
        result = await self.mod.all_flights(begin=1000, end=2000)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_all_flights_params(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "c")
        monkeypatch.setattr(oauth, "_secret", "s")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "t", "expires_in": 1800})
        flights_resp = _mock_response([{"icao24": "abc"}])
        client = AsyncMock()
        client.post.return_value = token_resp
        client.get.return_value = flights_resp
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            result = await self.mod.all_flights(begin=1000, end=2000)
        params = client.get.call_args[1]["params"]
        assert params["begin"] == 1000
        assert params["end"] == 2000

    @pytest.mark.asyncio
    async def test_airport_arrivals_requires_auth(self, monkeypatch):
        monkeypatch.setattr(self.mod, "OPENSKY_CLIENT_ID", "")
        result = await self.mod.airport_arrivals(
            airport="EDDF", begin=1000, end=2000
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_airport_arrivals_uppercases(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "c")
        monkeypatch.setattr(oauth, "_secret", "s")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "t", "expires_in": 1800})
        flights_resp = _mock_response([])
        client = AsyncMock()
        client.post.return_value = token_resp
        client.get.return_value = flights_resp
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            result = await self.mod.airport_arrivals(
                airport="eddf", begin=1000, end=2000
            )
        params = client.get.call_args[1]["params"]
        assert params["airport"] == "EDDF"
        assert result["airport"] == "EDDF"

    @pytest.mark.asyncio
    async def test_airport_departures_requires_auth(self, monkeypatch):
        monkeypatch.setattr(self.mod, "OPENSKY_CLIENT_ID", "")
        result = await self.mod.airport_departures(
            airport="KJFK", begin=1000, end=2000
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_flight_track_requires_auth(self, monkeypatch):
        monkeypatch.setattr(self.mod, "OPENSKY_CLIENT_ID", "")
        result = await self.mod.flight_track(icao24="abc123")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_flight_track_waypoints(self, monkeypatch):
        oauth = self.mod._opensky_oauth
        monkeypatch.setattr(oauth, "_client_id", "c")
        monkeypatch.setattr(oauth, "_secret", "s")
        monkeypatch.setattr(oauth, "_token", "")
        monkeypatch.setattr(oauth, "_exp", 0)
        token_resp = _mock_response({"access_token": "t", "expires_in": 1800})
        track_resp = _mock_response({
            "icao24": "abc123", "callsign": "DLH123",
            "startTime": 1000, "endTime": 2000,
            "path": [[1000, 50.1, 8.5, 10000, 90, False]]
        })
        client = AsyncMock()
        client.post.return_value = token_resp
        client.get.return_value = track_resp
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            result = await self.mod.flight_track(icao24="ABC123", time_stamp=1000)
        params = client.get.call_args[1]["params"]
        assert params["icao24"] == "abc123"
        assert params["time"] == 1000
        assert result["icao24"] == "abc123"
        assert len(result["waypoints"]) == 1
        wp = result["waypoints"][0]
        assert wp["latitude"] == 50.1
        assert wp["on_ground"] is False


# ── Water Server ─────────────────────────────────


class TestWaterServer:
    @pytest.fixture(autouse=True)
    def _import(self):
        import water_server
        self.mod = water_server

    @pytest.mark.asyncio
    async def test_streamflow_by_site(self):
        resp = _mock_response({"value": {"timeSeries": []}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.streamflow(site="01646500")
        params = client.get.call_args[1]["params"]
        assert params["sites"] == "01646500"
        assert "stateCd" not in params

    @pytest.mark.asyncio
    async def test_streamflow_by_state(self):
        resp = _mock_response({"value": {}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.streamflow(state="TX")
        params = client.get.call_args[1]["params"]
        assert params["stateCd"] == "TX"

    @pytest.mark.asyncio
    async def test_groundwater_by_state(self):
        resp = _mock_response({"value": {}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.groundwater(state="CA")
        params = client.get.call_args[1]["params"]
        assert params["stateCd"] == "CA"
        assert params["parameterCd"] == "72019"
        assert params["siteType"] == "GW"

    @pytest.mark.asyncio
    async def test_drought_uses_fips(self):
        resp = _mock_response([])
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.drought(area="CA")
        params = client.get.call_args[1]["params"]
        assert params["aoi"] == "06"  # CA -> FIPS 06

    @pytest.mark.asyncio
    async def test_drought_dsci(self):
        resp = _mock_response([])
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.drought_dsci(area="TX")
        url = client.get.call_args[0][0]
        assert "GetDSCI" in url
        params = client.get.call_args[1]["params"]
        assert params["aoi"] == "48"  # TX -> FIPS 48

    @pytest.mark.asyncio
    async def test_water_quality_params(self):
        resp = _mock_response({"value": {}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.water_quality(state="NY", parameter="00300")
        params = client.get.call_args[1]["params"]
        assert params["stateCd"] == "NY"
        assert params["parameterCd"] == "00300"


# ── Humanitarian Server ──────────────────────────


class TestHumanitarianServer:
    @pytest.fixture(autouse=True)
    def _import(self):
        import humanitarian_server
        self.mod = humanitarian_server

    @pytest.mark.asyncio
    async def test_unhcr_population_params(self):
        resp = _mock_response({"items": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.unhcr_population(year=2023, country_origin="SYR")
        params = client.get.call_args[1]["params"]
        assert params["year"] == 2023
        assert params["coo"] == "SYR"

    @pytest.mark.asyncio
    async def test_unhcr_demographics(self):
        resp = _mock_response({"items": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.unhcr_demographics(year=2023, country_asylum="DEU")
        params = client.get.call_args[1]["params"]
        assert params["coa"] == "DEU"

    @pytest.mark.asyncio
    async def test_hdx_search(self):
        resp = _mock_response({"success": True, "result": {"results": []}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.hdx_search(query="displacement")
        params = client.get.call_args[1]["params"]
        assert params["q"] == "displacement"

    @pytest.mark.asyncio
    async def test_reliefweb_reports_missing_appname(self):
        old = self.mod.RELIEFWEB_APPNAME
        self.mod.RELIEFWEB_APPNAME = ""
        try:
            result = await self.mod.reliefweb_reports(query="drought")
            assert "error" in result
            assert "RELIEFWEB_APPNAME" in result["error"]
        finally:
            self.mod.RELIEFWEB_APPNAME = old

    @pytest.mark.asyncio
    async def test_reliefweb_reports_country_filter(self):
        old = self.mod.RELIEFWEB_APPNAME
        self.mod.RELIEFWEB_APPNAME = "test-app"
        try:
            resp = _mock_response({"data": []})
            patcher, client = _patch_httpx_get(resp)
            with patcher:
                await self.mod.reliefweb_reports(country="Syria")
            body = client.post.call_args[1]["json"]
            assert body["filter"]["field"] == "country.name"
            assert "Syria" in body["filter"]["value"]
        finally:
            self.mod.RELIEFWEB_APPNAME = old

    @pytest.mark.asyncio
    async def test_idmc_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "IDMC_KEY", "")
        result = await self.mod.idmc_displacement(iso3="SYR")
        assert "error" in result
        assert "IDMC_API_KEY" in result["error"]

    @pytest.mark.asyncio
    async def test_idmc_displacement_params(self, monkeypatch):
        monkeypatch.setattr(self.mod, "IDMC_KEY", "test-key")
        resp = _mock_response({"results": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.idmc_displacement(iso3="SYR", start_year=2020)
        url = client.get.call_args[0][0]
        assert "displacement-export" in url
        params = client.get.call_args[1]["params"]
        assert params["iso3__in"] == "SYR"
        assert params["start_year"] == 2020


# ── Infra Server ─────────────────────────────────


class TestInfraServer:
    @pytest.fixture(autouse=True)
    def _import(self):
        import infra_server
        self.mod = infra_server

    @pytest.mark.asyncio
    async def test_internet_traffic_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "CF_TOKEN", "")
        result = await self.mod.internet_traffic(location="US")
        assert result["error"] == "CF_API_TOKEN not set"

    @pytest.mark.asyncio
    async def test_internet_traffic_params(self, monkeypatch):
        monkeypatch.setattr(self.mod, "CF_TOKEN", "test-token")
        resp = _mock_response({"success": True, "result": {}})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.internet_traffic(location="DE", date_range="1d")
        params = client.get.call_args[1]["params"]
        assert params["location"] == "DE"
        assert params["dateRange"] == "1d"

    @pytest.mark.asyncio
    async def test_ripe_probes_params(self):
        resp = _mock_response({"count": 10, "results": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.ripe_probes(country="FR", status=2)
        params = client.get.call_args[1]["params"]
        assert params["country_code"] == "FR"
        assert params["status"] == 2

    @pytest.mark.asyncio
    async def test_ioda_outages_params(self):
        resp = _mock_response({"data": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.ioda_outages(entity_type="asn", entity_code="3320")
        params = client.get.call_args[1]["params"]
        assert params["entityType"] == "asn"
        assert params["entityCode"] == "3320"
        assert "from" in params
        assert "until" in params

    @pytest.mark.asyncio
    async def test_traffic_anomalies_missing_key(self, monkeypatch):
        monkeypatch.setattr(self.mod, "CF_TOKEN", "")
        result = await self.mod.traffic_anomalies(location="US")
        assert result["error"] == "CF_API_TOKEN not set"

    @pytest.mark.asyncio
    async def test_ripe_measurements_params(self):
        resp = _mock_response({"count": 5, "results": []})
        patcher, client = _patch_httpx_get(resp)
        with patcher:
            await self.mod.ripe_measurements(type="ping", country="DE")
        params = client.get.call_args[1]["params"]
        assert params["type"] == "ping"
        assert params["target_cc"] == "DE"


# ── Combined Server ─────────────────────────────


_ta_available = bool(importlib.util.find_spec("ta"))


@pytest.mark.skipif(not _ta_available, reason="ta library not installed")
class TestCombinedServer:
    """Verify combined_server.py mounts store + 12 domains with correct namespaces."""

    @pytest.fixture(autouse=True)
    def _import(self, monkeypatch):
        # Set all optional API keys so modules load cleanly
        for key in ("GOOGLE_API_KEY", "CF_API_TOKEN", "AISSTREAM_API_KEY",
                     "FRED_API_KEY", "EIA_API_KEY", "ACLED_API_KEY",
                     "COMTRADE_API_KEY", "USDA_NASS_API_KEY",
                     "IDMC_API_KEY", "MONGO_URI_SIGNALS"):
            monkeypatch.setenv(key, "test")
        # Clear cached modules to pick up env changes
        for mod_name in list(sys.modules):
            if mod_name.endswith("_server") or mod_name in ("combined_server", "server"):
                del sys.modules[mod_name]
        import combined_server
        self.mod = combined_server

    def test_combined_server_imports(self):
        assert self.mod.mcp is not None
        assert self.mod.mcp.name == "trading"

    @pytest.mark.asyncio
    async def test_combined_server_tool_count(self):
        tools = await self.mod.mcp.list_tools()
        assert len(tools) >= 50, f"Expected 50+ tools, got {len(tools)}: {[t.name for t in tools]}"

    @pytest.mark.asyncio
    async def test_combined_server_namespaces(self):
        tools = await self.mod.mcp.list_tools()
        tool_names = {t.name for t in tools}
        expected_prefixes = [
            "store_", "weather_", "disaster_", "econ_", "agri_", "conflict_",
            "commodity_", "health_", "politics_", "transport_",
            "water_", "humanitarian_", "infra_"
        ]
        for prefix in expected_prefixes:
            matching = [n for n in tool_names if n.startswith(prefix)]
            assert matching, f"No tools found with prefix '{prefix}'"

    @pytest.mark.asyncio
    async def test_combined_server_specific_tools(self):
        tools = await self.mod.mcp.list_tools()
        tool_names = {t.name for t in tools}
        must_have = [
            "store_get_profile", "store_snapshot", "store_chart",
            "store_save_note", "store_risk_status",
            "weather_forecast", "disaster_get_earthquakes", "econ_fred_series",
            "agri_fao_data", "conflict_acled_events", "commodity_trade_flows",
            "health_who_indicator", "politics_global_elections",
            "transport_flights_in_area",
            "water_streamflow", "water_drought",
            "humanitarian_unhcr_population", "humanitarian_hdx_search",
            "infra_internet_traffic", "infra_ioda_outages", "infra_ripe_probes"
        ]
        for name in must_have:
            assert name in tool_names, f"Missing tool: {name}"

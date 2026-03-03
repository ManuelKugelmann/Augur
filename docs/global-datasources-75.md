# 🌍 Global Data Source Stack — MCP + FastMCP Gap-Fillers

> **Uberspace-deployable.** No Docker, no browser, no root. All free APIs.
> Existing MCPs where available, FastMCP wrappers (~30-80 lines) for gaps.

---

## 🌾 AGRICULTURE & CROPS

### Existing MCPs
*None found for agriculture specifically.*

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 1 | **FAOSTAT** | `fenixservices.fao.org/faostat/api/v1/` | ❌ None | Global crop production, trade, prices, livestock, forestry. 245 countries, 1961-present. Domain codes: `QCL` (crops), `QV` (value), `TP` (trade), `PP` (prices) | ~60 |
| 2 | **USDA NASS** | `quickstats.nass.usda.gov/api/` | 🔑 Free | US crop production, progress, acreage, yield. Weekly crop progress reports | ~50 |
| 3 | **USDA FAS/PSD** | `apps.fas.usda.gov/OpenData/api/` | 🔑 Free | Foreign crop production/supply/demand (WASDE data). Global wheat/corn/soy/rice balance sheets | ~50 |
| 4 | **Agromonitoring** | `api.agromonitoring.com/agro/1.0/` | 🔑 Free (60 calls/min) | NDVI, EVI vegetation indices per polygon. Satellite imagery. Crop health monitoring | ~40 |
| 5 | **FAO GIEWS** | `www.fao.org/giews/food-prices/` | ❌ Scrape/RSS | Food price monitoring, crop forecasts. Early warning for food crises | ~40 |
| 6 | **AMIS** (FAO) | `app.amis-outlook.org/` | ❌ Scrape | Wheat/maize/rice/soybean market outlook. Supply & demand balances | ~30 |

```python
# FAOSTAT — ~60 lines
from fastmcp import FastMCP
import httpx

mcp = FastMCP("faostat", description="FAO global agriculture statistics")
BASE = "https://fenixservices.fao.org/faostat/api/v1/en"

@mcp.tool()
async def list_datasets() -> list:
    """List all FAOSTAT dataset codes (QCL=crops, TP=trade, PP=prices, etc.)"""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/definitions/domain")
        r.raise_for_status()
        return [{"code": d["code"], "label": d["label"]} for d in r.json()["data"]]

@mcp.tool()
async def get_data(domain: str = "QCL", area: str = "5000>",
                   item: str = "15", element: str = "5510",
                   year: str = "2020,2021,2022,2023") -> dict:
    """Get FAOSTAT data. domain: QCL(crops), QV(value), TP(trade), PP(prices).
    area: country M49 code or 5000>(world). item: crop code (15=wheat, 56=maize,
    27=rice, 236=soybean). element: 5510(production tonnes), 5312(area ha),
    5419(yield). year: comma-separated."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}/data/{domain}", params={
            "area": area, "item": item, "element": element, "year": year,
            "output_type": "objects"
        })
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def get_food_prices(area: str = "5000>", item: str = "15",
                          year: str = "2023") -> dict:
    """Get FAO food price indices and producer prices."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}/data/PP", params={
            "area": area, "item": item, "year": year,
            "output_type": "objects"
        })
        r.raise_for_status()
        return r.json()
```

---

## 🔥 FIRE & NATURAL DISASTERS

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 7 | **NASA FIRMS** | `firms.modaps.eosdis.nasa.gov/api/` | 🔑 Free | Active fire/hotspot detection. VIIRS + MODIS satellites. Global coverage, near real-time | ~35 |
| 8 | **USGS Earthquakes** | `earthquake.usgs.gov/fdsnws/event/1/` | ❌ None | Real-time earthquake catalog. GeoJSON. Magnitude, depth, tsunami flag, alert level | ~40 |
| 9 | **GDACS** | `www.gdacs.org/gdacsapi/api/events/` | ❌ None | Global Disaster Alert & Coordination. Earthquakes, floods, cyclones, volcanoes, droughts. Alert levels (green/orange/red) | ~35 |
| 10 | **ReliefWeb** | `api.reliefweb.int/v1/` | ❌ None | UN OCHA disaster reports, situation updates, maps. 800k+ humanitarian documents | ~40 |
| 11 | **Smithsonian GVP** | `volcano.si.edu/database/` | ❌ Scrape/RSS | Global Volcanism Program. Eruption history, weekly reports | ~30 |
| 12 | **EONET** (NASA) | `eonet.gsfc.nasa.gov/api/v3/events` | ❌ None | Earth Observatory Natural Event Tracker. Wildfires, severe storms, volcanoes, sea/lake ice | ~30 |

```python
# USGS Earthquakes — ~40 lines
from fastmcp import FastMCP
import httpx

mcp = FastMCP("usgs-earthquakes", description="Real-time global earthquake data")

@mcp.tool()
async def get_earthquakes(min_magnitude: float = 4.0, days: int = 7,
                          alert_level: str = "", limit: int = 100) -> dict:
    """Get recent earthquakes. alert_level: green/yellow/orange/red or empty for all."""
    from datetime import datetime, timedelta
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"format": "geojson", "starttime": start,
              "minmagnitude": min_magnitude, "limit": limit, "orderby": "time"}
    if alert_level: params["alertlevel"] = alert_level
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://earthquake.usgs.gov/fdsnws/event/1/query", params=params)
        r.raise_for_status()
        data = r.json()
        return {"count": data["metadata"]["count"],
                "earthquakes": [{"mag": f["properties"]["mag"],
                    "place": f["properties"]["place"],
                    "time": f["properties"]["time"],
                    "tsunami": f["properties"]["tsunami"],
                    "alert": f["properties"]["alert"],
                    "coords": f["geometry"]["coordinates"]}
                    for f in data["features"][:50]]}

@mcp.tool()
async def get_disasters(days: int = 30, status: str = "open") -> dict:
    """Get GDACS disaster alerts. status: open/closed."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
                        params={"eventlist": "", "fromDate": "",
                                "toDate": "", "alertlevel": ""})
        r.raise_for_status()
        return r.json()
```

```python
# NASA EONET — ~30 lines (wildfires, storms, volcanoes)
from fastmcp import FastMCP
import httpx

mcp = FastMCP("nasa-eonet", description="NASA Earth natural events tracker")

@mcp.tool()
async def get_events(category: str = "", days: int = 30,
                     status: str = "open", limit: int = 50) -> dict:
    """Get natural events. category: wildfires, severeStorms, volcanoes,
    seaLakeIce, earthquakes, floods, landslides, drought, dustHaze, snow,
    tempExtremes, waterColor. status: open/closed."""
    params = {"status": status, "limit": limit, "days": days}
    if category: params["category"] = category
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://eonet.gsfc.nasa.gov/api/v3/events", params=params)
        r.raise_for_status()
        return r.json()
```

---

## 🗳️ ELECTIONS & VOTING

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 13 | **IFES ElectionGuide** | `electionguide.org` | ❌ Scrape/RSS | Global election calendar, results, turnout. 1998-present | ~40 |
| 14 | **IDEA Voter Turnout** | `www.idea.int/data-tools/data/voter-turnout` | ❌ Scrape/bulk CSV | 171 countries turnout data since 1945 | ~30 |
| 15 | **V-Dem** | `v-dem.net/data_analysis/` | ❌ Bulk CSV | Varieties of Democracy. 470+ democracy indicators, 202 countries, 1789-present | ~40 |
| 16 | **Google Civic Info** | `www.googleapis.com/civicinfo/v2/` | 🔑 Free (Google API key) | US elections, representatives, polling locations | ~35 |
| 17 | **EU Parliament** | `data.europarl.europa.eu/api/v2/` | ❌ None | MEP data, votes, documents, committees | ~30 |
| 18 | **ParlGov** | `parlgov.org/data/` | ❌ Bulk CSV | Parties & elections in 37 democracies since 1945 | ~25 |

```python
# ReliefWeb API — also covers election-related crises
# IFES doesn't have a formal API, but RSS + scrape works
from fastmcp import FastMCP
import httpx

mcp = FastMCP("elections", description="Global elections and democracy data")

@mcp.tool()
async def search_reliefweb(query: str = "election", country: str = "",
                           limit: int = 20) -> dict:
    """Search ReliefWeb humanitarian reports (includes election monitoring)."""
    params = {"appname": "mcp", "limit": limit,
              "query[value]": query, "sort[]": "date:desc"}
    if country: params["filter[field]"] = f"country.name:{country}"
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.reliefweb.int/v1/reports", params=params)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def get_us_elections(address: str) -> dict:
    """Get US election info for an address (Google Civic Info API)."""
    import os
    async with httpx.AsyncClient() as c:
        r = await c.get("https://www.googleapis.com/civicinfo/v2/voterInfoQuery",
                        params={"key": os.environ["GOOGLE_API_KEY"], "address": address})
        r.raise_for_status()
        return r.json()
```

---

## 📊 MACRO INDICATORS & DEVELOPMENT

### Existing MCPs
| MCP | Coverage |
|-----|----------|
| **kylezarif/mcp** 🏆 | GDELT + SEC EDGAR + Treasury + World Bank + ECB + FHFA |

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 19 | **FRED** | `api.stlouisfed.org/fred/` | 🔑 Free | 800k+ US economic time series. GDP, CPI, unemployment, yield curve, M2, VIX | ~45 |
| 20 | **World Bank** | `api.worldbank.org/v2/` | ❌ None | 16k+ indicators, 217 countries. GDP, poverty, trade, health, education | ~45 |
| 21 | **IMF SDMX** | `dataservices.imf.org/REST/SDMX_JSON.svc/` | ❌ None | International Financial Statistics, Balance of Payments, WEO forecasts | ~40 |
| 22 | **ECB SDMX** | `data-api.ecb.europa.eu/service/data/` | ❌ None | Euro area monetary stats, exchange rates, interest rates, banking | ~35 |
| 23 | **BIS** | `data.bis.org/api/v2/` | ❌ None | Bank for International Settlements. Credit, property prices, derivatives, FX turnover | ~35 |
| 24 | **OECD** | `sdmx.oecd.org/public/rest/data/` | ❌ None | Leading indicators, GDP forecasts, trade, employment, prices | ~35 |
| 25 | **UN Stats** | `unstats.un.org/SDMXWS/rest/data/` | ❌ None | SDG indicators, national accounts, trade, demographics | ~35 |
| 26 | **Eurostat** | `ec.europa.eu/eurostat/api/dissemination/` | ❌ None | EU statistics on everything: economy, population, trade, transport, environment | ~40 |

```python
# World Bank — ~45 lines
from fastmcp import FastMCP
import httpx

mcp = FastMCP("worldbank", description="World Bank development indicators")

@mcp.tool()
async def get_indicator(indicator: str = "NY.GDP.MKTP.CD",
                        country: str = "all", date: str = "2020:2024",
                        per_page: int = 100) -> dict:
    """Get World Bank indicator data. Examples: NY.GDP.MKTP.CD (GDP),
    SI.POV.DDAY (poverty), SP.POP.TOTL (population), NY.GDP.PCAP.CD (GDP/capita),
    FP.CPI.TOTL.ZG (inflation), SL.UEM.TOTL.ZS (unemployment),
    MS.MIL.XPND.GD.ZS (military spending % GDP)."""
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
            params={"format": "json", "date": date, "per_page": per_page})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def search_indicators(query: str) -> dict:
    """Search World Bank indicators by keyword."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.worldbank.org/v2/indicator",
                        params={"format": "json", "qterm": query, "per_page": 50})
        r.raise_for_status()
        return r.json()

# IMF — ~40 lines
@mcp.tool()
async def get_imf_data(database: str = "IFS", frequency: str = "A",
                       ref_area: str = "US", indicator: str = "NGDP_R_XDC",
                       start: str = "2020", end: str = "2024") -> dict:
    """Get IMF data. database: IFS (Intl Financial Stats), BOP (Balance of Payments),
    DOT (Direction of Trade), WEO (World Economic Outlook).
    indicator examples: NGDP_R_XDC (real GDP), PCPI_IX (CPI), ENDA_XDC_USD_RATE (exchange)."""
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/{database}/{frequency}.{ref_area}.{indicator}",
            params={"startPeriod": start, "endPeriod": end})
        r.raise_for_status()
        return r.json()
```

---

## 🌧️ WEATHER & CLIMATE

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 27 | **Open-Meteo** | `api.open-meteo.com/v1/` | ❌ None | Free weather API. Forecast 16d, historical since 1940, air quality, marine, flood, climate projections. No key needed! | ~50 |
| 28 | **NOAA CDO** | `www.ncdc.noaa.gov/cdo-web/api/v2/` | 🔑 Free | US climate data. Daily/monthly observations. Temperature, precipitation, drought | ~40 |
| 29 | **NOAA SWPC** | `services.swpc.noaa.gov/json/` | ❌ None | Space weather! Solar flares, geomagnetic storms, Kp index. Affects satellites, GPS, power grids | ~35 |
| 30 | **Copernicus CDS** | `cds.climate.copernicus.eu/api/` | 🔑 Free | ERA5 reanalysis, climate projections, satellite data. Massive but slow | ~40 |
| 31 | **US Drought Monitor** | `droughtmonitor.unl.edu/` | ❌ GeoJSON/CSV | Weekly drought conditions by county/state. D0-D4 severity. Direct agricultural/commodity impact | ~30 |

```python
# Open-Meteo — ~50 lines, ZERO auth needed
from fastmcp import FastMCP
import httpx

mcp = FastMCP("weather", description="Global weather, climate, and space weather")

@mcp.tool()
async def forecast(lat: float, lon: float, days: int = 7) -> dict:
    """Weather forecast. Returns hourly temp, precip, wind, humidity."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "forecast_days": days,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
            "timezone": "auto"})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def historical_weather(lat: float, lon: float,
                              start: str = "2024-01-01",
                              end: str = "2024-12-31") -> dict:
    """Historical weather data since 1940. Daily resolution."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://archive-api.open-meteo.com/v1/archive", params={
            "latitude": lat, "longitude": lon,
            "start_date": start, "end_date": end,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto"})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def flood_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """River discharge forecast (flood risk)."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://flood-api.open-meteo.com/v1/flood", params={
            "latitude": lat, "longitude": lon, "forecast_days": days,
            "daily": "river_discharge"})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def space_weather() -> dict:
    """Current space weather: Kp index, solar wind, geomagnetic storms."""
    async with httpx.AsyncClient() as c:
        kp = await c.get("https://services.swpc.noaa.gov/json/planetary_k_index_1m.json")
        solar = await c.get("https://services.swpc.noaa.gov/json/solar_wind/plasma-7-day.json")
        alerts = await c.get("https://services.swpc.noaa.gov/json/alerts.json")
        return {
            "kp_index": kp.json()[-5:] if kp.status_code == 200 else [],
            "solar_wind": solar.json()[-5:] if solar.status_code == 200 else [],
            "alerts": alerts.json()[:10] if alerts.status_code == 200 else []
        }
```

---

## ⛏️ RAW MATERIALS & COMMODITIES

### Existing MCPs
| MCP | Coverage |
|-----|----------|
| **yahoo-finance-mcp** | Commodity futures via Yahoo Finance symbols (GC=F gold, CL=F oil, etc.) |

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 32 | **UN Comtrade** | `comtradeapi.un.org/data/v1/get/` | 🔑 Free | International trade flows. HS codes. Import/export by commodity/country pair. Monthly + annual | ~50 |
| 33 | **USGS Minerals** | `minerals.usgs.gov/` | ❌ Bulk CSV | Mineral commodity summaries. Rare earths, lithium, cobalt, copper, nickel. Strategic reserves | ~35 |
| 34 | **EIA** (US Energy) | `api.eia.gov/v2/` | 🔑 Free | Oil production/stocks/imports, natural gas, electricity, coal, renewables. US + international | ~45 |
| 35 | **Commodities-API** | `commodities-api.com/api/` | 🔑 Free (250/mo) | Real-time spot prices: gold, silver, oil, copper, wheat, corn, coffee. 60+ commodities | ~30 |
| 36 | **World Bank Pink Sheet** | `api.worldbank.org/v2/` | ❌ None | Monthly commodity price data. ~70 commodities back to 1960 | ~30 |

```python
# UN Comtrade — ~50 lines
from fastmcp import FastMCP
import httpx, os

mcp = FastMCP("comtrade", description="UN international trade data")
KEY = os.environ.get("COMTRADE_API_KEY", "")

@mcp.tool()
async def get_trade(reporter: str = "842", partner: str = "0",
                    commodity: str = "TOTAL", flow: str = "M",
                    period: str = "2023", frequency: str = "A") -> dict:
    """Get trade flows. reporter/partner: M49 codes (842=USA, 156=China, 276=Germany, 0=World).
    commodity: HS code or TOTAL. flow: M(import), X(export). frequency: A(annual), M(monthly)."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://comtradeapi.un.org/data/v1/get/C/A/HS", params={
            "reporterCode": reporter, "partnerCode": partner,
            "cmdCode": commodity, "flowCode": flow, "period": period,
            "subscription-key": KEY})
        r.raise_for_status()
        return r.json()

# EIA Energy — ~45 lines
@mcp.tool()
async def get_energy(series: str = "PET.RWTC.D",
                     start: str = "2024-01", frequency: str = "monthly") -> dict:
    """Get EIA energy data. series examples:
    PET.RWTC.D (WTI crude daily), PET.RBRTE.D (Brent daily),
    NG.RNGWHHD.D (Henry Hub natgas), ELEC.GEN.ALL-US-99.M (US electricity),
    PET.WCRSTUS1.W (US crude oil stocks), INTL.57-1-AFRC-TBPD.A (Africa oil production)."""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"https://api.eia.gov/v2/seriesid/{series}",
                        params={"api_key": os.environ["EIA_API_KEY"],
                                "start": start, "frequency": frequency})
        r.raise_for_status()
        return r.json()
```

---

## ⚔️ MILITARY & DEFENSE

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 37 | **SIPRI Arms Transfers** | `armstransfers.sipri.org/` | ❌ CSV export | Arms trade since 1950. Supplier→recipient, weapon type, TIV values | ~45 |
| 38 | **SIPRI Military Expenditure** | Via World Bank API | ❌ None | Military spending by country (% GDP, absolute). Indicator: `MS.MIL.XPND.GD.ZS` | ~20 |
| 39 | **UCDP** | `ucdpapi.pcr.uu.se/api/` | ❌ None | Uppsala Conflict Data. Armed conflicts, battle deaths, georeferenced events 1946-2024 | ~45 |
| 40 | **ACLED** | `api.acleddata.com/` | 🔑 Free | Armed Conflict Location & Event Data. Battles, protests, riots, violence. Real-time. 200+ countries | ~40 |
| 41 | **GlobalFirepower** | Web scrape | ❌ None | Military strength rankings. 145 countries. Personnel, equipment, budget | ~30 |
| 42 | **OpenSanctions** | `api.opensanctions.org/` | ❌ None (self-host for bulk) | Sanctions lists (OFAC, EU, UN, UK). PEPs. 500k+ entities | ~35 |
| 43 | **OFAC SDN** | `sanctionslist.ofac.treas.gov/` | ❌ XML/JSON download | US Treasury sanctioned entities. Updated frequently | ~30 |

```python
# UCDP Conflict Data — ~45 lines
from fastmcp import FastMCP
import httpx

mcp = FastMCP("conflict", description="Armed conflict, military, and sanctions data")

@mcp.tool()
async def get_conflicts(year: int = 2024, page: int = 1) -> dict:
    """Get UCDP armed conflicts by year."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://ucdpapi.pcr.uu.se/api/gedevents/24.1",
                        params={"pagesize": 100, "page": page, "Year": year})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def get_battle_deaths(conflict_id: int = 0, year: int = 2024) -> dict:
    """Get battle-related deaths from UCDP."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://ucdpapi.pcr.uu.se/api/battledeaths/24.1",
                        params={"pagesize": 100, "Year": year})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def search_sanctions(query: str, schema: str = "") -> dict:
    """Search OpenSanctions for sanctioned entities/persons.
    schema: Person, Company, Vessel, Aircraft, Organization."""
    params = {"q": query, "limit": 20}
    if schema: params["schema"] = schema
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.opensanctions.org/search/default", params=params)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def get_sipri_military_spending(country: str = "all",
                                       date: str = "2015:2024") -> dict:
    """Military expenditure (% GDP) via World Bank. Uses SIPRI data."""
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"https://api.worldbank.org/v2/country/{country}/indicator/MS.MIL.XPND.GD.ZS",
            params={"format": "json", "date": date, "per_page": 300})
        r.raise_for_status()
        return r.json()
```

---

## 🏥 MEDICAL & HEALTH

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 44 | **WHO GHO** | `ghoapi.azureedge.net/api/` | ❌ None | WHO Global Health Observatory. 2000+ indicators: mortality, disease burden, health systems, risk factors | ~45 |
| 45 | **WHO Disease Outbreaks** | `www.who.int/api/news/diseaseoutbreaknews` | ❌ None | Disease outbreak reports. Epidemiology, assessment, response | ~30 |
| 46 | **disease.sh** | `disease.sh/v3/` | ❌ None | COVID-19 + Influenza real-time tracking. Global/country/state. Historical. Vaccine data | ~35 |
| 47 | **CDC WONDER** | `wonder.cdc.gov/` | ❌ XML API | US mortality, cancer, births, STDs, environmental health. 50+ datasets | ~40 |
| 48 | **OpenFDA** | `api.fda.gov/` | ❌ None (1k/day, 120k with key) | Drug adverse events, recalls, labeling. Device reports. Food enforcement | ~40 |
| 49 | **PubMed/NCBI** | `eutils.ncbi.nlm.nih.gov/entrez/eutils/` | 🔑 Free (10/sec) | 36M+ biomedical articles. Clinical trials. Gene/protein data | ~40 |
| 50 | **GISAID** / **NCBI Virus** | `www.ncbi.nlm.nih.gov/datasets/docs/v2/` | ❌ / 🔑 | Pathogen genomic sequences. Influenza, SARS-CoV-2, RSV surveillance | ~35 |
| 51 | **HealthData.gov** | `healthdata.gov/` | ❌ Socrata API | US health datasets. Hospital capacity, Medicare, health surveys | ~30 |
| 52 | **IPC** (Famine) | `www.ipcinfo.org/` | ❌ Scrape/API | Integrated Food Security Phase Classification. Famine early warning. Phase 1-5 | ~35 |

```python
# WHO + disease.sh — ~60 lines combined
from fastmcp import FastMCP
import httpx

mcp = FastMCP("health", description="Global health, disease outbreaks, FDA, famine data")

@mcp.tool()
async def who_indicator(indicator: str = "NCDMORT3070",
                        country: str = "", year: str = "") -> dict:
    """Get WHO health indicator. Examples: NCDMORT3070 (NCD mortality),
    WHOSIS_000001 (life expectancy), MDG_0000000001 (under-5 mortality),
    WHS4_100 (hospital beds), NCD_BMI_30A (obesity), SA_0000001688 (alcohol).
    See https://ghoapi.azureedge.net/api/Indicator for full list."""
    url = f"https://ghoapi.azureedge.net/api/{indicator}"
    params = {}
    filters = []
    if country: filters.append(f"SpatialDim eq '{country}'")
    if year: filters.append(f"TimeDim eq {year}")
    if filters: params["$filter"] = " and ".join(filters)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def disease_outbreaks(limit: int = 20) -> dict:
    """Get latest WHO Disease Outbreak News."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://www.who.int/api/news/diseaseoutbreaknews",
                        params={"sf_culture": "en", "$top": limit,
                                "$orderby": "PublicationDate desc"})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def disease_tracker(disease: str = "covid",
                          country: str = "") -> dict:
    """Real-time disease tracking (disease.sh). disease: covid/influenza."""
    async with httpx.AsyncClient() as c:
        if disease == "covid":
            url = f"https://disease.sh/v3/covid-19/{'countries/' + country if country else 'all'}"
        else:
            url = f"https://disease.sh/v3/influenza/{'ihsa/country/' + country if country else 'ihsa'}"
        r = await c.get(url)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def fda_adverse_events(drug: str = "", limit: int = 20) -> dict:
    """Search FDA adverse drug event reports."""
    search = f'patient.drug.medicinalproduct:"{drug}"' if drug else ""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.fda.gov/drug/event.json",
                        params={"search": search, "limit": limit})
        r.raise_for_status()
        return r.json()
```

---

## 🚢 SHIPPING & TRADE ROUTES

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 53 | **AIS Stream** | `stream.aisstream.io/` | 🔑 Free | Real-time vessel positions. Chokepoint monitoring (Suez, Hormuz, Panama, Malacca) | ~50 |
| 54 | **MarineTraffic** | Paid API | 💰 | AIS data, port calls, vessel details. Alternative: AIS Stream for free tier | — |
| 55 | **UN Comtrade** | (See #32 above) | 🔑 Free | Bilateral trade flows → shipping demand proxy | — |
| 56 | **Suez Canal** | Web scrape / RSS | ❌ | Transit data via news monitoring | ~25 |
| 57 | **Port of Rotterdam** | `portofrotterdam.com/en/api` | ❌ | Europe's largest port. Throughput data | ~25 |

---

## ✈️ AVIATION & FLIGHTS

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 58 | **OpenSky Network** | `opensky-network.org/api/` | ❌ None (rate limit) | Live aircraft positions. ICAO24 lookup. Flight history. Military tracking | ~40 |
| 59 | **AviationStack** | `aviationstack.com/` | 🔑 Free (100/mo) | Flight status, airports, airlines, routes | ~30 |
| 60 | **ADS-B Exchange** | `rapidapi.com` | 🔑 (RapidAPI) | Unfiltered ADS-B data (includes military). More complete than OpenSky | ~30 |

---

## 🌊 WATER & DROUGHT

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 61 | **USGS Water** | `waterservices.usgs.gov/nwis/` | ❌ None | US river levels, streamflow, groundwater. 1.5M+ sites. Real-time | ~40 |
| 62 | **US Drought Monitor** | `droughtmonitor.unl.edu/WebServiceInfo.aspx` | ❌ None | Weekly US drought map. D0-D4 severity. County-level GeoJSON | ~30 |
| 63 | **Global Flood Monitor** | `globalfloods.eu/` | ❌ None | Copernicus Emergency Management. Global flood alerts | ~25 |
| 64 | **Open-Meteo Flood** | (See #27 above) | ❌ None | River discharge forecast. Free. No key | — |

```python
# USGS Water Services — ~40 lines
from fastmcp import FastMCP
import httpx

mcp = FastMCP("water", description="US water levels, drought, flood monitoring")

@mcp.tool()
async def get_streamflow(site: str = "", state: str = "CA",
                         period: str = "P7D") -> dict:
    """Get USGS real-time streamflow. site: USGS site number or empty for state.
    period: P1D (1 day), P7D (7 days), P30D (30 days)."""
    params = {"format": "json", "period": period, "parameterCd": "00060"}
    if site: params["sites"] = site
    elif state: params["stateCd"] = state
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://waterservices.usgs.gov/nwis/iv", params=params)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def get_drought(area_type: str = "state", area: str = "CA") -> dict:
    """Get US Drought Monitor data. area_type: state/county/national."""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"https://usdm.unl.edu/DmData/TimeSeries.aspx",
                        params={"area_type": area_type, "area": area, "format": "json"})
        r.raise_for_status()
        return r.json()
```

---

## 🧬 NUCLEAR & ENERGY INFRASTRUCTURE

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 65 | **IAEA PRIS** | `pris.iaea.org/PRIS/` | ❌ Scrape | Power Reactor Information. 440+ operating reactors. Status, capacity, outages | ~40 |
| 66 | **NRC** (US) | `nrc.gov/reading-rm/doc-collections/event-status/reactor-status/` | ❌ CSV | US reactor status. Daily power output. Outage tracking | ~30 |
| 67 | **EIA Nuclear** | (See #34 above) | 🔑 Free | US nuclear generation, capacity factors, outages | — |

---

## 👥 REFUGEES & HUMANITARIAN

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 68 | **UNHCR** | `api.unhcr.org/population/v1/` | ❌ None | Refugee populations, asylum seekers, IDPs. By country of origin/asylum | ~40 |
| 69 | **IOM DTM** | `dtm.iom.int/data-and-analysis` | ❌ Bulk | Displacement Tracking Matrix. Migration flows, mobility tracking | ~30 |
| 70 | **OCHA HDX** | `data.humdata.org/api/3/` | ❌ None (CKAN API) | Humanitarian Data Exchange. 20k+ datasets. Crisis data, needs assessments | ~35 |
| 71 | **WFP HungerMap** | `hungermap.wfp.org/` | ❌ JSON endpoints | Real-time food security. 90+ countries. Market prices, conflict proximity | ~30 |

```python
# UNHCR + HDX — ~45 lines
from fastmcp import FastMCP
import httpx

mcp = FastMCP("humanitarian", description="Refugee, displacement, and humanitarian data")

@mcp.tool()
async def unhcr_population(year: int = 2024, country_origin: str = "",
                            country_asylum: str = "") -> dict:
    """Get UNHCR refugee population data."""
    params = {"year": year, "limit": 100}
    if country_origin: params["coo"] = country_origin  # ISO3
    if country_asylum: params["coa"] = country_asylum
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.unhcr.org/population/v1/population/",
                        params=params)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def hdx_search(query: str, rows: int = 20) -> dict:
    """Search Humanitarian Data Exchange datasets."""
    async with httpx.AsyncClient() as c:
        r = await c.get("https://data.humdata.org/api/3/action/package_search",
                        params={"q": query, "rows": rows})
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def reliefweb_reports(query: str = "", country: str = "",
                             limit: int = 20) -> dict:
    """Search ReliefWeb humanitarian reports and situation updates."""
    body = {"limit": limit, "sort": ["date:desc"]}
    if query: body["query"] = {"value": query}
    async with httpx.AsyncClient() as c:
        r = await c.post("https://api.reliefweb.int/v1/reports",
                         json=body, params={"appname": "mcp"})
        r.raise_for_status()
        return r.json()
```

---

## 🌐 INTERNET & INFRASTRUCTURE

### FastMCP Gap-Fillers

| # | Source | API Base | Auth | Signal | Lines |
|---|--------|----------|------|--------|-------|
| 72 | **Cloudflare Radar** | `api.cloudflare.com/client/v4/radar/` | 🔑 Free | Internet traffic, DDoS attacks, BGP route leaks, outages by country. HTTP protocols, bot traffic | ~40 |
| 73 | **RIPE Atlas** | `atlas.ripe.net/api/v2/` | ❌ None | Internet measurement network. Latency, DNS, traceroute from 12k+ probes worldwide | ~35 |
| 74 | **Internet Outages** (Kentik) | Blog/RSS | ❌ | BGP hijacks, submarine cable cuts | ~20 |
| 75 | **Submarine Cable Map** | `submarinecablemap.com/api/` | ❌ None | Global submarine cable data. Landing points, cable specs | ~25 |

---

## 📦 COMPLETE DOMAIN COVERAGE MAP

```
┌────────────────────────────────────────────────────────────────┐
│                GLOBAL DATA SOURCE COVERAGE                      │
│                                                                  │
│  🌾 AGRICULTURE (6)    🔥 DISASTERS (6)    🗳️ ELECTIONS (6)     │
│   FAOSTAT              NASA FIRMS           IFES ElectionGuide  │
│   USDA NASS/FAS        USGS Earthquakes     IDEA Voter Turnout  │
│   Agromonitoring       GDACS                V-Dem Democracy     │
│   FAO GIEWS/AMIS       ReliefWeb            Google Civic        │
│                        Smithsonian GVP      EU Parliament       │
│                        NASA EONET           ParlGov             │
│                                                                  │
│  📊 MACRO (8)          🌧️ WEATHER (5)      ⛏️ COMMODITIES (5)  │
│   FRED                 Open-Meteo ⭐        UN Comtrade         │
│   World Bank           NOAA CDO             USGS Minerals       │
│   IMF                  NOAA SWPC (space)    EIA Energy          │
│   ECB                  Copernicus CDS       Commodities-API     │
│   BIS                  US Drought           WB Pink Sheet       │
│   OECD                                                          │
│   UN Stats                                                      │
│   Eurostat                                                      │
│                                                                  │
│  ⚔️ MILITARY (7)      🏥 MEDICAL (9)       🚢 SHIPPING (3)    │
│   SIPRI Arms           WHO GHO              AIS Stream          │
│   SIPRI MilEx          WHO Outbreaks        UN Comtrade         │
│   UCDP Conflict        disease.sh           Port data           │
│   ACLED                CDC WONDER                               │
│   GlobalFirepower      OpenFDA              ✈️ AVIATION (3)     │
│   OpenSanctions        PubMed               OpenSky             │
│   OFAC SDN             IPC Famine           AviationStack       │
│                        HealthData.gov       ADS-B Exchange      │
│                        NCBI Virus                               │
│                                                                  │
│  🌊 WATER (4)          👥 HUMANITARIAN (4)  🧬 NUCLEAR (3)     │
│   USGS Water           UNHCR                IAEA PRIS           │
│   US Drought           IOM DTM              NRC Reactor Status  │
│   Global Floods        OCHA HDX             EIA Nuclear         │
│   Open-Meteo Flood     WFP HungerMap                            │
│                                                                  │
│  🌐 INTERNET (4)       + EXISTING MCPs from previous catalog    │
│   Cloudflare Radar     📈 Prediction markets                    │
│   RIPE Atlas           💹 Stock/Financial                       │
│   Submarine Cables     😱 Crypto sentiment                      │
│   Internet Outages     📄 Academic research                     │
│                        📡 RSS monitoring                        │
│                        🔴 Social media (Reddit, X, HN)          │
│                        📢 Social publishing                     │
│                        🧮 Math/Statistics                       │
│                        📜 Patents                               │
│                        💼 Job boards                            │
└────────────────────────────────────────────────────────────────┘
```

---

## 🔑 API KEYS MASTER LIST

| # | Service | Free? | Rate Limit | Env Var |
|---|---------|-------|-----------|---------|
| — | FAOSTAT | ✅ No key | Generous | — |
| — | USDA NASS | ✅ Free key | 50k/day | `USDA_NASS_API_KEY` |
| — | USDA FAS | ✅ Free key | — | `USDA_FAS_API_KEY` |
| — | Agromonitoring | ✅ Free key | 60/min | `AGRO_API_KEY` |
| — | NASA FIRMS | ✅ Free key | — | `NASA_FIRMS_API_KEY` |
| — | USGS Earthquakes | ✅ No key | — | — |
| — | GDACS | ✅ No key | — | — |
| — | ReliefWeb | ✅ No key | — | — |
| — | NASA EONET | ✅ No key | — | — |
| — | Google Civic | ✅ Free key | 25k/day | `GOOGLE_API_KEY` |
| — | FRED | ✅ Free key | 120/min | `FRED_API_KEY` |
| — | World Bank | ✅ No key | — | — |
| — | IMF | ✅ No key | — | — |
| — | ECB | ✅ No key | — | — |
| — | Open-Meteo | ✅ No key ⭐ | 10k/day | — |
| — | NOAA CDO | ✅ Free token | 5/sec | `NOAA_CDO_TOKEN` |
| — | NOAA SWPC | ✅ No key | — | — |
| — | UN Comtrade | ✅ Free key | 100/hr guest | `COMTRADE_API_KEY` |
| — | EIA | ✅ Free key | — | `EIA_API_KEY` |
| — | UCDP | ✅ No key | — | — |
| — | ACLED | ✅ Free (register) | — | `ACLED_API_KEY` + `ACLED_EMAIL` |
| — | OpenSanctions | ✅ No key (API) | 10/min public | — |
| — | WHO GHO | ✅ No key | — | — |
| — | WHO Outbreaks | ✅ No key | — | — |
| — | disease.sh | ✅ No key | — | — |
| — | OpenFDA | ✅ No key (1k/day) | 120k with key | `OPENFDA_API_KEY` |
| — | UNHCR | ✅ No key | — | — |
| — | OCHA HDX | ✅ No key | — | — |
| — | OpenSky | ✅ No key (limited) | 10/min anon | — |
| — | AIS Stream | ✅ Free key | — | `AISSTREAM_API_KEY` |
| — | USGS Water | ✅ No key | — | — |
| — | Cloudflare Radar | ✅ Free key | — | `CF_API_TOKEN` |
| — | RIPE Atlas | ✅ No key (read) | — | — |

**28 sources need NO key at all. 15 need a free key. 0 paid.**

---

## 📐 FASTMCP LINE COUNT ESTIMATE

| Domain | Sources | Total Lines | Shared server.py? |
|--------|---------|-------------|-------------------|
| Agriculture | 4 main | ~200 | `agri-server.py` |
| Disasters | 4 main | ~150 | `disasters-server.py` |
| Elections | 2 main | ~80 | `elections-server.py` |
| Macro | 4 main | ~170 | `macro-server.py` |
| Weather | 4 tools | ~150 | `weather-server.py` |
| Commodities | 3 main | ~130 | `commodities-server.py` |
| Military | 4 tools | ~160 | `conflict-server.py` |
| Medical | 4 tools | ~160 | `health-server.py` |
| Shipping/Aviation | 2 main | ~80 | `transport-server.py` |
| Water | 2 main | ~70 | `water-server.py` |
| Humanitarian | 3 tools | ~120 | `humanitarian-server.py` |
| Internet | 2 main | ~70 | `infra-server.py` |
| **TOTAL** | **~38 tools** | **~1,540 lines** | **12 files** |

~130 lines per domain average. All pure Python, `httpx` + `fastmcp` only.

---

*Generated 2026-02-28. 75+ data sources. All free. All Uberspace-compatible.*

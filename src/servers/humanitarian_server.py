"""Humanitarian — UNHCR refugees, OCHA HDX, ReliefWeb, IDMC displacement."""
from fastmcp import FastMCP
import httpx
import os
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("humanitarian", instructions="Refugees, displacement, humanitarian data, crisis reports")
IDMC_KEY = os.environ.get("IDMC_API_KEY", "")

_RW_HEADERS = {
    "User-Agent": "TradingAssistant/1.0 (https://github.com/ManuelKugelmann/TradingAssistant)",
}
_RW_APPNAME = {"appname": "TradingAssistant"}


@mcp.tool()
async def unhcr_population(year: int = 2024, country_origin: str = "",
                            country_asylum: str = "") -> dict:
    """UNHCR refugee population statistics. Countries as ISO3 (e.g. SYR, TUR).
    Returns refugees, asylum seekers, IDPs, stateless persons."""
    params: dict = {"year": year, "limit": 100}
    if country_origin:
        params["coo"] = country_origin
    if country_asylum:
        params["coa"] = country_asylum
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.unhcr.org/population/v1/population/",
                            params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"UNHCR API request failed: {e}"}


@mcp.tool()
async def unhcr_demographics(year: int = 2024, country_asylum: str = "") -> dict:
    """UNHCR demographics (age, sex breakdown). country_asylum: ISO3."""
    params: dict = {"year": year, "limit": 100}
    if country_asylum:
        params["coa"] = country_asylum
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.unhcr.org/population/v1/demographics/",
                            params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"UNHCR demographics request failed: {e}"}


@mcp.tool()
async def hdx_search(query: str, rows: int = 20) -> dict:
    """Search OCHA Humanitarian Data Exchange datasets.
    Returns dataset metadata with download links."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://data.humdata.org/api/3/action/package_search",
                            params={"q": query, "rows": rows})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"HDX search request failed: {e}"}


@mcp.tool()
async def hdx_dataset(dataset_id: str) -> dict:
    """Get details of an HDX dataset by ID or name. Returns resources (files)
    with download URLs, formats, and metadata."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://data.humdata.org/api/3/action/package_show",
                            params={"id": dataset_id})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"HDX dataset request failed: {e}"}


@mcp.tool()
async def reliefweb_reports(query: str = "", country: str = "",
                             disaster: str = "", limit: int = 20) -> dict:
    """ReliefWeb humanitarian reports and situation updates.
    Filter by country name or disaster name."""
    body: dict = {"limit": limit, "sort": ["date:desc"],
                  "fields": {"include": ["title", "date.original", "source",
                             "country", "disaster", "url_alias"]}}
    if query:
        body["query"] = {"value": query}
    filters = []
    if country:
        filters.append({"field": "country.name", "value": [country]})
    if disaster:
        filters.append({"field": "disaster.name", "value": [disaster]})
    if len(filters) == 1:
        body["filter"] = filters[0]
    elif len(filters) > 1:
        body["filter"] = {"operator": "AND", "conditions": filters}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.reliefweb.int/v2/reports",
                             json=body, params=_RW_APPNAME,
                             headers=_RW_HEADERS)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"ReliefWeb reports request failed: {e}"}


@mcp.tool()
async def reliefweb_disasters(country: str = "", status: str = "ongoing",
                                limit: int = 20) -> dict:
    """ReliefWeb active disasters. status: ongoing, past, alert."""
    body: dict = {"limit": limit, "sort": ["date.event:desc"],
                  "fields": {"include": ["name", "date", "status", "country",
                             "type", "glide", "url_alias"]}}
    filters = []
    if status:
        filters.append({"field": "status", "value": [status]})
    if country:
        filters.append({"field": "country.name", "value": [country]})
    if len(filters) == 1:
        body["filter"] = filters[0]
    elif len(filters) > 1:
        body["filter"] = {"operator": "AND", "conditions": filters}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.reliefweb.int/v2/disasters",
                             json=body, params=_RW_APPNAME,
                             headers=_RW_HEADERS)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"ReliefWeb disasters request failed: {e}"}


@mcp.tool()
async def idmc_displacement(iso3: str = "", start_year: int = 0,
                             end_year: int = 0) -> dict:
    """IDMC internal displacement data (GIDD). iso3: country code (e.g. SYR).
    Returns conflict and disaster displacement figures by year.
    Requires IDMC_API_KEY env var."""
    if not IDMC_KEY:
        return {"error": "IDMC_API_KEY not set — request key from IDMC"}
    params: dict = {"client_id": IDMC_KEY,
                    "release_environment": "RELEASE"}
    if iso3:
        params["iso3__in"] = iso3
    if start_year:
        params["start_year"] = start_year
    if end_year:
        params["end_year"] = end_year
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://helix-tools-api.idmcdb.org/external-api/gidd/displacements/displacement-export/",
                params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"IDMC displacement request failed: {e}"}


@mcp.tool()
async def idmc_disasters(iso3: str = "", start_year: int = 0,
                          end_year: int = 0) -> dict:
    """IDMC disaster displacement events. iso3: country code.
    Requires IDMC_API_KEY env var."""
    if not IDMC_KEY:
        return {"error": "IDMC_API_KEY not set — request key from IDMC"}
    params: dict = {"client_id": IDMC_KEY,
                    "release_environment": "RELEASE"}
    if iso3:
        params["iso3__in"] = iso3
    if start_year:
        params["start_year"] = start_year
    if end_year:
        params["end_year"] = end_year
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://helix-tools-api.idmcdb.org/external-api/gidd/disasters/disaster-export/",
                params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"IDMC disasters request failed: {e}"}


# ── Aggregation ──────────────────────────────────────────


@mcp.tool()
async def humanitarian_crisis(country: str = "", iso3: str = "") -> dict:
    """Humanitarian overview for a country. Combines UNHCR refugee data,
    ReliefWeb reports, and active disasters. country: full name, iso3: code."""
    results: dict = {}
    if iso3:
        try:
            results["refugees"] = await unhcr_population(country_asylum=iso3)
        except Exception as e:
            results["refugees"] = {"error": str(e)}
    name = country or iso3
    if name:
        try:
            results["disasters"] = await reliefweb_disasters(
                country=country, limit=10)
        except Exception as e:
            results["disasters"] = {"error": str(e)}
        try:
            results["reports"] = await reliefweb_reports(
                country=country, limit=10)
        except Exception as e:
            results["reports"] = {"error": str(e)}
    results["_meta"] = {"country": country, "iso3": iso3,
                        "sources": ["UNHCR", "ReliefWeb"]}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

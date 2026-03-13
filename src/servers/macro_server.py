"""Macro — FRED, World Bank, IMF SDMX."""
from fastmcp import FastMCP
from _http import api_get
import httpx
import os
import logging
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("augur.macro")

mcp = FastMCP("macro", instructions="Macroeconomic indicators: FRED, World Bank, IMF")
FRED_KEY = os.environ.get("FRED_API_KEY", "")


@mcp.tool()
async def fred_series(series_id: str, limit: int = 100,
                      sort_order: str = "desc") -> dict:
    """FRED time series. Examples: GDP, UNRATE, CPIAUCSL, DFF (fed funds),
    T10Y2Y (yield curve), M2SL (money supply), VIXCLS, ICSA (jobless claims)."""
    if not FRED_KEY:
        return {"error": "FRED_API_KEY not set"}
    return await api_get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": FRED_KEY,
                "file_type": "json", "limit": limit, "sort_order": sort_order},
        label="FRED")


@mcp.tool()
async def fred_search(query: str, limit: int = 20) -> dict:
    """Search FRED for economic data series."""
    if not FRED_KEY:
        return {"error": "FRED_API_KEY not set"}
    return await api_get(
        "https://api.stlouisfed.org/fred/series/search",
        params={"search_text": query, "api_key": FRED_KEY,
                "file_type": "json", "limit": limit},
        label="FRED search")


@mcp.tool()
async def worldbank_indicator(indicator: str = "NY.GDP.MKTP.CD",
                               country: str = "all", date: str = "2020:2024",
                               per_page: int = 100) -> dict:
    """World Bank indicator. Examples: NY.GDP.MKTP.CD (GDP), SP.POP.TOTL (population),
    FP.CPI.TOTL.ZG (inflation), SL.UEM.TOTL.ZS (unemployment),
    MS.MIL.XPND.GD.ZS (military spending % GDP)."""
    return await api_get(
        f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
        params={"format": "json", "date": date, "per_page": per_page},
        label="World Bank")


@mcp.tool()
async def worldbank_search(query: str) -> dict:
    """Search World Bank indicators by keyword."""
    return await api_get("https://api.worldbank.org/v2/indicator",
                         params={"format": "json", "qterm": query, "per_page": 50},
                         label="World Bank search")


@mcp.tool()
async def imf_data(database: str = "IFS", frequency: str = "A",
                    ref_area: str = "US", indicator: str = "NGDP_R_XDC",
                    start: str = "2020", end: str = "2024") -> dict:
    """IMF data. database: IFS/BOP/DOT/WEO. indicator: NGDP_R_XDC, PCPI_IX, ENDA_XDC_USD_RATE.
    Tries SDMX Central first, falls back to legacy SDMX endpoint."""
    sdmx_urls = [
        f"https://sdmxcentral.imf.org/ws/public/sdmxapi/rest/data/"
        f"{database}/{frequency}.{ref_area}.{indicator}",
        f"https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/"
        f"{database}/{frequency}.{ref_area}.{indicator}",
    ]
    params = {"startPeriod": start, "endPeriod": end}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            for url in sdmx_urls:
                try:
                    r = await c.get(url, params=params,
                                    headers={"Accept": "application/json"})
                    r.raise_for_status()
                    return r.json()
                except httpx.HTTPError:
                    continue
            return {"error": f"IMF SDMX endpoints unavailable for {database}/{indicator}"}
    except httpx.HTTPError as e:
        return {"error": f"IMF SDMX request failed: {e}"}


# ── Provider-agnostic routing ──────────────────────────

_INDICATOR_MAP: dict[str, dict[str, str]] = {
    "gdp":            {"fred": "GDP",       "wb": "NY.GDP.MKTP.CD",   "imf": "NGDP_R_XDC"},
    "gdp_growth":     {"fred": "A191RL1Q225SBEA", "wb": "NY.GDP.MKTP.KD.ZG"},
    "gdp_per_capita": {"wb": "NY.GDP.PCAP.CD"},
    "inflation":      {"fred": "CPIAUCSL",  "wb": "FP.CPI.TOTL.ZG",  "imf": "PCPI_IX"},
    "unemployment":   {"fred": "UNRATE",    "wb": "SL.UEM.TOTL.ZS"},
    "interest_rate":  {"fred": "DFF",       "imf": "FPOLM_PA"},
    "population":     {"wb": "SP.POP.TOTL"},
    "trade_balance":  {"wb": "BN.GSR.GNFS.CD",   "imf": "BCA_BP6_USD"},
    "exchange_rate":  {"fred": "DEXUSEU",   "imf": "ENDA_XDC_USD_RATE"},
    "debt_gdp":       {"fred": "GFDEGDQ188S", "wb": "GC.DOD.TOTL.GD.ZS"},
    "money_supply":   {"fred": "M2SL"},
    "yield_curve":    {"fred": "T10Y2Y"},
    "vix":            {"fred": "VIXCLS"},
    "jobless_claims": {"fred": "ICSA"},
    "military_spending": {"wb": "MS.MIL.XPND.GD.ZS"},
}

_US_CODES = {"US", "USA", "840", "United States"}


@mcp.tool()
async def indicator(concept: str, country: str = "US",
                    years: str = "2020:2024") -> dict:
    """Economic indicator by concept. Auto-routes to best provider.

    concept: gdp, gdp_growth, gdp_per_capita, inflation, unemployment,
             interest_rate, population, trade_balance, exchange_rate,
             debt_gdp, money_supply, yield_curve, vix, jobless_claims,
             military_spending.
    country: ISO2/ISO3 code (default US). For FRED-only concepts (vix,
             yield_curve, money_supply, jobless_claims) country is ignored.
    years: range like '2020:2024' (World Bank/IMF) or observation count for FRED.

    Routes: US → FRED (high-frequency) → World Bank fallback.
            Non-US → World Bank → IMF fallback."""
    key = concept.lower().replace(" ", "_").replace("-", "_")
    providers = _INDICATOR_MAP.get(key)
    if not providers:
        available = ", ".join(sorted(_INDICATOR_MAP))
        return {"error": f"Unknown concept '{concept}'. Available: {available}"}

    is_us = country.upper() in _US_CODES
    errors: list[str] = []

    if is_us and "fred" in providers and FRED_KEY:
        try:
            return {"provider": "fred", "series_id": providers["fred"],
                    "data": await fred_series(providers["fred"])}
        except Exception as e:
            errors.append(f"fred: {e}")

    if "wb" in providers:
        try:
            wb_country = country if not is_us else "US"
            return {"provider": "worldbank", "indicator": providers["wb"],
                    "data": await worldbank_indicator(
                        providers["wb"], wb_country, years)}
        except Exception as e:
            errors.append(f"worldbank: {e}")

    if "imf" in providers:
        try:
            ref = country.upper()[:2] if len(country) <= 3 else country.upper()
            start, _, end = years.partition(":")
            return {"provider": "imf", "indicator": providers["imf"],
                    "data": await imf_data(
                        ref_area=ref, indicator=providers["imf"],
                        start=start, end=end or start)}
        except Exception as e:
            errors.append(f"imf: {e}")

    return {"error": f"All providers failed for '{concept}' ({country})",
            "details": errors}


if __name__ == "__main__":
    mcp.run(transport="stdio")

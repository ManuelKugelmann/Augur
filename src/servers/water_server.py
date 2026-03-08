"""Water & Drought — USGS Water Services, US Drought Monitor."""
from fastmcp import FastMCP
from datetime import datetime as dt, timedelta
import httpx

mcp = FastMCP("water", instructions="Streamflow, groundwater, water quality, drought monitoring")

# State FIPS codes for drought API (2-letter -> 2-digit FIPS)
_STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "FL": "12", "GA": "13", "HI": "15", "ID": "16",
    "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22",
    "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40",
    "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47",
    "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56",
}


def _to_fips(area: str) -> str:
    """Convert 2-letter state code to FIPS if needed."""
    return _STATE_FIPS.get(area.upper(), area)


@mcp.tool()
async def streamflow(site: str = "", state: str = "CA",
                     period: str = "P7D") -> dict:
    """USGS real-time streamflow (discharge). site: USGS site number,
    state: 2-letter code, period: P1D, P7D, P30D."""
    params = {"format": "json", "period": period, "parameterCd": "00060"}
    if site:
        params["sites"] = site
    elif state:
        params["stateCd"] = state
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://waterservices.usgs.gov/nwis/iv", params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"USGS streamflow request failed: {e}"}


@mcp.tool()
async def groundwater(site: str = "", state: str = "CA",
                      period: str = "P7D") -> dict:
    """USGS groundwater levels. site: USGS site number, state: 2-letter code."""
    params = {"format": "json", "period": period, "parameterCd": "72019"}
    if site:
        params["sites"] = site
    elif state:
        params["stateCd"] = state
        params["siteType"] = "GW"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://waterservices.usgs.gov/nwis/iv", params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"USGS groundwater request failed: {e}"}


@mcp.tool()
async def water_quality(state: str = "CA", parameter: str = "00010",
                        period: str = "P7D") -> dict:
    """USGS water quality. parameter: 00010=temp, 00300=dissolved_oxygen,
    00400=pH, 00095=conductance, 63680=turbidity."""
    params = {"format": "json", "period": period,
              "parameterCd": parameter, "stateCd": state, "siteType": "ST"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://waterservices.usgs.gov/nwis/iv", params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"USGS water quality request failed: {e}"}


@mcp.tool()
async def drought(area: str = "06", scope: str = "StateStatistics",
                  start_date: str = "", end_date: str = "") -> dict:
    """US Drought Monitor (percent area per severity level).
    scope: USStatistics, StateStatistics, CountyStatistics.
    area: 'us' for national, 2-digit FIPS for state (06=CA, or use 2-letter
    code like CA), 5-digit FIPS for county. Dates: M/D/YYYY format."""
    area = _to_fips(area)
    if not start_date:
        start_date = (dt.now() - timedelta(days=90)).strftime("%-m/%-d/%Y")
    if not end_date:
        end_date = dt.now().strftime("%-m/%-d/%Y")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"https://usdmdataservices.unl.edu/api/{scope}/GetDroughtSeverityStatisticsByAreaPercent",
                params={"aoi": area, "startdate": start_date,
                        "enddate": end_date, "statisticsType": "1"},
                headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"US Drought Monitor request failed: {e}"}


@mcp.tool()
async def drought_dsci(area: str = "06", scope: str = "StateStatistics",
                        start_date: str = "", end_date: str = "") -> dict:
    """US Drought Monitor DSCI (Drought Severity and Coverage Index, 0-500).
    scope: StateStatistics, CountyStatistics. area: FIPS code or 2-letter state."""
    area = _to_fips(area)
    if not start_date:
        start_date = (dt.now() - timedelta(days=365)).strftime("%-m/%-d/%Y")
    if not end_date:
        end_date = dt.now().strftime("%-m/%-d/%Y")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                f"https://usdmdataservices.unl.edu/api/{scope}/GetDSCI",
                params={"aoi": area, "startdate": start_date,
                        "enddate": end_date, "statisticsType": "1"},
                headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"US Drought Monitor DSCI request failed: {e}"}


# ── Aggregation ──────────────────────────────────────────


@mcp.tool()
async def water_alerts(state: str = "CA") -> dict:
    """Water overview for a US state: current streamflow + drought conditions.
    Combines USGS real-time data with US Drought Monitor."""
    fips = _to_fips(state)
    results: dict = {}
    try:
        results["streamflow"] = await streamflow(state=state, period="P1D")
    except Exception as e:
        results["streamflow"] = {"error": str(e)}
    try:
        results["drought"] = await drought(area=fips)
    except Exception as e:
        results["drought"] = {"error": str(e)}
    results["_meta"] = {"state": state, "sources": ["USGS", "USDM"]}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

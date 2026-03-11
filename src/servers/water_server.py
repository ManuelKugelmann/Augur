"""Water & Drought — USGS Water Services, US Drought Monitor."""
from fastmcp import FastMCP
from _http import api_get, api_multi
from datetime import datetime, timedelta

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


# ── USGS Water Services (shared endpoint, different params) ──

async def _usgs_iv(param_code: str, site: str = "", state: str = "CA",
                   period: str = "P7D", site_type: str = "") -> dict:
    """Shared USGS instantaneous values query."""
    params = {"format": "json", "period": period, "parameterCd": param_code}
    if site:
        params["sites"] = site
    elif state:
        params["stateCd"] = state
        if site_type:
            params["siteType"] = site_type
    return await api_get("https://waterservices.usgs.gov/nwis/iv",
                         params=params, timeout=15, label="USGS")


@mcp.tool()
async def streamflow(site: str = "", state: str = "CA",
                     period: str = "P7D") -> dict:
    """USGS real-time streamflow (discharge). site: USGS site number,
    state: 2-letter code, period: P1D, P7D, P30D."""
    return await _usgs_iv("00060", site=site, state=state, period=period)


@mcp.tool()
async def groundwater(site: str = "", state: str = "CA",
                      period: str = "P7D") -> dict:
    """USGS groundwater levels. site: USGS site number, state: 2-letter code."""
    return await _usgs_iv("72019", site=site, state=state, period=period,
                          site_type="GW")


@mcp.tool()
async def water_quality(state: str = "CA", parameter: str = "00010",
                        period: str = "P7D") -> dict:
    """USGS water quality. parameter: 00010=temp, 00300=dissolved_oxygen,
    00400=pH, 00095=conductance, 63680=turbidity."""
    return await _usgs_iv(parameter, state=state, period=period,
                          site_type="ST")


# ── US Drought Monitor (shared pattern) ──

async def _drought_query(endpoint: str, area: str, scope: str,
                         start_date: str, end_date: str,
                         default_days: int) -> dict:
    """Shared Drought Monitor query."""
    area = _to_fips(area)
    if not start_date:
        start_date = (datetime.now() - timedelta(days=default_days)).strftime("%-m/%-d/%Y")
    if not end_date:
        end_date = datetime.now().strftime("%-m/%-d/%Y")
    return await api_get(
        f"https://usdmdataservices.unl.edu/api/{scope}/{endpoint}",
        params={"aoi": area, "startdate": start_date,
                "enddate": end_date, "statisticsType": "1"},
        headers={"Accept": "application/json"}, timeout=30,
        label="US Drought Monitor")


@mcp.tool()
async def drought(area: str = "06", scope: str = "StateStatistics",
                  start_date: str = "", end_date: str = "") -> dict:
    """US Drought Monitor (percent area per severity level).
    scope: USStatistics, StateStatistics, CountyStatistics.
    area: 'us' for national, 2-digit FIPS for state (06=CA, or use 2-letter
    code like CA), 5-digit FIPS for county. Dates: M/D/YYYY format."""
    return await _drought_query(
        "GetDroughtSeverityStatisticsByAreaPercent",
        area, scope, start_date, end_date, default_days=90)


@mcp.tool()
async def drought_dsci(area: str = "06", scope: str = "StateStatistics",
                        start_date: str = "", end_date: str = "") -> dict:
    """US Drought Monitor DSCI (Drought Severity and Coverage Index, 0-500).
    scope: StateStatistics, CountyStatistics. area: FIPS code or 2-letter state."""
    return await _drought_query(
        "GetDSCI", area, scope, start_date, end_date, default_days=365)


# ── Aggregation ──────────────────────────────────────────


@mcp.tool()
async def water_alerts(state: str = "CA") -> dict:
    """Water overview for a US state: current streamflow + drought conditions.
    Combines USGS real-time data with US Drought Monitor."""
    fips = _to_fips(state)
    results = await api_multi({
        "streamflow": streamflow(state=state, period="P1D"),
        "drought": drought(area=fips),
    })
    results["_meta"] = {"state": state, "sources": ["USGS", "USDM"]}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

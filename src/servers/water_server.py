"""Water & Drought — USGS Water Services, US Drought Monitor, USGS Water Quality."""
from fastmcp import FastMCP
import httpx

mcp = FastMCP("water", instructions="Streamflow, groundwater, water quality, drought monitoring")


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
async def drought(area_type: str = "state", area: str = "CA") -> dict:
    """US Drought Monitor conditions. area_type: state/county/national.
    area: 2-letter state code, FIPS, or 'total' for national."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://usdm.unl.edu/DmData/TimeSeries.aspx",
                            params={"area_type": area_type, "area": area,
                                    "format": "json"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"US Drought Monitor request failed: {e}"}


@mcp.tool()
async def drought_comprehensive(area_type: str = "state",
                                 area: str = "CA") -> dict:
    """Comprehensive drought data: DSCI score + current conditions.
    area_type: state/county. area: 2-letter code or FIPS."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            ts = await c.get("https://usdm.unl.edu/DmData/TimeSeries.aspx",
                             params={"area_type": area_type, "area": area,
                                     "format": "json"})
            dsci = await c.get("https://usdm.unl.edu/DmData/TimeSeries.aspx",
                               params={"area_type": area_type, "area": area,
                                       "statstype": "4", "format": "json"})
            return {
                "conditions": ts.json() if ts.status_code == 200 else [],
                "dsci_score": dsci.json() if dsci.status_code == 200 else [],
            }
    except httpx.HTTPError as e:
        return {"error": f"Drought data request failed: {e}"}


# ── Aggregation ──────────────────────────────────────────


@mcp.tool()
async def water_alerts(state: str = "CA") -> dict:
    """Water overview for a US state: current streamflow + drought conditions.
    Combines USGS real-time data with US Drought Monitor."""
    results: dict = {}
    try:
        results["streamflow"] = await streamflow(state=state, period="P1D")
    except Exception as e:
        results["streamflow"] = {"error": str(e)}
    try:
        results["drought"] = await drought(area_type="state", area=state)
    except Exception as e:
        results["drought"] = {"error": str(e)}
    results["_meta"] = {"state": state, "sources": ["USGS", "USDM"]}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

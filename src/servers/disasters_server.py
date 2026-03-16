"""Disasters — USGS Earthquakes + GDACS + NASA EONET."""
from fastmcp import FastMCP
from _http import api_get, api_multi
import httpx
from datetime import datetime, timedelta, timezone
import logging

log = logging.getLogger("augur.disasters")

mcp = FastMCP("disasters", instructions="Real-time earthquakes, disasters, natural events")


@mcp.tool()
async def get_earthquakes(min_magnitude: float = 4.0, days: int = 7,
                          alert_level: str = "", limit: int = 100) -> dict:
    """Recent earthquakes. alert_level: green/yellow/orange/red or empty."""
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"format": "geojson", "starttime": start,
              "minmagnitude": min_magnitude, "limit": limit, "orderby": "time"}
    if alert_level:
        params["alertlevel"] = alert_level
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://earthquake.usgs.gov/fdsnws/event/1/query", params=params)
            r.raise_for_status()
            data = r.json()
            features = data.get("features", [])
            return {"count": data.get("metadata", {}).get("count", len(features)),
                    "earthquakes": [{"mag": f["properties"]["mag"],
                        "place": f["properties"]["place"],
                        "time": f["properties"]["time"],
                        "tsunami": f["properties"].get("tsunami"),
                        "alert": f["properties"].get("alert"),
                        "coords": f["geometry"]["coordinates"]}
                        for f in features]}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"error": f"USGS earthquake request failed: {type(e).__name__}: {e}"}


@mcp.tool()
async def get_disasters() -> dict:
    """GDACS global disaster alerts (earthquakes, floods, cyclones, volcanoes)."""
    return await api_get(
        "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
        params={"eventlist": "", "fromDate": "", "toDate": "", "alertlevel": ""},
        timeout=15, label="GDACS")


@mcp.tool()
async def get_natural_events(category: str = "", days: int = 30,
                              status: str = "open", limit: int = 50) -> dict:
    """NASA EONET natural events. category: wildfires, severeStorms, volcanoes,
    seaLakeIce, earthquakes, floods, landslides, drought, dustHaze, snow."""
    params = {"status": status, "limit": limit, "days": days}
    if category:
        params["category"] = category
    return await api_get("https://eonet.gsfc.nasa.gov/api/v3/events",
                         params=params, timeout=15, label="NASA EONET")


# ── Provider-agnostic routing ──────────────────────────

# Hazard → best EONET category name
_EONET_CATEGORIES: dict[str, str] = {
    "wildfire": "wildfires", "storm": "severeStorms", "volcano": "volcanoes",
    "flood": "floods", "landslide": "landslides", "drought": "drought",
    "ice": "seaLakeIce", "dust": "dustHaze", "snow": "snow",
}


@mcp.tool()
async def hazard_alerts(hazard: str = "", days: int = 7,
                        min_magnitude: float = 4.0) -> dict:
    """Natural hazard alerts. Auto-selects best source per hazard type.

    hazard: earthquake, flood, cyclone, volcano, wildfire, storm, landslide,
            drought, dust, snow, ice, or empty for all.
    For earthquakes: returns detailed USGS data (magnitude, alert, tsunami).
    For other/all hazards: returns GDACS alerts + NASA EONET events."""
    hazard = hazard.lower().strip()
    calls: dict = {}
    if hazard in ("earthquake", "quake", ""):
        calls["usgs_earthquakes"] = get_earthquakes(
            min_magnitude=min_magnitude, days=days)
    if hazard != "earthquake":
        calls["gdacs_alerts"] = get_disasters()
        eonet_cat = _EONET_CATEGORIES.get(hazard, "")
        calls["eonet_events"] = get_natural_events(category=eonet_cat, days=days)
    results = await api_multi(calls)
    results["_meta"] = {"hazard": hazard or "all", "days": days,
                        "sources": [k for k in results if k != "_meta"]}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

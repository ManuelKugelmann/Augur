"""Transport — OpenSky flights, AIS vessel tracking."""
from fastmcp import FastMCP
from _http import api_get, OAuthToken
import httpx
import os
import logging
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("augur.transport")

mcp = FastMCP("transport", instructions="Flight tracking, vessel tracking, shipping chokepoints")
AIS_KEY = os.environ.get("AISSTREAM_API_KEY", "")
OPENSKY_CLIENT_ID = os.environ.get("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.environ.get("OPENSKY_CLIENT_SECRET", "")

_OPENSKY_BASE = "https://opensky-network.org/api"

# ── OpenSky OAuth2 ────────────────────────────

_opensky_oauth = OAuthToken(
    token_url="https://auth.opensky-network.org/auth/realms/opensky-network"
              "/protocol/openid-connect/token",
    client_id=OPENSKY_CLIENT_ID,
    client_secret=OPENSKY_CLIENT_SECRET,
)


# ── OpenSky state vector field names ─────────────

_STATE_FIELDS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact",
    "longitude", "latitude", "baro_altitude", "on_ground", "velocity",
    "true_track", "vertical_rate", "sensors", "geo_altitude", "squawk",
    "spi", "position_source", "category",
]


def _label_states(raw_states: list | None, limit: int = 50) -> list[dict]:
    """Convert positional state arrays into labelled dicts (capped)."""
    if not raw_states:
        return []
    return [{k: v for k, v in zip(_STATE_FIELDS, s) if v is not None}
            for s in raw_states[:limit]]


# ── OpenSky endpoints ────────────────────────────

@mcp.tool()
async def flights_in_area(lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float,
                           extended: bool = False) -> dict:
    """OpenSky live aircraft in bounding box. Returns up to 50 state vectors.
    Set extended=True for aircraft category info. Auth optional but gives
    higher rate limits (set OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET)."""
    headers = await _opensky_oauth.headers()
    params: dict = {"lamin": lat_min, "lamax": lat_max,
                    "lomin": lon_min, "lomax": lon_max}
    if extended:
        params["extended"] = 1
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/states/all",
                            params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            states = _label_states(data.get("states"))
            return {"time": data.get("time"), "count": len(data.get("states") or []),
                    "states": states}
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"OpenSky request failed: {type(e).__name__}: {e}"}


@mcp.tool()
async def own_states(icao24: str = "", serials: str = "") -> dict:
    """State vectors from your own OpenSky receivers. Requires OAuth2 credentials.
    Optional: icao24 hex address, serials (comma-separated receiver serial numbers)."""
    headers = await _opensky_oauth.headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    params: dict = {}
    if icao24:
        params["icao24"] = icao24
    if serials:
        params["serials"] = serials
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/states/own",
                            params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            states = _label_states(data.get("states"))
            return {"time": data.get("time"), "count": len(data.get("states") or []),
                    "states": states}
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"OpenSky own states request failed: {type(e).__name__}: {e}"}


@mcp.tool()
async def flight_history(icao24: str, begin: int = 0, end: int = 0) -> dict:
    """Flight history for aircraft by ICAO24 hex address. Requires auth.
    begin/end are Unix timestamps (max 2-day interval). Updated nightly."""
    headers = await _opensky_oauth.headers()
    params: dict = {"icao24": icao24.lower()}
    if begin:
        params["begin"] = begin
    if end:
        params["end"] = end
    return await api_get(f"{_OPENSKY_BASE}/flights/aircraft",
                         params=params, headers=headers, timeout=15,
                         label="OpenSky flight history")


@mcp.tool()
async def all_flights(begin: int, end: int) -> dict:
    """All flights in a time interval (max 2 hours). Requires auth.
    begin/end are Unix timestamps. Updated nightly."""
    headers = await _opensky_oauth.headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    return await api_get(f"{_OPENSKY_BASE}/flights/all",
                         params={"begin": begin, "end": end},
                         headers=headers, timeout=15,
                         label="OpenSky all flights")


# ── Airport arrivals/departures (shared pattern) ──

async def _airport_flights(direction: str, airport: str, begin: int,
                           end: int) -> dict:
    """Shared OpenSky airport flight query."""
    headers = await _opensky_oauth.headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    result = await api_get(
        f"{_OPENSKY_BASE}/flights/{direction}",
        params={"airport": airport.upper(), "begin": begin, "end": end},
        headers=headers, timeout=15,
        label=f"OpenSky {direction}s")
    if "error" not in result:
        return {"airport": airport.upper(), "flights": result}
    return result


@mcp.tool()
async def airport_arrivals(airport: str, begin: int, end: int) -> dict:
    """Flights arriving at an airport. Requires auth.
    airport: ICAO code (e.g. EDDF, KJFK). begin/end: Unix timestamps (max 7 days).
    Updated nightly — historical data only."""
    return await _airport_flights("arrival", airport, begin, end)


@mcp.tool()
async def airport_departures(airport: str, begin: int, end: int) -> dict:
    """Flights departing from an airport. Requires auth.
    airport: ICAO code (e.g. EDDF, KJFK). begin/end: Unix timestamps (max 7 days).
    Updated nightly — historical data only."""
    return await _airport_flights("departure", airport, begin, end)


@mcp.tool()
async def flight_track(icao24: str, time_stamp: int = 0) -> dict:
    """Aircraft trajectory waypoints. Requires auth.
    icao24: hex address. time_stamp: Unix timestamp within flight window (0 = live).
    Max 30 days history. Experimental endpoint."""
    headers = await _opensky_oauth.headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    params: dict = {"icao24": icao24.lower()}
    if time_stamp:
        params["time"] = time_stamp
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/tracks",
                            params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            wp_fields = ["time", "latitude", "longitude",
                         "baro_altitude", "true_track", "on_ground"]
            waypoints = [{k: v for k, v in zip(wp_fields, wp) if v is not None}
                         for wp in (data.get("path") or [])]
            return {"icao24": data.get("icao24"),
                    "callsign": data.get("callsign"),
                    "startTime": data.get("startTime"),
                    "endTime": data.get("endTime"),
                    "waypoints": waypoints}
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"OpenSky track request failed: {type(e).__name__}: {e}"}


# ── AIS / vessel tracking ────────────────────────

@mcp.tool()
async def vessels_in_area(lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float) -> dict:
    """AIS vessel positions. Chokepoints: Suez 29.8,30.1,32.3,32.6 —
    Hormuz 26.0,27.0,55.5,57.0 — Panama 8.8,9.4,-79.9,-79.5."""
    if not AIS_KEY:
        return {"error": "AISSTREAM_API_KEY not set"}
    return await api_get("https://api.aisstream.io/v0/vessel-positions",
                         params={"apiKey": AIS_KEY,
                                 "boundingBox": f"{lat_min},{lon_min},{lat_max},{lon_max}"},
                         timeout=15, label="AIS vessel")


if __name__ == "__main__":
    mcp.run(transport="stdio")

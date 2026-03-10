"""Transport — OpenSky flights, AIS vessel tracking."""
from fastmcp import FastMCP
import httpx
import os
import time
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("transport", instructions="Flight tracking, vessel tracking, shipping chokepoints")
AIS_KEY = os.environ.get("AISSTREAM_API_KEY", "")
OPENSKY_CLIENT_ID = os.environ.get("OPENSKY_CLIENT_ID", "")
OPENSKY_CLIENT_SECRET = os.environ.get("OPENSKY_CLIENT_SECRET", "")

_OPENSKY_BASE = "https://opensky-network.org/api"

# ── OpenSky OAuth2 helper ────────────────────────

_opensky_token: str = ""
_opensky_token_exp: float = 0


async def _opensky_headers() -> dict:
    """Get Authorization header for OpenSky (OAuth2 client credentials).
    Supports both public clients (client_id only) and confidential clients
    (client_id + client_secret)."""
    global _opensky_token, _opensky_token_exp
    if not OPENSKY_CLIENT_ID:
        return {}
    if _opensky_token and time.time() < _opensky_token_exp:
        return {"Authorization": f"Bearer {_opensky_token}"}
    try:
        token_data: dict = {"grant_type": "client_credentials",
                            "client_id": OPENSKY_CLIENT_ID}
        if OPENSKY_CLIENT_SECRET:
            token_data["client_secret"] = OPENSKY_CLIENT_SECRET
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://auth.opensky-network.org/auth/realms/opensky-network"
                "/protocol/openid-connect/token",
                data=token_data)
            r.raise_for_status()
            data = r.json()
            _opensky_token = data["access_token"]
            _opensky_token_exp = time.time() + data.get("expires_in", 1800) - 60
            return {"Authorization": f"Bearer {_opensky_token}"}
    except httpx.HTTPError:
        return {}


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
    out = []
    for s in raw_states[:limit]:
        out.append({k: v for k, v in zip(_STATE_FIELDS, s) if v is not None})
    return out


# ── OpenSky endpoints ────────────────────────────

@mcp.tool()
async def flights_in_area(lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float,
                           extended: bool = False) -> dict:
    """OpenSky live aircraft in bounding box. Returns up to 50 state vectors.
    Set extended=True for aircraft category info. Auth optional but gives
    higher rate limits (set OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET)."""
    headers = await _opensky_headers()
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
    except httpx.HTTPError as e:
        return {"error": f"OpenSky request failed: {e}"}


@mcp.tool()
async def own_states(icao24: str = "", serials: str = "") -> dict:
    """State vectors from your own OpenSky receivers. Requires OAuth2 credentials.
    Optional: icao24 hex address, serials (comma-separated receiver serial numbers)."""
    headers = await _opensky_headers()
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
    except httpx.HTTPError as e:
        return {"error": f"OpenSky own states request failed: {e}"}


@mcp.tool()
async def flight_history(icao24: str, begin: int = 0, end: int = 0) -> dict:
    """Flight history for aircraft by ICAO24 hex address. Requires auth.
    begin/end are Unix timestamps (max 2-day interval). Updated nightly."""
    headers = await _opensky_headers()
    params: dict = {"icao24": icao24.lower()}
    if begin:
        params["begin"] = begin
    if end:
        params["end"] = end
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/flights/aircraft",
                            params=params, headers=headers)
            r.raise_for_status()
            return {"flights": r.json()}
    except httpx.HTTPError as e:
        return {"error": f"OpenSky flight history request failed: {e}"}


@mcp.tool()
async def all_flights(begin: int, end: int) -> dict:
    """All flights in a time interval (max 2 hours). Requires auth.
    begin/end are Unix timestamps. Updated nightly."""
    headers = await _opensky_headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/flights/all",
                            params={"begin": begin, "end": end},
                            headers=headers)
            r.raise_for_status()
            return {"flights": r.json()}
    except httpx.HTTPError as e:
        return {"error": f"OpenSky all flights request failed: {e}"}


@mcp.tool()
async def airport_arrivals(airport: str, begin: int, end: int) -> dict:
    """Flights arriving at an airport. Requires auth.
    airport: ICAO code (e.g. EDDF, KJFK). begin/end: Unix timestamps (max 7 days).
    Updated nightly — historical data only."""
    headers = await _opensky_headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/flights/arrival",
                            params={"airport": airport.upper(),
                                    "begin": begin, "end": end},
                            headers=headers)
            r.raise_for_status()
            return {"airport": airport.upper(), "flights": r.json()}
    except httpx.HTTPError as e:
        return {"error": f"OpenSky arrivals request failed: {e}"}


@mcp.tool()
async def airport_departures(airport: str, begin: int, end: int) -> dict:
    """Flights departing from an airport. Requires auth.
    airport: ICAO code (e.g. EDDF, KJFK). begin/end: Unix timestamps (max 7 days).
    Updated nightly — historical data only."""
    headers = await _opensky_headers()
    if not headers:
        return {"error": "OPENSKY_CLIENT_ID required (set in .env)"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{_OPENSKY_BASE}/flights/departure",
                            params={"airport": airport.upper(),
                                    "begin": begin, "end": end},
                            headers=headers)
            r.raise_for_status()
            return {"airport": airport.upper(), "flights": r.json()}
    except httpx.HTTPError as e:
        return {"error": f"OpenSky departures request failed: {e}"}


@mcp.tool()
async def flight_track(icao24: str, time_stamp: int = 0) -> dict:
    """Aircraft trajectory waypoints. Requires auth.
    icao24: hex address. time_stamp: Unix timestamp within flight window (0 = live).
    Max 30 days history. Experimental endpoint."""
    headers = await _opensky_headers()
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
            waypoints = []
            wp_fields = ["time", "latitude", "longitude",
                         "baro_altitude", "true_track", "on_ground"]
            for wp in (data.get("path") or []):
                waypoints.append({k: v for k, v in zip(wp_fields, wp)
                                  if v is not None})
            return {"icao24": data.get("icao24"),
                    "callsign": data.get("callsign"),
                    "startTime": data.get("startTime"),
                    "endTime": data.get("endTime"),
                    "waypoints": waypoints}
    except httpx.HTTPError as e:
        return {"error": f"OpenSky track request failed: {e}"}


# ── AIS / vessel tracking ────────────────────────

@mcp.tool()
async def vessels_in_area(lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float) -> dict:
    """AIS vessel positions. Chokepoints: Suez 29.8,30.1,32.3,32.6 —
    Hormuz 26.0,27.0,55.5,57.0 — Panama 8.8,9.4,-79.9,-79.5."""
    if not AIS_KEY:
        return {"error": "AISSTREAM_API_KEY not set"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.aisstream.io/v0/vessel-positions", params={
                "apiKey": AIS_KEY,
                "boundingBox": f"{lat_min},{lon_min},{lat_max},{lon_max}"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"AIS vessel request failed: {e}"}


if __name__ == "__main__":
    mcp.run(transport="stdio")

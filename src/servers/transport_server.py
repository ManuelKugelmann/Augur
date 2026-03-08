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

# ── OpenSky OAuth2 helper ────────────────────────

_opensky_token: str = ""
_opensky_token_exp: float = 0


async def _opensky_headers() -> dict:
    """Get Authorization header for OpenSky (OAuth2 client credentials)."""
    global _opensky_token, _opensky_token_exp
    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
        return {}
    if _opensky_token and time.time() < _opensky_token_exp:
        return {"Authorization": f"Bearer {_opensky_token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://auth.opensky-network.org/auth/realms/opensky-network"
                "/protocol/openid-connect/token",
                data={"grant_type": "client_credentials",
                      "client_id": OPENSKY_CLIENT_ID,
                      "client_secret": OPENSKY_CLIENT_SECRET})
            r.raise_for_status()
            data = r.json()
            _opensky_token = data["access_token"]
            _opensky_token_exp = time.time() + data.get("expires_in", 1800) - 60
            return {"Authorization": f"Bearer {_opensky_token}"}
    except httpx.HTTPError:
        return {}


@mcp.tool()
async def flights_in_area(lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float) -> dict:
    """OpenSky live aircraft in bounding box. Optional: OPENSKY_CLIENT_ID +
    OPENSKY_CLIENT_SECRET for authenticated access (higher rate limits)."""
    headers = await _opensky_headers()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://opensky-network.org/api/states/all",
                            params={"lamin": lat_min, "lamax": lat_max,
                                    "lomin": lon_min, "lomax": lon_max},
                            headers=headers)
            r.raise_for_status()
            data = r.json()
            return {"count": len(data.get("states", [])),
                    "states": data.get("states", [])[:50]}
    except httpx.HTTPError as e:
        return {"error": f"OpenSky request failed: {e}"}


@mcp.tool()
async def flight_history(icao24: str, begin: int = 0, end: int = 0) -> dict:
    """Flight history for aircraft by ICAO24 hex address."""
    headers = await _opensky_headers()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            params: dict = {"icao24": icao24}
            if begin:
                params["begin"] = begin
            if end:
                params["end"] = end
            r = await c.get("https://opensky-network.org/api/flights/aircraft",
                            params=params, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"OpenSky flight history request failed: {e}"}


@mcp.tool()
async def vessels_in_area(lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float) -> dict:
    """AIS vessel positions. Chokepoints: Suez 29.8,30.1,32.3,32.6 —
    Hormuz 26.0,27.0,55.5,57.0 — Panama 8.8,9.4,-79.9,-79.5."""
    if not AIS_KEY:
        return {"error": "AISSTREAM_API_KEY not set"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.aisstream.io/v0/vessel-positions", params={
            "apiKey": AIS_KEY,
            "boundingBox": f"{lat_min},{lon_min},{lat_max},{lon_max}"})
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    mcp.run(transport="stdio")

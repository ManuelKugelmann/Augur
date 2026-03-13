"""Conflict & Military — UCDP, ACLED, VIEWS forecasts, OpenSanctions."""
import asyncio
import logging
import time
from fastmcp import FastMCP
from _http import api_get
import os
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("augur.conflict")

mcp = FastMCP("conflict", instructions="Armed conflict events, military data, sanctions")
ACLED_EMAIL = os.environ.get("ACLED_EMAIL", "")
ACLED_PASSWORD = os.environ.get("ACLED_PASSWORD", "")
UCDP_TOKEN = os.environ.get("UCDP_ACCESS_TOKEN", "")
OPENSANCTIONS_KEY = os.environ.get("OPENSANCTIONS_API_KEY", "")


# ── ACLED OAuth (password grant, cached with expiry + lock) ──

_acled_token: str = ""
_acled_token_exp: float = 0
_acled_lock = asyncio.Lock()


async def _acled_auth() -> str:
    """Get ACLED OAuth bearer token (async-safe with lock)."""
    global _acled_token, _acled_token_exp
    if _acled_token and time.time() < _acled_token_exp:
        return _acled_token
    if not ACLED_EMAIL or not ACLED_PASSWORD:
        return ""
    async with _acled_lock:
        # Double-check after acquiring lock
        if _acled_token and time.time() < _acled_token_exp:
            return _acled_token
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://acleddata.com/oauth/token", data={
                    "username": ACLED_EMAIL, "password": ACLED_PASSWORD,
                    "grant_type": "password", "client_id": "acled"})
                r.raise_for_status()
                data = r.json()
                _acled_token = data.get("access_token", "")
                _acled_token_exp = time.time() + data.get("expires_in", 3600) - 60
                return _acled_token
        except Exception:
            log.warning("ACLED auth failed")
            return ""


_UCDP_BASE = "https://ucdpapi.pcr.uu.se/api"


def _ucdp_headers() -> dict:
    if UCDP_TOKEN:
        return {"x-ucdp-access-token": UCDP_TOKEN}
    return {}


@mcp.tool()
async def ucdp_conflicts(year: int = 2024, page: int = 1,
                          version: str = "25.1") -> dict:
    """UCDP georeferenced conflict events (GED). Data: 1989-2024.
    version: API dataset version (default 25.1 = 2025 release covering through 2024).
    Requires UCDP_ACCESS_TOKEN env var."""
    return await api_get(f"{_UCDP_BASE}/gedevents/{version}",
                         params={"pagesize": 100, "page": page, "Year": year},
                         headers=_ucdp_headers(), label="UCDP")


@mcp.tool()
async def ucdp_candidate_events(page: int = 1, country: str = "",
                                 version: str = "26.0.1") -> dict:
    """UCDP candidate events — near-real-time monthly releases (more recent than
    the stable GED dataset). Use for 2025+ conflict events. version default: 26.0.1.
    Requires UCDP_ACCESS_TOKEN env var."""
    params: dict = {"pagesize": 100, "page": page}
    if country:
        params["Country"] = country
    return await api_get(f"{_UCDP_BASE}/gedevents/{version}",
                         params=params, headers=_ucdp_headers(),
                         label="UCDP candidate events")


_VIEWS_BASE = "https://api.viewsforecasting.org"


@mcp.tool()
async def views_forecast(iso: str = "", level: str = "cm",
                          violence_type: str = "sb",
                          date_start: str = "", date_end: str = "") -> dict:
    """VIEWS conflict fatality forecasts 1-36 months ahead. Free, no auth.
    iso: 3-letter country code (e.g. SYR, UKR). level: cm (country-month) or
    pgm (PRIO-GRID-month, sub-national for Africa/MENA). violence_type: sb
    (state-based), ns (non-state), os (one-sided). date_start/date_end: YYYY-MM-DD."""
    params: dict = {"pagesize": 100}
    if iso:
        params["iso"] = iso.upper()
    if date_start:
        params["date_start"] = date_start
    if date_end:
        params["date_end"] = date_end
    return await api_get(f"{_VIEWS_BASE}/current/{level}/{violence_type}",
                         params=params, label="VIEWS forecast")


@mcp.tool()
async def acled_events(country: str = "", event_type: str = "",
                        event_date_start: str = "", limit: int = 100) -> dict:
    """ACLED conflict/protest events. Requires ACLED_EMAIL + ACLED_PASSWORD (OAuth).
    event_type: Battles, Protests, Riots, Violence against civilians,
    Explosions/Remote violence."""
    token = await _acled_auth()
    if not token:
        return {"error": "ACLED_EMAIL + ACLED_PASSWORD not set (OAuth login required)"}
    params: dict = {"limit": limit}
    if country:
        params["country"] = country
    if event_type:
        params["event_type"] = event_type
    if event_date_start:
        params["event_date"] = f"{event_date_start}|"
    return await api_get("https://acleddata.com/api/acled/read",
                         params=params,
                         headers={"Authorization": f"Bearer {token}"},
                         label="ACLED")


@mcp.tool()
async def search_sanctions(query: str, schema: str = "") -> dict:
    """OpenSanctions search. Requires OPENSANCTIONS_API_KEY env var.
    schema: Person, Company, Vessel, Aircraft, Organization."""
    if not OPENSANCTIONS_KEY:
        return {"error": "OPENSANCTIONS_API_KEY not set — get a free key at opensanctions.org"}
    params = {"q": query, "limit": 20}
    if schema:
        params["schema"] = schema
    return await api_get("https://api.opensanctions.org/search/default",
                         params=params,
                         headers={"Authorization": f"ApiKey {OPENSANCTIONS_KEY}"},
                         label="OpenSanctions")


if __name__ == "__main__":
    mcp.run(transport="stdio")

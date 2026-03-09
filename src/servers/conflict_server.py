"""Conflict & Military — UCDP, ACLED, VIEWS forecasts, OpenSanctions."""
from fastmcp import FastMCP
import httpx
import os
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("conflict", instructions="Armed conflict events, military data, sanctions")
ACLED_EMAIL = os.environ.get("ACLED_EMAIL", "")
ACLED_PASSWORD = os.environ.get("ACLED_PASSWORD", "")
UCDP_TOKEN = os.environ.get("UCDP_ACCESS_TOKEN", "")
OPENSANCTIONS_KEY = os.environ.get("OPENSANCTIONS_API_KEY", "")


# ── ACLED OAuth helper ───────────────────────────

_acled_token: str = ""


async def _acled_auth() -> str:
    """Get ACLED OAuth bearer token (cached in module)."""
    global _acled_token
    if _acled_token:
        return _acled_token
    if not ACLED_EMAIL or not ACLED_PASSWORD:
        return ""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post("https://acleddata.com/oauth/token", data={
                "username": ACLED_EMAIL, "password": ACLED_PASSWORD,
                "grant_type": "password", "client_id": "acled"})
            r.raise_for_status()
            _acled_token = r.json().get("access_token", "")
            return _acled_token
    except httpx.HTTPError:
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
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_UCDP_BASE}/gedevents/{version}",
                            params={"pagesize": 100, "page": page, "Year": year},
                            headers=_ucdp_headers())
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"UCDP request failed: {e}"}


@mcp.tool()
async def ucdp_candidate_events(page: int = 1, country: str = "",
                                 version: str = "26.0.1") -> dict:
    """UCDP candidate events — near-real-time monthly releases (more recent than
    the stable GED dataset). Use for 2025+ conflict events. version default: 26.0.1.
    Requires UCDP_ACCESS_TOKEN env var."""
    params: dict = {"pagesize": 100, "page": page}
    if country:
        params["Country"] = country
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_UCDP_BASE}/gedevents/{version}",
                            params=params, headers=_ucdp_headers())
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"UCDP candidate events request failed: {e}"}


# ── VIEWS conflict forecasts ──────────────────────

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
    path = f"/current/{level}/{violence_type}"
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{_VIEWS_BASE}{path}", params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"VIEWS forecast request failed: {e}"}


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
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://acleddata.com/api/acled/read", params=params,
                            headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"ACLED request failed: {e}"}


@mcp.tool()
async def search_sanctions(query: str, schema: str = "") -> dict:
    """OpenSanctions search. Requires OPENSANCTIONS_API_KEY env var.
    schema: Person, Company, Vessel, Aircraft, Organization."""
    if not OPENSANCTIONS_KEY:
        return {"error": "OPENSANCTIONS_API_KEY not set — get a free key at opensanctions.org"}
    params = {"q": query, "limit": 20}
    if schema:
        params["schema"] = schema
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://api.opensanctions.org/search/default",
                            params=params,
                            headers={"Authorization": f"ApiKey {OPENSANCTIONS_KEY}"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"OpenSanctions request failed: {e}"}


if __name__ == "__main__":
    mcp.run(transport="stdio")

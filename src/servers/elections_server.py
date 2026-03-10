"""Elections — Global election data, EU Parliament, Google Civic Info, Wikidata."""
from fastmcp import FastMCP
from _http import api_get
import httpx
import os
import re
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("elections", instructions="Global elections and democracy data")
GOOGLE_KEY = os.environ.get("GOOGLE_API_KEY", "")

_WD_HEADERS = {"User-Agent": "TradingAssistant/1.0 (https://github.com/ManuelKugelmann/TradingAssistant)"}

# Sanitize inputs for SPARQL queries to prevent injection
_SAFE_SPARQL_TEXT = re.compile(r'^[A-Za-z0-9 .\'()-]+$')
_SAFE_YEAR = re.compile(r'^\d{4}$')
_SAFE_QID = re.compile(r'^Q\d+$')


async def _resolve_country_qid(name: str) -> str | None:
    """Resolve a country name to its Wikidata Q-ID via entity search."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.wikidata.org/w/api.php", params={
                "action": "wbsearchentities", "search": name,
                "language": "en", "type": "item", "limit": "5",
                "format": "json"}, headers=_WD_HEADERS)
            r.raise_for_status()
            for hit in r.json().get("search", []):
                qid = hit.get("id", "")
                if _SAFE_QID.match(qid):
                    return qid
    except httpx.HTTPError:
        pass
    return None


# ── Wikidata (global elections, no key) ──────────────────


@mcp.tool()
async def global_elections(country: str = "", year: str = "",
                           limit: int = 20) -> dict:
    """Global elections (Wikidata). country: English name. year: e.g. '2025'."""
    filters = []
    country_filter = ""
    if country:
        if not _SAFE_SPARQL_TEXT.match(country):
            return {"error": "invalid country name (letters, spaces, digits only)"}
        qid = await _resolve_country_qid(country)
        if not qid:
            return {"error": f"Could not resolve country '{country}' on Wikidata"}
        country_filter = f"VALUES ?country {{ wd:{qid} }}"
    if year:
        if not _SAFE_YEAR.match(year):
            return {"error": "invalid year (must be 4 digits, e.g. 2025)"}
        filters.append(f"FILTER(YEAR(?date) = {year})")
    filter_block = "\n    ".join(filters)
    query = f"""SELECT ?election ?electionLabel ?countryLabel ?date ?typeLabel WHERE {{
  {country_filter}
  ?election wdt:P31/wdt:P279* wd:Q40231 .
  ?election wdt:P17 ?country .
  ?election wdt:P585 ?date .
  OPTIONAL {{ ?election wdt:P31 ?type }}
  {filter_block}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}} ORDER BY DESC(?date) LIMIT {limit}"""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://query.wikidata.org/sparql",
                            params={"query": query, "format": "json"},
                            headers=_WD_HEADERS)
            r.raise_for_status()
            bindings = r.json()["results"]["bindings"]
            return {"elections": [
                {"election": b.get("electionLabel", {}).get("value", ""),
                 "country": b.get("countryLabel", {}).get("value", ""),
                 "date": b.get("date", {}).get("value", ""),
                 "type": b.get("typeLabel", {}).get("value", "")}
                for b in bindings]}
    except httpx.HTTPError as e:
        return {"error": f"Wikidata request failed: {e}"}


@mcp.tool()
async def heads_of_state(country: str = "", limit: int = 10) -> dict:
    """Heads of state/government (Wikidata). country: English name."""
    country_filter = ""
    if country:
        if not _SAFE_SPARQL_TEXT.match(country):
            return {"error": "invalid country name (letters, spaces, digits only)"}
        qid = await _resolve_country_qid(country)
        if not qid:
            return {"error": f"Could not resolve country '{country}' on Wikidata"}
        country_filter = f"VALUES ?country {{ wd:{qid} }}"
    query = f"""SELECT ?person ?personLabel ?countryLabel ?positionLabel ?start ?end WHERE {{
  {country_filter}
  ?person wdt:P39 ?position .
  ?position wdt:P279* wd:Q48352 .
  ?person p:P39 ?stmt .
  ?stmt ps:P39 ?position .
  ?stmt pq:P580 ?start .
  OPTIONAL {{ ?stmt pq:P582 ?end }}
  ?position wdt:P17 ?country .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
}} ORDER BY DESC(?start) LIMIT {limit}"""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://query.wikidata.org/sparql",
                            params={"query": query, "format": "json"},
                            headers=_WD_HEADERS)
            r.raise_for_status()
            bindings = r.json()["results"]["bindings"]
            return {"leaders": [
                {"person": b.get("personLabel", {}).get("value", ""),
                 "country": b.get("countryLabel", {}).get("value", ""),
                 "position": b.get("positionLabel", {}).get("value", ""),
                 "start": b.get("start", {}).get("value", ""),
                 "end": b.get("end", {}).get("value", "")}
                for b in bindings]}
    except httpx.HTTPError as e:
        return {"error": f"Wikidata request failed: {e}"}


# ── EU Parliament (no key) ──────────────────────────────


@mcp.tool()
async def eu_parliament_meps(country: str = "", limit: int = 50) -> dict:
    """EU Parliament members. country: ISO2 (DE, FR, IT)."""
    params: dict = {"offset": 0, "limit": limit}
    if country:
        params["country-of-representation"] = country.upper()
    result = await api_get("https://data.europarl.europa.eu/api/v2/meps",
                           params=params,
                           headers={"Accept": "application/ld+json"},
                           label="EU Parliament")
    if "error" not in result:
        meps = result.get("data", [])
        return {"count": len(meps), "meps": meps}
    return result


@mcp.tool()
async def eu_parliament_votes(year: str = "2025", limit: int = 20) -> dict:
    """EU Parliament plenary documents/votes."""
    return await api_get(
        "https://data.europarl.europa.eu/api/v2/plenary-documents",
        params={"year": year, "limit": limit},
        headers={"Accept": "application/ld+json"},
        label="EU Parliament")


# ── Google Civic Info (US, needs key) ────────────────────
# Note: us_representatives removed — Google Civic Representatives API
# was shut down April 2025.


@mcp.tool()
async def us_voter_info(address: str) -> dict:
    """US voter/election info for an address. Only during active elections."""
    if not GOOGLE_KEY:
        return {"error": "GOOGLE_API_KEY not set"}
    return await api_get(
        "https://www.googleapis.com/civicinfo/v2/voterInfoQuery",
        params={"key": GOOGLE_KEY, "address": address},
        label="Google Civic Info")


if __name__ == "__main__":
    mcp.run(transport="stdio")

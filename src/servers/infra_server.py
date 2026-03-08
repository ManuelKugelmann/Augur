"""Internet Infrastructure — Cloudflare Radar, RIPE Atlas, IODA outages."""
from fastmcp import FastMCP
import httpx
import os
import time
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("infra", instructions="Internet traffic, network probes, outage detection")
CF_TOKEN = os.environ.get("CF_API_TOKEN", "")


@mcp.tool()
async def internet_traffic(location: str = "", date_range: str = "7d") -> dict:
    """Cloudflare Radar HTTP traffic summary. location: country ISO2 (e.g. US, DE).
    date_range: 1d, 7d, 14d, 28d. Requires CF_API_TOKEN."""
    if not CF_TOKEN:
        return {"error": "CF_API_TOKEN not set"}
    params: dict = {"dateRange": date_range}
    if location:
        params["location"] = location
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://api.cloudflare.com/client/v4/radar/http/summary/http_protocol",
                params=params,
                headers={"Authorization": f"Bearer {CF_TOKEN}"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"Cloudflare Radar request failed: {e}"}


@mcp.tool()
async def traffic_anomalies(location: str = "", date_range: str = "7d") -> dict:
    """Cloudflare Radar traffic anomalies. location: country ISO2.
    Detects unusual traffic patterns. Requires CF_API_TOKEN."""
    if not CF_TOKEN:
        return {"error": "CF_API_TOKEN not set"}
    params: dict = {"dateRange": date_range}
    if location:
        params["location"] = location
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://api.cloudflare.com/client/v4/radar/annotations/outages",
                params=params,
                headers={"Authorization": f"Bearer {CF_TOKEN}"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"Cloudflare anomaly request failed: {e}"}


@mcp.tool()
async def attack_summary(location: str = "", date_range: str = "7d") -> dict:
    """Cloudflare Radar DDoS/attack layer summary. location: country ISO2.
    Requires CF_API_TOKEN."""
    if not CF_TOKEN:
        return {"error": "CF_API_TOKEN not set"}
    params: dict = {"dateRange": date_range}
    if location:
        params["location"] = location
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://api.cloudflare.com/client/v4/radar/attacks/layer3/summary",
                params=params,
                headers={"Authorization": f"Bearer {CF_TOKEN}"})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"Cloudflare attack summary request failed: {e}"}


@mcp.tool()
async def ripe_probes(country: str = "", status: int = 1,
                       limit: int = 50) -> dict:
    """RIPE Atlas network probes. country: ISO2, status: 1=connected,
    2=disconnected, 3=abandoned. No API key needed for reads."""
    params: dict = {"limit": limit, "status": status}
    if country:
        params["country_code"] = country
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://atlas.ripe.net/api/v2/probes/", params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"RIPE Atlas probes request failed: {e}"}


@mcp.tool()
async def ripe_measurements(country: str = "", type: str = "",
                              status: int = 2, limit: int = 20) -> dict:
    """RIPE Atlas public measurements. type: ping, traceroute, dns, sslcert, ntp.
    status: 1=specified, 2=ongoing, 4=stopped. No API key for public data."""
    params: dict = {"limit": limit, "status": status, "is_public": True}
    if country:
        params["target_cc"] = country
    if type:
        params["type"] = type
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://atlas.ripe.net/api/v2/measurements/",
                            params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"RIPE Atlas measurements request failed: {e}"}


@mcp.tool()
async def ioda_outages(entity_type: str = "country", entity_code: str = "",
                        hours: int = 24, limit: int = 50) -> dict:
    """IODA internet outage events. entity_type: country, region, asn.
    entity_code: ISO2 country or ASN number. Free, no API key needed."""
    now = int(time.time())
    since = now - (hours * 3600)
    params: dict = {"from": since, "until": now, "limit": limit,
                    "entityType": entity_type}
    if entity_code:
        params["entityCode"] = entity_code
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events",
                params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"IODA outage events request failed: {e}"}


@mcp.tool()
async def ioda_alerts(entity_type: str = "country", entity_code: str = "",
                       hours: int = 24) -> dict:
    """IODA raw outage alerts. entity_type: country, region, asn.
    datasource: bgp, ping-slash24, gtr, merit-nt. Free, no API key."""
    now = int(time.time())
    since = now - (hours * 3600)
    params: dict = {"from": since, "until": now, "entityType": entity_type}
    if entity_code:
        params["entityCode"] = entity_code
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(
                "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts",
                params=params)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return {"error": f"IODA alerts request failed: {e}"}


# ── Aggregation ──────────────────────────────────────────


@mcp.tool()
async def internet_health(country: str = "") -> dict:
    """Internet health overview for a country. Combines Cloudflare Radar traffic,
    IODA outage events, and RIPE Atlas probe status. country: ISO2."""
    results: dict = {}
    if CF_TOKEN and country:
        try:
            results["traffic"] = await internet_traffic(
                location=country, date_range="1d")
        except Exception as e:
            results["traffic"] = {"error": str(e)}
    if country:
        try:
            results["outages"] = await ioda_outages(
                entity_type="country", entity_code=country, hours=24)
        except Exception as e:
            results["outages"] = {"error": str(e)}
        try:
            results["probes"] = await ripe_probes(country=country, limit=10)
        except Exception as e:
            results["probes"] = {"error": str(e)}
    sources = ["IODA", "RIPE Atlas"]
    if CF_TOKEN:
        sources.insert(0, "Cloudflare Radar")
    results["_meta"] = {"country": country, "sources": sources}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

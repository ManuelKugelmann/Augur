"""Internet Infrastructure — Cloudflare Radar, RIPE Atlas, IODA outages."""
from fastmcp import FastMCP
from _http import api_get, api_multi
import os
import time
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("infra", instructions="Internet traffic, network probes, outage detection")
CF_TOKEN = os.environ.get("CF_API_TOKEN", "")


# ── Cloudflare Radar (shared pattern) ──

async def _cf_radar(endpoint: str, location: str, date_range: str,
                    label: str) -> dict:
    """Shared Cloudflare Radar query."""
    if not CF_TOKEN:
        return {"error": "CF_API_TOKEN not set"}
    params: dict = {"dateRange": date_range}
    if location:
        params["location"] = location
    return await api_get(
        f"https://api.cloudflare.com/client/v4/radar/{endpoint}",
        params=params, headers={"Authorization": f"Bearer {CF_TOKEN}"},
        label=label)


@mcp.tool()
async def internet_traffic(location: str = "", date_range: str = "7d") -> dict:
    """Cloudflare Radar HTTP traffic summary. location: country ISO2 (e.g. US, DE).
    date_range: 1d, 7d, 14d, 28d. Requires CF_API_TOKEN."""
    return await _cf_radar("http/summary/http_protocol", location, date_range,
                           "Cloudflare Radar")


@mcp.tool()
async def traffic_anomalies(location: str = "", date_range: str = "7d") -> dict:
    """Cloudflare Radar traffic anomalies. location: country ISO2.
    Detects unusual traffic patterns. Requires CF_API_TOKEN."""
    return await _cf_radar("annotations/outages", location, date_range,
                           "Cloudflare anomaly")


@mcp.tool()
async def attack_summary(location: str = "", date_range: str = "7d") -> dict:
    """Cloudflare Radar DDoS/attack layer summary. location: country ISO2.
    Requires CF_API_TOKEN."""
    return await _cf_radar("attacks/layer3/summary", location, date_range,
                           "Cloudflare attack summary")


# ── RIPE Atlas ──

@mcp.tool()
async def ripe_probes(country: str = "", status: int = 1,
                       limit: int = 50) -> dict:
    """RIPE Atlas network probes. country: ISO2, status: 1=connected,
    2=disconnected, 3=abandoned. No API key needed for reads."""
    params: dict = {"limit": limit, "status": status}
    if country:
        params["country_code"] = country
    return await api_get("https://atlas.ripe.net/api/v2/probes/",
                         params=params, label="RIPE Atlas probes")


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
    return await api_get("https://atlas.ripe.net/api/v2/measurements/",
                         params=params, label="RIPE Atlas measurements")


# ── IODA (shared time-window pattern) ──

async def _ioda_query(endpoint: str, entity_type: str, entity_code: str,
                      hours: int, **extra_params) -> dict:
    """Shared IODA query with time window."""
    now = int(time.time())
    since = now - (hours * 3600)
    params: dict = {"from": since, "until": now, "entityType": entity_type,
                    **extra_params}
    if entity_code:
        params["entityCode"] = entity_code
    return await api_get(
        f"https://api.ioda.inetintel.cc.gatech.edu/v2/outages/{endpoint}",
        params=params, label=f"IODA {endpoint}")


@mcp.tool()
async def ioda_outages(entity_type: str = "country", entity_code: str = "",
                        hours: int = 24, limit: int = 50) -> dict:
    """IODA internet outage events. entity_type: country, region, asn.
    entity_code: ISO2 country or ASN number. Free, no API key needed."""
    return await _ioda_query("events", entity_type, entity_code, hours,
                             limit=limit)


@mcp.tool()
async def ioda_alerts(entity_type: str = "country", entity_code: str = "",
                       hours: int = 24) -> dict:
    """IODA raw outage alerts. entity_type: country, region, asn.
    datasource: bgp, ping-slash24, gtr, merit-nt. Free, no API key."""
    return await _ioda_query("alerts", entity_type, entity_code, hours)


# ── Aggregation ──────────────────────────────────────────


@mcp.tool()
async def internet_health(country: str = "") -> dict:
    """Internet health overview for a country. Combines Cloudflare Radar traffic,
    IODA outage events, and RIPE Atlas probe status. country: ISO2."""
    calls: dict = {}
    if CF_TOKEN and country:
        calls["traffic"] = internet_traffic(location=country, date_range="1d")
    if country:
        calls["outages"] = ioda_outages(
            entity_type="country", entity_code=country, hours=24)
        calls["probes"] = ripe_probes(country=country, limit=10)
    results = await api_multi(calls)
    sources = ["IODA", "RIPE Atlas"]
    if CF_TOKEN:
        sources.insert(0, "Cloudflare Radar")
    results["_meta"] = {"country": country, "sources": sources}
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")

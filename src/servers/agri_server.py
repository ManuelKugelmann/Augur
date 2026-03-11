"""Agriculture — FAOSTAT + USDA NASS."""
from fastmcp import FastMCP
from _http import api_get
import httpx
import os
from dotenv import load_dotenv
load_dotenv()

mcp = FastMCP("agri", instructions="FAO global agriculture + USDA crop data")
# FAOSTAT migrated from fenixservices to faostatservices (2025).
# Try new endpoint first, fall back to old if unavailable.
_FAOSTAT_URLS = [
    "https://faostatservices.fao.org/api/v1/en",
    "https://fenixservices.fao.org/faostat/api/v1/en",
]
NASS_KEY = os.environ.get("USDA_NASS_API_KEY", "")


async def _fao_get(path: str, params: dict | None = None) -> httpx.Response:
    """Try FAOSTAT endpoints in order, return first successful response."""
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=30) as c:
        for base in _FAOSTAT_URLS:
            try:
                r = await c.get(f"{base}/{path}", params=params)
                r.raise_for_status()
                return r
            except httpx.HTTPError as e:
                last_exc = e
                continue
    raise last_exc  # type: ignore[misc]


@mcp.tool()
async def fao_datasets() -> dict:
    """List FAOSTAT dataset codes (QCL=crops, TP=trade, PP=prices)."""
    try:
        r = await _fao_get("definitions/domain")
        data = r.json().get("data", [])
        return {"datasets": [{"code": d["code"], "label": d["label"]} for d in data]}
    except httpx.HTTPError as e:
        return {"error": f"FAOSTAT request failed: {e}"}


@mcp.tool()
async def fao_data(domain: str = "QCL", area: str = "5000>",
                    item: str = "15", element: str = "5510",
                    year: str = "2020,2021,2022,2023") -> dict:
    """FAOSTAT data. item: 15=wheat, 56=maize, 27=rice, 236=soybean.
    element: 5510=production, 5312=area, 5419=yield."""
    try:
        r = await _fao_get(f"data/{domain}", params={
            "area": area, "item": item, "element": element, "year": year,
            "output_type": "objects"})
        return r.json()
    except httpx.HTTPError as e:
        return {"error": f"FAOSTAT request failed: {e}"}


# ── USDA NASS (shared endpoint, different stat category) ──

async def _usda_nass(commodity: str, year: int,
                     statisticcat: str, **extra) -> dict:
    """Shared USDA NASS query."""
    if not NASS_KEY:
        return {"error": "USDA_NASS_API_KEY not set"}
    params = {"key": NASS_KEY, "commodity_desc": commodity.upper(),
              "year": year, "statisticcat_desc": statisticcat,
              "format": "json", **extra}
    return await api_get("https://quickstats.nass.usda.gov/api/api_GET/",
                         params=params, label="USDA NASS")


@mcp.tool()
async def usda_crop(commodity: str, year: int = 2025,
                     state: str = "US TOTAL") -> dict:
    """USDA crop production. commodity: CORN, SOYBEANS, WHEAT, etc."""
    return await _usda_nass(
        commodity, year, "PRODUCTION",
        agg_level_desc="NATIONAL" if state == "US TOTAL" else "STATE")


@mcp.tool()
async def usda_crop_progress(commodity: str, year: int = 2025) -> dict:
    """Weekly crop progress (planted/emerged/harvested %)."""
    return await _usda_nass(commodity, year, "PROGRESS", source_desc="SURVEY")


if __name__ == "__main__":
    mcp.run(transport="stdio")

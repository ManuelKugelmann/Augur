"""Health — WHO GHO, WHO Outbreaks, disease.sh, OpenFDA."""
import logging
from fastmcp import FastMCP
from _http import api_get
import httpx
import re

log = logging.getLogger("augur.health")

mcp = FastMCP("health", instructions="Global health, disease outbreaks, FDA data")

_SAFE_ODATA = re.compile(r'^[A-Za-z0-9_-]+$')
_SAFE_COUNTRY = re.compile(r'^[A-Za-z0-9 -]+$')


@mcp.tool()
async def who_indicator(indicator: str = "NCDMORT3070",
                        country: str = "", year: str = "") -> dict:
    """WHO health indicator. Examples: WHOSIS_000001 (life expectancy),
    MDG_0000000001 (under-5 mortality), WHS4_100 (hospital beds),
    NCD_BMI_30A (obesity)."""
    if not _SAFE_ODATA.match(indicator):
        return {"error": "invalid indicator code"}
    params = {}
    filters = []
    if country:
        if not _SAFE_ODATA.match(country):
            return {"error": "invalid country code"}
        filters.append(f"SpatialDim eq '{country}'")
    if year:
        if not _SAFE_ODATA.match(year):
            return {"error": "invalid year"}
        filters.append(f"TimeDim eq {year}")
    if filters:
        params["$filter"] = " and ".join(filters)
    return await api_get(f"https://ghoapi.azureedge.net/api/{indicator}",
                         params=params, timeout=15, label="WHO GHO")


@mcp.tool()
async def disease_outbreaks(limit: int = 20) -> dict:
    """Latest WHO Disease Outbreak News."""
    return await api_get("https://www.who.int/api/news/diseaseoutbreaknews",
                         params={"sf_culture": "en", "$top": limit,
                                 "$orderby": "PublicationDate desc"},
                         label="WHO outbreaks")


@mcp.tool()
async def disease_tracker(disease: str = "covid", country: str = "") -> dict:
    """Real-time disease tracking (disease.sh). disease: covid/influenza."""
    if country and not _SAFE_COUNTRY.match(country):
        return {"error": "invalid country name (letters, spaces, digits only)"}
    if disease not in ("covid", "influenza"):
        return {"error": "disease must be 'covid' or 'influenza'"}
    if disease == "covid":
        url = f"https://disease.sh/v3/covid-19/{'countries/' + country if country else 'all'}"
    else:
        url = f"https://disease.sh/v3/influenza/{'ihsa/country/' + country if country else 'ihsa'}"
    return await api_get(url, label="disease.sh")


@mcp.tool()
async def fda_adverse_events(drug: str = "", limit: int = 20) -> dict:
    """FDA adverse drug event reports."""
    if drug and not _SAFE_COUNTRY.match(drug):
        return {"error": "invalid drug name (letters, spaces, digits only)"}
    safe_drug = drug.replace('"', '') if drug else ""
    search = f'patient.drug.medicinalproduct:"{safe_drug}"' if safe_drug else ""
    return await api_get("https://api.fda.gov/drug/event.json",
                         params={"search": search, "limit": limit},
                         label="OpenFDA")


if __name__ == "__main__":
    mcp.run(transport="stdio")

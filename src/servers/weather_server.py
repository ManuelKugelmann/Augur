"""Weather & Climate — Open-Meteo forecasts + NOAA SWPC space weather."""
from fastmcp import FastMCP
from _http import api_get
import httpx
import logging

log = logging.getLogger("augur.weather")

mcp = FastMCP("weather", instructions="Weather forecasts, historical climate, space weather")


@mcp.tool()
async def forecast(lat: float, lon: float, days: int = 7) -> dict:
    """Weather forecast (daily temp, precip, wind)."""
    return await api_get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "forecast_days": days,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
        "timezone": "auto"}, label="Open-Meteo forecast")


@mcp.tool()
async def historical_weather(lat: float, lon: float,
                              start: str = "2024-01-01",
                              end: str = "2024-12-31") -> dict:
    """Historical weather since 1940. start/end: YYYY-MM-DD."""
    return await api_get("https://archive-api.open-meteo.com/v1/archive", params={
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "auto"}, label="Open-Meteo archive")


@mcp.tool()
async def flood_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """River discharge forecast (flood risk)."""
    return await api_get("https://flood-api.open-meteo.com/v1/flood", params={
        "latitude": lat, "longitude": lon, "forecast_days": days,
        "daily": "river_discharge"}, label="Open-Meteo flood")


@mcp.tool()
async def space_weather() -> dict:
    """Space weather: Kp index, solar wind, geomagnetic storms (NOAA SWPC)."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            kp = await c.get("https://services.swpc.noaa.gov/json/planetary_k_index_1m.json")
            solar = await c.get("https://services.swpc.noaa.gov/json/solar_wind/plasma-7-day.json")
            alerts = await c.get("https://services.swpc.noaa.gov/json/alerts.json")
            return {
                "kp_index": kp.json()[-5:] if kp.status_code == 200 else [],
                "solar_wind": solar.json()[-5:] if solar.status_code == 200 else [],
                "alerts": alerts.json()[:10] if alerts.status_code == 200 else [],
            }
    except httpx.HTTPError as e:
        return {"error": f"NOAA SWPC request failed: {e}"}


if __name__ == "__main__":
    mcp.run(transport="stdio")

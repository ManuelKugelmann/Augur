"""Shared HTTP helpers for domain servers."""
import time
import httpx


async def api_get(url: str, *, params: dict | None = None,
                  headers: dict | None = None, timeout: int = 30,
                  label: str = "API") -> dict:
    """GET JSON from url, return parsed dict or {"error": ...}."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"{label} request failed: {type(e).__name__}: {e}"}


async def api_post(url: str, *, json: dict | None = None,
                   data: dict | None = None, params: dict | None = None,
                   headers: dict | None = None, timeout: int = 30,
                   label: str = "API") -> dict:
    """POST and return parsed JSON or {"error": ...}."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=json, data=data, params=params,
                             headers=headers)
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"{label} request failed: {type(e).__name__}: {e}"}


async def api_multi(calls: dict) -> dict:
    """Run multiple async callables concurrently, capture errors per key.

    calls: {"streamflow": coroutine_or_callable, "drought": ...}
    Returns: {"streamflow": result_or_error, "drought": ...}
    """
    import asyncio

    keys = list(calls.keys())
    coros = list(calls.values())

    raw = await asyncio.gather(*coros, return_exceptions=True)

    results: dict = {}
    for key, val in zip(keys, raw):
        if isinstance(val, Exception):
            results[key] = {"error": str(val)}
        else:
            results[key] = val
    return results


class OAuthToken:
    """Reusable OAuth2 client-credentials token cache with expiry."""

    def __init__(self, token_url: str, client_id: str,
                 client_secret: str = "", margin: int = 60):
        self._url = token_url
        self._client_id = client_id
        self._secret = client_secret
        self._margin = margin
        self._token: str = ""
        self._exp: float = 0

    async def headers(self) -> dict:
        """Return Authorization header, refreshing if needed."""
        if not self._client_id:
            return {}
        if self._token and time.time() < self._exp:
            return {"Authorization": f"Bearer {self._token}"}
        try:
            token_data: dict = {"grant_type": "client_credentials",
                                "client_id": self._client_id}
            if self._secret:
                token_data["client_secret"] = self._secret
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(self._url, data=token_data)
                r.raise_for_status()
                data = r.json()
                self._token = data["access_token"]
                self._exp = time.time() + data.get("expires_in", 1800) - self._margin
                return {"Authorization": f"Bearer {self._token}"}
        except (httpx.HTTPError, KeyError):
            return {}

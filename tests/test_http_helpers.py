"""Tests for _http.py — api_get, api_post, OAuthToken."""
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("httpx", reason="httpx required for _http tests")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "servers"))


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp)
    return resp


def _patch_httpx(response):
    client = AsyncMock()
    client.get.return_value = response
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=client), client


# ── api_get ──────────────────────────────────────


class TestApiGet:
    @pytest.mark.asyncio
    async def test_success_returns_json(self):
        from _http import api_get
        resp = _mock_response({"result": "ok"})
        patcher, client = _patch_httpx(resp)
        with patcher:
            result = await api_get("https://example.com/api", params={"q": "test"})
        assert result == {"result": "ok"}
        client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_error_returns_error_dict(self):
        from _http import api_get
        resp = _mock_response({}, status_code=500)
        patcher, _ = _patch_httpx(resp)
        with patcher:
            result = await api_get("https://example.com/api", label="TestAPI")
        assert "error" in result
        assert "TestAPI" in result["error"]

    @pytest.mark.asyncio
    async def test_custom_headers_and_timeout(self):
        from _http import api_get
        resp = _mock_response({"ok": True})
        patcher, client = _patch_httpx(resp)
        with patcher:
            await api_get("https://example.com/api",
                         headers={"Authorization": "Bearer tok"},
                         timeout=60)
        call_kwargs = client.get.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer tok"


# ── api_post ─────────────────────────────────────


class TestApiPost:
    @pytest.mark.asyncio
    async def test_success_returns_json(self):
        from _http import api_post
        resp = _mock_response({"created": True})
        patcher, client = _patch_httpx(resp)
        with patcher:
            result = await api_post("https://example.com/api",
                                    json={"name": "test"})
        assert result == {"created": True}
        client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_error_returns_error_dict(self):
        from _http import api_post
        resp = _mock_response({}, status_code=403)
        patcher, _ = _patch_httpx(resp)
        with patcher:
            result = await api_post("https://example.com/api", label="PostAPI")
        assert "error" in result
        assert "PostAPI" in result["error"]

    @pytest.mark.asyncio
    async def test_data_and_params_passed(self):
        from _http import api_post
        resp = _mock_response({"ok": True})
        patcher, client = _patch_httpx(resp)
        with patcher:
            await api_post("https://example.com/api",
                          data={"grant_type": "client_credentials"},
                          params={"appname": "test"})
        call_kwargs = client.post.call_args[1]
        assert call_kwargs["data"]["grant_type"] == "client_credentials"
        assert call_kwargs["params"]["appname"] == "test"


# ── OAuthToken ───────────────────────────────────


class TestOAuthToken:
    @pytest.mark.asyncio
    async def test_empty_client_id_returns_empty(self):
        from _http import OAuthToken
        token = OAuthToken("https://auth.example.com/token", client_id="")
        result = await token.headers()
        assert result == {}

    @pytest.mark.asyncio
    async def test_fetches_and_caches_token(self):
        from _http import OAuthToken
        resp = _mock_response({"access_token": "tok123", "expires_in": 3600})
        patcher, client = _patch_httpx(resp)
        token = OAuthToken("https://auth.example.com/token",
                          client_id="my-id", client_secret="my-secret")
        with patcher:
            headers1 = await token.headers()
            # Second call should use cache (no new HTTP request)
            headers2 = await token.headers()
        assert headers1 == {"Authorization": "Bearer tok123"}
        assert headers2 == {"Authorization": "Bearer tok123"}
        # Only one HTTP call (cached on second)
        assert client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        from _http import OAuthToken
        resp = _mock_response({}, status_code=401)
        patcher, _ = _patch_httpx(resp)
        token = OAuthToken("https://auth.example.com/token", client_id="id")
        with patcher:
            result = await token.headers()
        assert result == {}

    @pytest.mark.asyncio
    async def test_expired_token_refetches(self):
        from _http import OAuthToken
        resp = _mock_response({"access_token": "new-tok", "expires_in": 3600})
        patcher, client = _patch_httpx(resp)
        token = OAuthToken("https://auth.example.com/token",
                          client_id="id", margin=60)
        # Simulate expired token
        token._token = "old-tok"
        token._exp = time.time() - 10  # expired
        with patcher:
            headers = await token.headers()
        assert headers == {"Authorization": "Bearer new-tok"}
        client.post.assert_called_once()

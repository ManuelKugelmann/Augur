"""MCP Gateway — wraps `claude mcp serve` with GitHub OAuth + HTTP transport.

Bridges:  claude mcp serve (stdio) -> FastMCP proxy (Streamable HTTP + OAuth)
Result:   Claude.ai gets direct Bash/Read/Write/Edit/Grep on the server.
"""
import os
import warnings

import httpx
from dotenv import load_dotenv
from fastmcp.server import create_proxy
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth import TokenVerifier

load_dotenv()


class GitHubUserFilter(TokenVerifier):
    """Restrict access to specific GitHub usernames."""

    def __init__(self, allowed_users: list[str]):
        super().__init__()
        self.allowed = {u.lower() for u in allowed_users}

    async def verify_token(self, token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            user = resp.json()
        if user["login"].lower() not in self.allowed:
            raise ValueError(f"User {user['login']} not in allowlist")
        return {"sub": user["login"], "name": user.get("name", "")}


def _get_auth():
    """GitHub OAuth via FastMCP's built-in GitHubProvider."""
    client_id = os.environ.get("GH_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GH_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        warnings.warn("No OAuth credentials — running WITHOUT auth", stacklevel=2)
        return None

    allowed = [
        u.strip()
        for u in os.environ.get("ALLOWED_GITHUB_USERS", "").split(",")
        if u.strip()
    ]

    provider = GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=os.environ.get(
            "GATEWAY_BASE_URL", "https://mcp.assist.uber.space"
        ),
        token_verifier=GitHubUserFilter(allowed) if allowed else None,
    )
    if not allowed:
        warnings.warn(
            "ALLOWED_GITHUB_USERS not set — any GitHub user can connect",
            stacklevel=2,
        )
    return provider


# Wrap claude mcp serve (stdio) as an HTTP proxy with OAuth.
# NOTE: create_proxy() does NOT accept plain command strings — use a config dict.
# A string like "claude mcp serve" would fail infer_transport() with ValueError.
proxy = create_proxy(
    {
        "mcpServers": {
            "claude-code": {
                "command": "claude",
                "args": ["mcp", "serve"],
                "transport": "stdio",
            }
        }
    },
    name="TradingAssistant Gateway",
    auth=_get_auth(),
)

if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", "8070"))
    proxy.run(transport="streamable-http", host="0.0.0.0", port=port)

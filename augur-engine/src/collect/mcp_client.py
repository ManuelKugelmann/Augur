"""MCP client wrapper — connects to MCP servers and exposes tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastmcp import Client

from ..config.types import McpEndpoint

log = logging.getLogger("augur.mcp")


@dataclass
class McpTool:
    """An MCP tool available for the agent to call."""
    name: str
    description: str
    input_schema: dict
    endpoint: McpEndpoint


async def discover_tools(endpoints: list[McpEndpoint]) -> list[McpTool]:
    """Connect to all MCP endpoints and discover available tools."""
    tools: list[McpTool] = []

    for ep in endpoints:
        try:
            async with Client(ep.url) as client:
                mcp_tools = await client.list_tools()
                for t in mcp_tools:
                    tools.append(McpTool(
                        name=t.name,
                        description=t.description or "",
                        input_schema=t.inputSchema if hasattr(t, "inputSchema") else {},
                        endpoint=ep,
                    ))
            log.info("discovered %d tools from %s (%s)", len(mcp_tools), ep.name, ep.url)
        except Exception as exc:
            log.warning("failed to connect to %s (%s): %s", ep.name, ep.url, exc)

    return tools


async def call_tool(endpoint: McpEndpoint, name: str, arguments: dict[str, Any]) -> Any:
    """Call a single MCP tool and return the result."""
    async with Client(endpoint.url) as client:
        result = await client.call_tool(name, arguments)
        # Extract text content from the result
        if hasattr(result, "content") and result.content:
            texts = []
            for block in result.content:
                if hasattr(block, "text"):
                    texts.append(block.text)
            return "\n".join(texts) if texts else str(result)
        return str(result)


def tools_to_anthropic_format(tools: list[McpTool]) -> list[dict]:
    """Convert MCP tools to Anthropic API tool definitions."""
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]

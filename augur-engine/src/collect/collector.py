"""Agentic signal collector — Claude uses MCP tools to research, like plan generation."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

from ..config.types import BrandConfig, HorizonKey, Signal
from ..config.horizons import compute_fictive_date, SECTION_LABELS
from .mcp_client import (
    McpTool,
    call_tool,
    discover_tools,
    tools_to_anthropic_format,
)

log = logging.getLogger("augur.collect")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
MAX_TOOL_ROUNDS = 10
MIN_SIGNALS = 3


def _research_system_prompt(brand: BrandConfig, horizon: HorizonKey) -> str:
    """System prompt for the agentic research phase."""
    fictive_date = compute_fictive_date(horizon)
    labels = SECTION_LABELS[brand.locale]
    lang = "German" if brand.locale == "de" else "English"

    return f"""You are a research agent for {brand.name}, collecting signals for a prediction article.

Your job: use the available tools to gather concrete, current data points that will feed a
"{labels['signal']}" → "{labels['extrapolation']}" → "{labels['in_the_works']}" prediction.

Horizon: {horizon} (fictive date: {fictive_date})
Language: {lang}

Research strategy:
{brand.research_prompt}

Rules:
- Make 3-8 tool calls to gather diverse data points
- Focus on the MOST significant current development
- Prefer tools that return quantitative data (numbers, dates, measurements)
- After gathering enough signals, respond with a summary of what you found
- Do NOT fabricate data — only report what the tools return
- If a tool call fails, try a different tool or different parameters"""


def _research_user_prompt(horizon: HorizonKey, locale: str) -> str:
    """User prompt to kick off the research phase."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    horizon_labels = {
        "en": {"tomorrow": "tomorrow", "soon": "next month", "future": "next year"},
        "de": {"tomorrow": "morgen", "soon": "nächsten Monat", "future": "nächstes Jahr"},
    }
    label = horizon_labels[locale][horizon]
    return (
        f"Current time: {now}\n"
        f"Research signals for a prediction about what will matter {label}. "
        f"Use the tools to gather real data, then summarize your findings."
    )


async def collect_signals(
    brand: BrandConfig,
    horizon: HorizonKey,
) -> list[Signal]:
    """Run the agentic research loop: Claude calls MCP tools to gather signals.

    Like plan generation — the LLM decides what data to fetch.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    model = os.environ.get("NEWS_MODEL", "claude-sonnet-4-5-20250514")

    # Step 1: Discover available MCP tools
    log.info("discovering MCP tools from %d endpoints...", len(brand.mcp_endpoints))
    mcp_tools = await discover_tools(brand.mcp_endpoints)
    if not mcp_tools:
        raise RuntimeError("No MCP tools available — check endpoint connectivity")
    log.info("discovered %d tools", len(mcp_tools))

    # Build tool name → McpTool lookup
    tool_map: dict[str, McpTool] = {t.name: t for t in mcp_tools}
    anthropic_tools = tools_to_anthropic_format(mcp_tools)

    # Step 2: Agentic loop — Claude decides what to query
    system = _research_system_prompt(brand, horizon)
    messages: list[dict] = [
        {"role": "user", "content": _research_user_prompt(horizon, brand.locale)},
    ]
    signals: list[Signal] = []

    for round_num in range(MAX_TOOL_ROUNDS):
        log.info("research round %d/%d...", round_num + 1, MAX_TOOL_ROUNDS)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                ANTHROPIC_API,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "system": system,
                    "messages": messages,
                    "tools": anthropic_tools,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Process response
        content = data.get("content", [])
        stop_reason = data.get("stop_reason", "end_turn")

        # Append assistant message
        messages.append({"role": "assistant", "content": content})

        # If no tool use, we're done researching
        if stop_reason != "tool_use":
            log.info(
                "research complete after %d rounds, %d signals",
                round_num + 1, len(signals),
            )
            break

        # Execute tool calls
        tool_results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tool_args = block.get("input", {})
            tool_id = block["id"]

            mcp_tool = tool_map.get(tool_name)
            if not mcp_tool:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Error: unknown tool {tool_name}",
                    "is_error": True,
                })
                continue

            try:
                result = await call_tool(mcp_tool.endpoint, tool_name, tool_args)
                result_str = (
                    result if isinstance(result, str)
                    else json.dumps(result, default=str)
                )

                # Truncate very long results
                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"

                signals.append(Signal(
                    tool=tool_name,
                    arguments=tool_args,
                    result=result_str,
                ))

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_str,
                })
                log.info("called %s → %d chars", tool_name, len(result_str))

            except Exception as exc:
                log.warning("tool %s failed: %s", tool_name, exc)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    return signals

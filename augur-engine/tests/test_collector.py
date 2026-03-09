"""Tests for the agentic collector and MCP client."""

from src.config.types import McpEndpoint
from src.collect.mcp_client import McpTool, tools_to_anthropic_format
from src.collect.collector import (
    _research_system_prompt,
    _research_user_prompt,
    MIN_SIGNALS,
)
from src.config.brands import BRANDS


class TestMcpToolConversion:
    def test_converts_to_anthropic_format(self):
        tools = [
            McpTool(
                name="weather_forecast",
                description="Get weather forecast",
                input_schema={
                    "type": "object",
                    "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                },
                endpoint=McpEndpoint(url="http://localhost:8071/mcp", name="trading"),
            ),
        ]
        result = tools_to_anthropic_format(tools)
        assert len(result) == 1
        assert result[0]["name"] == "weather_forecast"
        assert result[0]["description"] == "Get weather forecast"
        assert "properties" in result[0]["input_schema"]

    def test_handles_empty_tool_list(self):
        assert tools_to_anthropic_format([]) == []


class TestResearchPrompts:
    def test_system_prompt_includes_brand_name(self):
        prompt = _research_system_prompt(BRANDS["the"], "tomorrow")
        assert "The Augur" in prompt

    def test_system_prompt_includes_section_labels(self):
        prompt = _research_system_prompt(BRANDS["the"], "tomorrow")
        assert "The Signal" in prompt
        assert "The Extrapolation" in prompt

    def test_system_prompt_includes_research_strategy(self):
        prompt = _research_system_prompt(BRANDS["the"], "tomorrow")
        assert "geopolitical" in prompt

    def test_system_prompt_de_brand(self):
        prompt = _research_system_prompt(BRANDS["der"], "tomorrow")
        assert "German" in prompt
        assert "Der Augur" in prompt

    def test_system_prompt_financial_brand(self):
        prompt = _research_system_prompt(BRANDS["financial"], "tomorrow")
        assert "FRED" in prompt or "macro" in prompt

    def test_user_prompt_includes_horizon_en(self):
        prompt = _research_user_prompt("tomorrow", "en")
        assert "tomorrow" in prompt

    def test_user_prompt_includes_horizon_de(self):
        prompt = _research_user_prompt("tomorrow", "de")
        assert "morgen" in prompt

    def test_user_prompt_includes_timestamp(self):
        prompt = _research_user_prompt("tomorrow", "en")
        assert "UTC" in prompt


class TestMinSignals:
    def test_min_signals_is_reasonable(self):
        assert MIN_SIGNALS >= 1
        assert MIN_SIGNALS <= 10

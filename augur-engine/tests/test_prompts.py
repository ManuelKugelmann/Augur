"""Tests for LLM prompt construction."""

from src.config.brands import BRANDS
from src.extrapolate.prompts import (
    system_prompt_pass1,
    user_prompt_pass1,
    system_prompt_pass2,
    system_prompt_pass3,
)


class TestSystemPromptPass1:
    def test_includes_brand_tone_prompt(self):
        prompt = system_prompt_pass1(BRANDS["the"])
        assert "clear-eyed analyst" in prompt

    def test_includes_en_section_labels(self):
        prompt = system_prompt_pass1(BRANDS["the"])
        assert "The Signal" in prompt
        assert "The Extrapolation" in prompt
        assert "In The Works" in prompt

    def test_includes_de_section_labels(self):
        prompt = system_prompt_pass1(BRANDS["der"])
        assert "Das Signal" in prompt
        assert "Die Extrapolation" in prompt
        assert "In Arbeit" in prompt

    def test_requests_json_output(self):
        prompt = system_prompt_pass1(BRANDS["the"])
        assert "JSON" in prompt
        assert "headline" in prompt
        assert "tags" in prompt

    def test_includes_sentiment_for_financial(self):
        prompt = system_prompt_pass1(BRANDS["financial"])
        assert "sentiment_sector" in prompt
        assert "sentiment_direction" in prompt

    def test_excludes_sentiment_for_general(self):
        prompt = system_prompt_pass1(BRANDS["the"])
        assert "sentiment_sector" not in prompt

    def test_instructs_german_for_de(self):
        prompt = system_prompt_pass1(BRANDS["der"])
        assert "German" in prompt


class TestUserPromptPass1:
    def test_includes_horizon_label_en(self):
        prompt = user_prompt_pass1([{"test": True}], "tomorrow", "2026-03-10", "en")
        assert "Tomorrow" in prompt

    def test_includes_horizon_label_de(self):
        prompt = user_prompt_pass1([{"test": True}], "tomorrow", "2026-03-10", "de")
        assert "Morgen" in prompt

    def test_includes_fictive_date(self):
        prompt = user_prompt_pass1([], "tomorrow", "2026-03-10", "en")
        assert "2026-03-10" in prompt

    def test_includes_serialized_signals(self):
        signals = [{"source": "tavily", "data": "test data"}]
        prompt = user_prompt_pass1(signals, "tomorrow", "2026-03-10", "en")
        assert "tavily" in prompt
        assert "test data" in prompt


class TestSystemPromptPass2:
    def test_instructs_editorial_rewrite(self):
        prompt = system_prompt_pass2("en")
        assert "editor" in prompt
        assert "constructive" in prompt


class TestSystemPromptPass3:
    def test_includes_platform_names(self):
        prompt = system_prompt_pass3(["x", "bluesky"], "en")
        assert '"x"' in prompt
        assert '"bluesky"' in prompt

    def test_requires_disclaimer(self):
        prompt = system_prompt_pass3(["x"], "en")
        assert "AI-generated prediction" in prompt

    def test_requires_link_placeholder(self):
        prompt = system_prompt_pass3(["x"], "en")
        assert "[LINK]" in prompt

"""Tests for Jekyll publishing (markdown generation, file paths)."""

import pytest

from src.config.types import Prediction
from src.publish.jekyll import prediction_to_markdown, prediction_file_path


def make_prediction(**overrides) -> Prediction:
    defaults = dict(
        brand="the",
        horizon="tomorrow",
        date_key="2026-03-10",
        fictive_date="2026-03-10",
        created_at="2026-03-09T14:22:00Z",
        headline="Grid failures accelerate across three European regions",
        signal="European TSOs reported capacity margins below 5%.",
        extrapolation="If the blocking pattern holds, load-shedding becomes probable.",
        in_the_works="CATL Erfurt plant reached 14 GWh annual capacity.",
        sources=[{"title": "ENTSO-E Transparency Platform", "url": "https://transparency.entsoe.eu/"}],
        tags=["energy", "europe"],
        model="claude-sonnet-4-5-20250514",
    )
    defaults.update(overrides)
    return Prediction(**defaults)


class TestPredictionToMarkdown:
    def test_valid_front_matter_delimiters(self):
        md = prediction_to_markdown(make_prediction())
        assert md.startswith("---\n")
        parts = md.split("---")
        assert len(parts) >= 3

    def test_includes_headline(self):
        md = prediction_to_markdown(make_prediction())
        assert "headline:" in md
        assert "Grid failures" in md

    def test_includes_brand_and_horizon(self):
        md = prediction_to_markdown(make_prediction())
        assert 'brand: "the"' in md
        assert 'horizon: "tomorrow"' in md

    def test_en_section_headers(self):
        md = prediction_to_markdown(make_prediction(brand="the"))
        assert "## The Signal" in md
        assert "## The Extrapolation" in md
        assert "## In The Works" in md

    def test_de_section_headers(self):
        md = prediction_to_markdown(make_prediction(brand="der"))
        assert "## Das Signal" in md
        assert "## Die Extrapolation" in md
        assert "## In Arbeit" in md

    def test_includes_tags(self):
        md = prediction_to_markdown(make_prediction(tags=["energy", "europe"]))
        assert "tags:" in md
        assert '"energy"' in md
        assert '"europe"' in md

    def test_includes_sources(self):
        md = prediction_to_markdown(make_prediction())
        assert "sources:" in md
        assert "ENTSO-E" in md

    def test_includes_outcome_fields_as_null(self):
        md = prediction_to_markdown(make_prediction())
        assert "outcome:" in md
        assert "outcome_note:" in md
        assert "outcome_date:" in md

    def test_includes_sentiment_for_financial(self):
        md = prediction_to_markdown(make_prediction(
            brand="financial",
            sentiment_sector="semiconductors",
            sentiment_direction="bullish",
            sentiment_confidence=0.6,
        ))
        assert "sentiment_sector:" in md
        assert "semiconductors" in md
        assert "sentiment_direction:" in md
        assert "bullish" in md

    def test_includes_categories(self):
        md = prediction_to_markdown(make_prediction(brand="the", horizon="tomorrow"))
        assert 'categories: "the/tomorrow"' in md

    def test_uses_de_horizon_slug(self):
        md = prediction_to_markdown(make_prediction(brand="der", horizon="tomorrow"))
        assert 'categories: "der/morgen"' in md


class TestPredictionFilePath:
    def test_correct_path_for_en_brand(self):
        path = prediction_file_path(make_prediction(), "/site")
        assert "_posts/the/tomorrow/2026-03-10-" in path
        assert "grid-failures" in path
        assert path.endswith(".md")

    def test_uses_de_horizon_slug(self):
        path = prediction_file_path(
            make_prediction(brand="der", horizon="tomorrow"), "/site"
        )
        assert "_posts/der/morgen/" in path

    def test_slugifies_headline(self):
        path = prediction_file_path(
            make_prediction(headline="Hello World! 123"), "/site"
        )
        assert "hello-world-123" in path

    def test_truncates_long_slugs(self):
        path = prediction_file_path(
            make_prediction(headline="A" * 100 + " very long headline that should be truncated"),
            "/site",
        )
        filename = path.split("/")[-1]
        slug = filename.replace(".md", "")
        # Remove date prefix
        slug = slug[len("2026-03-10-"):]
        assert len(slug) <= 60

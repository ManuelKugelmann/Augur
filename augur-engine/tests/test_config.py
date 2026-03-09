"""Tests for brand config, horizons, and section labels."""

import re
from datetime import datetime

import pytest

from src.config.brands import BRANDS
from src.config.horizons import compute_fictive_date, SECTION_LABELS


BRAND_KEYS = ["the", "der", "financial", "finanz"]


class TestBrandsConfig:
    def test_has_all_4_brands(self):
        assert sorted(BRANDS.keys()) == sorted(BRAND_KEYS)

    @pytest.mark.parametrize("key", BRAND_KEYS)
    def test_brand_has_required_fields(self, key):
        brand = BRANDS[key]
        assert brand.name
        assert brand.slug == key
        assert brand.locale in ("en", "de")
        assert brand.module in ("general", "markets")
        assert brand.masthead
        assert brand.subtitle
        assert len(brand.horizons) == 3
        assert brand.palette.bg.startswith("#")
        assert brand.palette.ink.startswith("#")
        assert brand.palette.accent.startswith("#")
        assert brand.image_style_prefix
        assert brand.tone_prompt
        assert brand.legal_disclaimer
        assert len(brand.mcp_endpoints) > 0
        assert brand.research_prompt
        assert len(brand.social_targets) > 0

    def test_en_brands_have_en_locale(self):
        assert BRANDS["the"].locale == "en"
        assert BRANDS["financial"].locale == "en"

    def test_de_brands_have_de_locale(self):
        assert BRANDS["der"].locale == "de"
        assert BRANDS["finanz"].locale == "de"

    def test_financial_brands_have_markets_module(self):
        assert BRANDS["financial"].module == "markets"
        assert BRANDS["finanz"].module == "markets"

    def test_financial_brands_have_trade_system_feed(self):
        assert BRANDS["financial"].trade_system_feed
        assert BRANDS["finanz"].trade_system_feed

    def test_general_brands_no_trade_system_feed(self):
        assert BRANDS["the"].trade_system_feed is None
        assert BRANDS["der"].trade_system_feed is None

    def test_en_brands_have_en_horizon_slugs(self):
        slugs = [h.slug for h in BRANDS["the"].horizons]
        assert slugs == ["tomorrow", "soon", "future"]

    def test_de_brands_have_de_horizon_slugs(self):
        slugs = [h.slug for h in BRANDS["der"].horizons]
        assert slugs == ["morgen", "bald", "zukunft"]

    @pytest.mark.parametrize("key", BRAND_KEYS)
    def test_all_horizons_have_cron_expressions(self, key):
        for h in BRANDS[key].horizons:
            assert re.match(r"^[\d*/,\s]+$", h.refresh_cron)

    @pytest.mark.parametrize("key", BRAND_KEYS)
    def test_all_mcp_endpoints_have_url(self, key):
        for ep in BRANDS[key].mcp_endpoints:
            assert ep.url.startswith("http")
            assert ep.name


class TestComputeFictiveDate:
    anchor = datetime(2026, 3, 9, 12, 0, 0)

    def test_tomorrow_plus_1_day(self):
        assert compute_fictive_date("tomorrow", self.anchor) == "2026-03-10"

    def test_soon_plus_1_month(self):
        assert compute_fictive_date("soon", self.anchor) == "2026-04-09"

    def test_future_plus_1_year(self):
        assert compute_fictive_date("future", self.anchor) == "2027-03-09"

    def test_returns_yyyy_mm_dd_format(self):
        result = compute_fictive_date("tomorrow", self.anchor)
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result)


class TestSectionLabels:
    def test_has_en_labels(self):
        assert SECTION_LABELS["en"]["signal"] == "The Signal"
        assert SECTION_LABELS["en"]["extrapolation"] == "The Extrapolation"
        assert SECTION_LABELS["en"]["in_the_works"] == "In The Works"

    def test_has_de_labels(self):
        assert SECTION_LABELS["de"]["signal"] == "Das Signal"
        assert SECTION_LABELS["de"]["extrapolation"] == "Die Extrapolation"
        assert SECTION_LABELS["de"]["in_the_works"] == "In Arbeit"

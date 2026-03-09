"""Tests for the augur MCP server tools."""

import json
import os
import sys
from pathlib import Path

import pytest

# Add src/servers to path so we can import augur_server
_servers_dir = str(Path(__file__).resolve().parent.parent.parent / "src" / "servers")
if _servers_dir not in sys.path:
    sys.path.insert(0, _servers_dir)

from augur_server import (
    BRANDS,
    SCHEDULES,
    SECTION_LABELS,
    _is_due,
    _slugify,
    _to_yaml,
)


class TestBrandsConfig:
    def test_has_all_4_brands(self):
        assert sorted(BRANDS.keys()) == ["der", "financial", "finanz", "the"]

    @pytest.mark.parametrize("key", ["the", "der", "financial", "finanz"])
    def test_brand_has_required_fields(self, key):
        b = BRANDS[key]
        assert b["name"]
        assert b["locale"] in ("en", "de")
        assert b["module"] in ("general", "markets")
        assert b["masthead"]
        assert b["horizons"]
        assert b["image_prefix"]
        assert b["disclaimer"]

    def test_en_brands_have_en_locale(self):
        assert BRANDS["the"]["locale"] == "en"
        assert BRANDS["financial"]["locale"] == "en"

    def test_de_brands_have_de_locale(self):
        assert BRANDS["der"]["locale"] == "de"
        assert BRANDS["finanz"]["locale"] == "de"


class TestSectionLabels:
    def test_en_labels(self):
        assert SECTION_LABELS["en"]["signal"] == "The Signal"
        assert SECTION_LABELS["en"]["extrapolation"] == "The Extrapolation"
        assert SECTION_LABELS["en"]["in_the_works"] == "In The Works"

    def test_de_labels(self):
        assert SECTION_LABELS["de"]["signal"] == "Das Signal"
        assert SECTION_LABELS["de"]["extrapolation"] == "Die Extrapolation"
        assert SECTION_LABELS["de"]["in_the_works"] == "In Arbeit"


class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Hello! World? 123") == "hello-world-123"

    def test_truncation(self):
        result = _slugify("A" * 100, max_len=60)
        assert len(result) <= 60

    def test_strips_leading_trailing_dashes(self):
        assert _slugify("---hello---") == "hello"


class TestToYaml:
    def test_string_values(self):
        result = _to_yaml({"key": "value"})
        assert 'key: "value"' in result

    def test_null_values(self):
        result = _to_yaml({"key": None})
        assert "key:" in result
        assert "None" not in result

    def test_list_values(self):
        result = _to_yaml({"tags": ["a", "b"]})
        assert '"a"' in result
        assert '"b"' in result

    def test_numeric_values(self):
        result = _to_yaml({"count": 42})
        assert "count: 42" in result

    def test_nested_dict(self):
        result = _to_yaml({"outer": {"inner": "val"}})
        assert "outer:" in result
        assert 'inner: "val"' in result

    def test_sources_list(self):
        result = _to_yaml({"sources": [{"title": "Test", "url": "http://example.com"}]})
        assert "sources:" in result
        assert "Test" in result


class TestScheduling:
    def test_is_due_hourly_match(self):
        from datetime import datetime
        now = datetime(2026, 3, 9, 6, 5, 0)  # 06:05
        assert _is_due("0,6,12,18", now) is True

    def test_is_due_hourly_no_match(self):
        from datetime import datetime
        now = datetime(2026, 3, 9, 7, 5, 0)  # 07:05
        assert _is_due("0,6,12,18", now) is False

    def test_is_due_past_15_min(self):
        from datetime import datetime
        now = datetime(2026, 3, 9, 6, 20, 0)  # 06:20
        assert _is_due("0,6,12,18", now) is False

    def test_is_due_daily(self):
        from datetime import datetime
        now = datetime(2026, 3, 9, 2, 5, 0)  # 02:05
        assert _is_due("2", now) is True

    def test_is_due_weekly_monday(self):
        from datetime import datetime
        now = datetime(2026, 3, 9, 3, 5, 0)  # Monday 03:05
        assert now.weekday() == 0  # Monday
        assert _is_due("3/mon", now) is True

    def test_is_due_weekly_not_monday(self):
        from datetime import datetime
        now = datetime(2026, 3, 10, 3, 5, 0)  # Tuesday 03:05
        assert now.weekday() == 1  # Tuesday
        assert _is_due("3/mon", now) is False

    def test_all_brands_have_schedules(self):
        for brand in BRANDS:
            assert brand in SCHEDULES
            for horizon in ("tomorrow", "soon", "future"):
                assert horizon in SCHEDULES[brand]

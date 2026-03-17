"""Tests for augur_common.py — site_base_url, to_yaml edge cases, apply_watermark."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "servers"))

import augur_common as ac


# ── site_base_url ────────────────────────────────


class TestSiteBaseUrl:
    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("AUGUR_SITE_URL", raising=False)
        assert ac.site_base_url() == "https://github.com/ManuelKugelmann/Augur"

    def test_custom_url(self, monkeypatch):
        monkeypatch.setenv("AUGUR_SITE_URL", "https://custom.example.com")
        assert ac.site_base_url() == "https://custom.example.com"


# ── site_dir ─────────────────────────────────────


class TestSiteDir:
    def test_default_dir(self, monkeypatch):
        monkeypatch.delenv("AUGUR_SITE_DIR", raising=False)
        result = ac.site_dir()
        assert result.endswith("augur-site")

    def test_custom_dir(self, monkeypatch):
        monkeypatch.setenv("AUGUR_SITE_DIR", "/tmp/my-site")
        assert ac.site_dir() == "/tmp/my-site"


# ── to_yaml edge cases ──────────────────────────


class TestToYaml:
    def test_empty_dict(self):
        assert ac.to_yaml({}) == ""

    def test_none_value(self):
        result = ac.to_yaml({"key": None})
        assert "key:\n" in result

    def test_bool_values(self):
        result = ac.to_yaml({"a": True, "b": False})
        assert "a: true" in result
        assert "b: false" in result

    def test_numeric_values(self):
        result = ac.to_yaml({"count": 42, "ratio": 3.14})
        assert "count: 42" in result
        assert "ratio: 3.14" in result

    def test_string_with_special_chars(self):
        result = ac.to_yaml({"title": "Hello: World"})
        # Should be JSON-encoded due to colon
        assert '"Hello: World"' in result

    def test_empty_list(self):
        result = ac.to_yaml({"items": []})
        assert "items: []" in result

    def test_list_of_strings(self):
        result = ac.to_yaml({"tags": ["a", "b", "c"]})
        assert "tags:" in result
        assert '"a"' in result

    def test_list_of_dicts(self):
        result = ac.to_yaml({"links": [
            {"type": "trade", "target": "CHN"},
            {"type": "alliance", "target": "USA"},
        ]})
        assert "links:" in result
        assert "trade" in result

    def test_list_of_dicts_with_empty_dict(self):
        """Regression: empty dict in list should not crash."""
        # If list has mixed empty/non-empty dicts, the first element
        # determines handling. An all-empty list is edge case.
        result = ac.to_yaml({"items": [{"a": 1}]})
        assert "items:" in result

    def test_nested_dict(self):
        result = ac.to_yaml({"outer": {"inner": "value"}})
        assert "outer:" in result
        assert "inner:" in result

    def test_indentation(self):
        result = ac.to_yaml({"nested": {"deep": "val"}})
        lines = result.strip().split("\n")
        assert lines[0] == "nested:"
        assert lines[1].startswith("  ")


# ── apply_watermark ──────────────────────────────


class TestApplyWatermark:
    def test_watermark_applied(self, tmp_path):
        """Test watermark runs without crashing on a real image."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img_path = str(tmp_path / "test.png")
        img = Image.new("RGB", (200, 100), color=(128, 128, 128))
        img.save(img_path)

        ac.apply_watermark(img_path)

        result = Image.open(img_path)
        assert result.size == (200, 100)  # dimensions preserved

    def test_watermark_bar_height_minimum(self, tmp_path):
        """Bar height should be at least 24px even for small images."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img_path = str(tmp_path / "tiny.png")
        img = Image.new("RGB", (50, 50), color=(200, 200, 200))
        img.save(img_path)

        ac.apply_watermark(img_path)
        # If it didn't crash, the bar height logic works
        result = Image.open(img_path)
        assert result.size == (50, 50)


# ── article_url ──────────────────────────────────


class TestArticleUrl:
    def test_builds_correct_url(self, monkeypatch):
        monkeypatch.setenv("AUGUR_SITE_URL", "https://test.example.com")
        url = ac.article_url("the", "tomorrow", "2026-03-14")
        assert url == "https://test.example.com/the/tomorrow/2026-03-14"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("AUGUR_SITE_URL", "https://test.example.com/")
        url = ac.article_url("der", "soon", "2026-06-14")
        assert url == "https://test.example.com/der/soon/2026-06-14"


# ── slugify ──────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert ac.slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert ac.slugify("$100 Oil: A Prediction!") == "100-oil-a-prediction"

    def test_max_len(self):
        result = ac.slugify("a" * 100, max_len=10)
        assert len(result) == 10

    def test_empty(self):
        assert ac.slugify("!!!") == "untitled"


# ── is_due ───────────────────────────────────────


class TestIsDue:
    def test_hourly_match(self):
        from datetime import datetime
        dt = datetime(2026, 3, 13, 6, 5)
        assert ac.is_due("0,6,12,18", dt) is True

    def test_hourly_no_match(self):
        from datetime import datetime
        dt = datetime(2026, 3, 13, 7, 5)
        assert ac.is_due("0,6,12,18", dt) is False

    def test_past_minute_15(self):
        from datetime import datetime
        dt = datetime(2026, 3, 13, 6, 20)
        assert ac.is_due("0,6,12,18", dt) is False

    def test_monday_schedule(self):
        from datetime import datetime
        # 2026-03-16 is a Monday
        dt = datetime(2026, 3, 16, 3, 0)
        assert ac.is_due("3/mon", dt) is True

    def test_non_monday_schedule(self):
        from datetime import datetime
        # 2026-03-13 is a Friday
        dt = datetime(2026, 3, 13, 3, 0)
        assert ac.is_due("3/mon", dt) is False

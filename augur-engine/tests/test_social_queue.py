"""Tests for social queue file operations."""

import json
from pathlib import Path

import pytest

from src.config.types import Prediction
from src.config.brands import BRANDS
from src.publish.social_queue import queue_social_posts, read_pending_posts, move_post


def make_prediction(**overrides) -> Prediction:
    defaults = dict(
        brand="the",
        horizon="tomorrow",
        date_key="2026-03-10",
        fictive_date="2026-03-10",
        created_at="2026-03-09T14:22:00Z",
        headline="Test prediction",
        signal="Test signal.",
        extrapolation="Test extrapolation.",
        in_the_works="Test in the works.",
        sources=[],
        tags=["test"],
        model="test-model",
    )
    defaults.update(overrides)
    return Prediction(**defaults)


class TestSocialQueue:
    def test_queue_creates_pending_files(self, tmp_path):
        prediction = make_prediction()
        captions = {"x": "Test caption [LINK]", "bluesky": "Test BS [LINK]"}
        brand = BRANDS["the"]

        queue_social_posts(prediction, captions, brand, str(tmp_path))

        pending_dir = tmp_path / "_data" / "social" / "pending"
        files = list(pending_dir.glob("*.json"))
        # "the" brand has targets: x, bluesky, facebook
        # but only x and bluesky have captions
        assert len(files) == 2

    def test_queued_files_have_correct_structure(self, tmp_path):
        prediction = make_prediction()
        captions = {"x": "Test caption [LINK]"}
        brand = BRANDS["the"]

        queue_social_posts(prediction, captions, brand, str(tmp_path))

        pending_dir = tmp_path / "_data" / "social" / "pending"
        f = list(pending_dir.glob("*.json"))[0]
        data = json.loads(f.read_text())

        assert data["brand"] == "the"
        assert data["platform"] == "x"
        assert data["caption"] == "Test caption [LINK]"
        assert data["scheduled_at"]
        assert data["created_at"]

    def test_read_pending_returns_due_posts(self, tmp_path):
        prediction = make_prediction()
        captions = {"x": "Test [LINK]"}
        brand = BRANDS["the"]

        queue_social_posts(prediction, captions, brand, str(tmp_path))
        pending = read_pending_posts(str(tmp_path))
        # Posts scheduled at "now" should be due
        assert len(pending) >= 1

    def test_move_post_to_failed(self, tmp_path):
        prediction = make_prediction()
        captions = {"x": "Test [LINK]"}
        brand = BRANDS["the"]

        queue_social_posts(prediction, captions, brand, str(tmp_path))
        pending = read_pending_posts(str(tmp_path))
        path, entry = pending[0]

        move_post(path, entry, "failed", str(tmp_path), error="test error")

        # Should be gone from pending
        assert not Path(path).exists()
        # Should exist in failed
        failed_dir = tmp_path / "_data" / "social" / "failed"
        assert len(list(failed_dir.glob("*.json"))) == 1

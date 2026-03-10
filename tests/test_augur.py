"""Tests for augur_server.py — scorecard tools + helpers."""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def site_dir(tmp_path, monkeypatch):
    """Provide a temp augur site directory with _posts structure."""
    monkeypatch.setenv("AUGUR_SITE_DIR", str(tmp_path))
    return tmp_path


def _write_article(site: Path, brand: str, horizon: str, date_key: str,
                   headline: str, outcome=None, outcome_note=None,
                   outcome_date=None, confidence="medium", tags=None) -> Path:
    """Write a minimal Jekyll article with front matter."""
    slug = headline.lower().replace(" ", "-")[:40]
    horizon_slug = {"tomorrow": "tomorrow", "soon": "soon", "future": "future"}[horizon]
    post_dir = site / "_posts" / brand / horizon_slug
    post_dir.mkdir(parents=True, exist_ok=True)
    path = post_dir / f"{date_key}-{slug}.md"

    fm_lines = [
        "---",
        f'brand: "{brand}"',
        f'horizon: "{horizon}"',
        f'date: "{date_key}"',
        f'headline: "{headline}"',
        f'confidence: "{confidence}"',
    ]
    if tags:
        fm_lines.append(f"tags: {json.dumps(tags)}")
    if outcome:
        fm_lines.append(f'outcome: "{outcome}"')
    else:
        fm_lines.append("outcome:")
    if outcome_note:
        fm_lines.append(f'outcome_note: "{outcome_note}"')
    else:
        fm_lines.append("outcome_note:")
    if outcome_date:
        fm_lines.append(f'outcome_date: "{outcome_date}"')
    else:
        fm_lines.append("outcome_date:")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append("## The Signal\n\nSome signal text.")

    path.write_text("\n".join(fm_lines), encoding="utf-8")
    return path


def _run(coro):
    """Run async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def augur(site_dir):
    """Import augur_server after env is set."""
    # Remove cached module to pick up new AUGUR_SITE_DIR
    mod_key = "src.servers.augur_server"
    if mod_key in sys.modules:
        del sys.modules[mod_key]
    from src.servers import augur_server
    return augur_server


# ---------------------------------------------------------------------------
# _parse_front_matter
# ---------------------------------------------------------------------------

class TestParseFrontMatter:
    def test_basic_parse(self, augur):
        text = '---\nbrand: "the"\nhorizon: "tomorrow"\noutcome:\n---\n\nBody.'
        fm, body = augur._parse_front_matter(text)
        assert fm["brand"] == "the"
        assert fm["horizon"] == "tomorrow"
        assert fm["outcome"] is None
        assert "Body." in body

    def test_no_front_matter(self, augur):
        fm, body = augur._parse_front_matter("Just some text")
        assert fm == {}
        assert "Just some text" in body

    def test_numeric_values(self, augur):
        text = '---\nconfidence: 0.75\ncount: 5\n---\n'
        fm, _ = augur._parse_front_matter(text)
        assert fm["confidence"] == 0.75
        assert fm["count"] == 5

    def test_list_values(self, augur):
        text = '---\ntags: ["trade", "oil"]\n---\n'
        fm, _ = augur._parse_front_matter(text)
        assert fm["tags"] == ["trade", "oil"]

    def test_null_value(self, augur):
        text = '---\noutcome: null\n---\n'
        fm, _ = augur._parse_front_matter(text)
        assert fm["outcome"] is None


# ---------------------------------------------------------------------------
# _find_articles
# ---------------------------------------------------------------------------

class TestFindArticles:
    def test_find_all(self, augur, site_dir):
        _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Test One")
        _write_article(site_dir, "financial", "soon", "2026-03-02", "Test Two")
        result = augur._find_articles(str(site_dir))
        assert len(result) == 2

    def test_filter_by_brand(self, augur, site_dir):
        _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Test One")
        _write_article(site_dir, "financial", "soon", "2026-03-02", "Test Two")
        result = augur._find_articles(str(site_dir), brand="financial")
        assert len(result) == 1

    def test_filter_by_horizon(self, augur, site_dir):
        _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Test One")
        _write_article(site_dir, "the", "future", "2026-03-02", "Test Two")
        result = augur._find_articles(str(site_dir), horizon="future")
        assert len(result) == 1

    def test_empty_dir(self, augur, site_dir):
        result = augur._find_articles(str(site_dir))
        assert result == []


# ---------------------------------------------------------------------------
# score_prediction
# ---------------------------------------------------------------------------

class TestScorePrediction:
    def test_score_confirmed(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Oil Rises")
        result = _run(augur.score_prediction(str(path), "confirmed", "Oil rose 5%"))
        assert result["outcome"] == "confirmed"

        # Verify file was updated
        text = path.read_text(encoding="utf-8")
        assert '"confirmed"' in text
        assert '"Oil rose 5%"' in text

    def test_score_wrong(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Gold Falls")
        result = _run(augur.score_prediction(str(path), "wrong", "Gold actually rose"))
        assert result["outcome"] == "wrong"

    def test_score_partial(self, augur, site_dir):
        path = _write_article(site_dir, "the", "soon", "2026-03-01", "Mixed Signals")
        result = _run(augur.score_prediction(str(path), "partial"))
        assert result["outcome"] == "partial"

    def test_invalid_outcome(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Test")
        result = _run(augur.score_prediction(str(path), "maybe"))
        assert "error" in result

    def test_missing_file(self, augur, site_dir):
        result = _run(augur.score_prediction("/nonexistent/article.md", "confirmed"))
        assert "error" in result

    def test_relative_path(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Relative Test")
        rel = str(path.relative_to(site_dir))
        result = _run(augur.score_prediction(rel, "confirmed"))
        assert result["outcome"] == "confirmed"

    def test_outcome_date_set(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Date Test")
        result = _run(augur.score_prediction(str(path), "confirmed"))
        assert "outcome_date" in result
        # Should be today's date
        assert result["outcome_date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# list_pending_scores
# ---------------------------------------------------------------------------

class TestListPendingScores:
    def test_finds_unscored_past_horizon(self, augur, site_dir):
        # Article from 10 days ago, tomorrow horizon (2 day window) — should be pending
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", old_date, "Old Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 1
        assert result["pending"][0]["headline"] == "Old Prediction"

    def test_skips_recent_articles(self, augur, site_dir):
        # Article from today, tomorrow horizon — not yet scoreable
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", today, "Fresh Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 0

    def test_skips_already_scored(self, augur, site_dir):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", old_date, "Scored Already",
                       outcome="confirmed", outcome_date="2026-03-05")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 0

    def test_filter_by_brand(self, augur, site_dir):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", old_date, "The Article")
        _write_article(site_dir, "financial", "tomorrow", old_date, "Finance Article")
        result = _run(augur.list_pending_scores(brand="financial"))
        assert result["count"] == 1
        assert result["pending"][0]["brand"] == "financial"

    def test_respects_limit(self, augur, site_dir):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        for i in range(5):
            _write_article(site_dir, "the", "tomorrow", old_date, f"Article {i}")
        result = _run(augur.list_pending_scores(limit=2))
        assert result["count"] == 2

    def test_soon_horizon_needs_14_days(self, augur, site_dir):
        # 5 days ago with "soon" horizon (14 day window) — not yet scoreable
        date_5d = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "soon", date_5d, "Soon Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 0

        # 20 days ago — should be pending
        date_20d = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "soon", date_20d, "Old Soon Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# generate_scorecard
# ---------------------------------------------------------------------------

class TestGenerateScorecard:
    def test_empty_scorecard(self, augur, site_dir):
        result = _run(augur.generate_scorecard())
        assert result["summary"]["total"] == 0
        assert result["summary"]["accuracy"] is None

    def test_basic_scorecard(self, augur, site_dir):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", recent, "Confirmed One",
                       outcome="confirmed", outcome_date=recent)
        _write_article(site_dir, "the", "tomorrow", recent, "Wrong One",
                       outcome="wrong", outcome_date=recent)
        result = _run(augur.generate_scorecard())
        assert result["summary"]["total"] == 2
        assert result["summary"]["confirmed"] == 1
        assert result["summary"]["wrong"] == 1
        # accuracy = (1 + 0) / 2 = 0.5
        assert result["summary"]["accuracy"] == 0.5

    def test_partial_counts_half(self, augur, site_dir):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", recent, "Partial One",
                       outcome="partial", outcome_date=recent)
        _write_article(site_dir, "the", "tomorrow", recent, "Partial Two",
                       outcome="partial", outcome_date=recent)
        result = _run(augur.generate_scorecard())
        assert result["summary"]["total"] == 2
        assert result["summary"]["accuracy"] == 0.5

    def test_per_brand_breakdown(self, augur, site_dir):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", recent, "The Confirmed",
                       outcome="confirmed", outcome_date=recent)
        _write_article(site_dir, "financial", "soon", recent, "Finance Wrong",
                       outcome="wrong", outcome_date=recent)
        result = _run(augur.generate_scorecard())
        assert "the/tomorrow" in result["breakdown"]
        assert "financial/soon" in result["breakdown"]
        assert result["breakdown"]["the/tomorrow"]["accuracy"] == 1.0
        assert result["breakdown"]["financial/soon"]["accuracy"] == 0.0

    def test_excludes_old_articles(self, augur, site_dir):
        old = (datetime.now(timezone.utc) - timedelta(days=200)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", old, "Ancient Prediction",
                       outcome="confirmed", outcome_date=old)
        result = _run(augur.generate_scorecard(last_n_days=90))
        assert result["summary"]["total"] == 0

    def test_writes_scorecard_json(self, augur, site_dir):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", recent, "SC Test",
                       outcome="confirmed", outcome_date=recent)
        _run(augur.generate_scorecard())
        sc_file = site_dir / "_data" / "scorecard.json"
        assert sc_file.exists()
        data = json.loads(sc_file.read_text(encoding="utf-8"))
        assert data["summary"]["total"] == 1

    def test_streak_tracking(self, augur, site_dir):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        for i in range(3):
            _write_article(site_dir, "the", "tomorrow", recent, f"Win {i}",
                           outcome="confirmed", outcome_date=recent)
        result = _run(augur.generate_scorecard())
        assert result["summary"]["streak"] == 3
        assert result["summary"]["streak_type"] == "confirmed"

    def test_filter_by_brand(self, augur, site_dir):
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", recent, "The One",
                       outcome="confirmed", outcome_date=recent)
        _write_article(site_dir, "financial", "tomorrow", recent, "Fin One",
                       outcome="wrong", outcome_date=recent)
        result = _run(augur.generate_scorecard(brand="the"))
        assert result["summary"]["total"] == 1
        assert result["summary"]["confirmed"] == 1

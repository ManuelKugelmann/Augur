"""Tests for augur_server.py — scorecard + social posting tools."""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
# _compute_fictive_date + _article_url
# ---------------------------------------------------------------------------

class TestFictiveDate:
    def test_tomorrow_adds_3_days(self, augur):
        pub = datetime(2026, 3, 10, tzinfo=timezone.utc)
        assert augur._compute_fictive_date("tomorrow", pub) == "2026-03-13"

    def test_soon_adds_3_months(self, augur):
        pub = datetime(2026, 3, 10, tzinfo=timezone.utc)
        assert augur._compute_fictive_date("soon", pub) == "2026-06-10"

    def test_future_adds_3_years(self, augur):
        pub = datetime(2026, 3, 10, tzinfo=timezone.utc)
        assert augur._compute_fictive_date("future", pub) == "2029-03-10"

    def test_leap_adds_30_years(self, augur):
        pub = datetime(2026, 3, 10, tzinfo=timezone.utc)
        assert augur._compute_fictive_date("leap", pub) == "2056-03-10"

    def test_soon_month_overflow(self, augur):
        pub = datetime(2026, 11, 15, tzinfo=timezone.utc)
        # 11 + 3 = 14 → February next year
        assert augur._compute_fictive_date("soon", pub) == "2027-02-15"

    def test_soon_clamps_day_to_month_end(self, augur):
        # Jan 31 + 3 months → April 30 (not April 28)
        pub = datetime(2026, 1, 31, tzinfo=timezone.utc)
        assert augur._compute_fictive_date("soon", pub) == "2026-04-30"

    def test_soon_feb_leap_year(self, augur):
        # Nov 30 2027 + 3 months → Feb 28 2028 (2028 is leap year → Feb 29)
        pub = datetime(2027, 11, 30, tzinfo=timezone.utc)
        assert augur._compute_fictive_date("soon", pub) == "2028-02-29"


class TestYamlSerializer:
    def test_bool_serialized_correctly(self, augur):
        result = augur._to_yaml({"flag": True, "off": False})
        assert "flag: true" in result
        assert "off: false" in result

    def test_bool_not_serialized_as_int(self, augur):
        result = augur._to_yaml({"flag": True})
        assert "1" not in result


class TestArticleUrl:
    def test_basic_url(self, augur, monkeypatch):
        monkeypatch.setenv("AUGUR_SITE_URL", "https://augur.news")
        # Reload to pick up env
        mod_key = "src.servers.augur_server"
        if mod_key in sys.modules:
            del sys.modules[mod_key]
        from src.servers import augur_server as aug
        url = aug._article_url("the", "tomorrow", "2026-03-13")
        assert url == "https://augur.news/the/tomorrow/2026-03-13"


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
        assert result["revision"] == 1

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
        assert result["outcome_date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_rescore_updates_front_matter(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "Rescore Test")
        _run(augur.score_prediction(str(path), "partial", "Unclear"))
        result = _run(augur.score_prediction(str(path), "confirmed", "Now confirmed"))
        assert result["outcome"] == "confirmed"
        assert result["revision"] == 2
        text = path.read_text(encoding="utf-8")
        assert '"confirmed"' in text

    def test_rescore_preserves_history(self, augur, site_dir):
        path = _write_article(site_dir, "the", "tomorrow", "2026-03-01", "History Test")
        _run(augur.score_prediction(str(path), "partial", "First pass"))
        _run(augur.score_prediction(str(path), "wrong", "Second pass"))
        _run(augur.score_prediction(str(path), "confirmed", "Third pass"))

        log_path = path.with_suffix(".scores.json")
        assert log_path.exists()
        history = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(history) == 3
        assert history[0]["outcome"] == "partial"
        assert history[1]["outcome"] == "wrong"
        assert history[2]["outcome"] == "confirmed"
        assert history[2]["revision"] == 3


# ---------------------------------------------------------------------------
# list_pending_scores
# ---------------------------------------------------------------------------

class TestListPendingScores:
    def test_finds_unscored_past_horizon(self, augur, site_dir):
        # Article from 10 days ago, tomorrow horizon (3 day window) — should be pending
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", old_date, "Old Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 1
        assert result["pending"][0]["headline"] == "Old Prediction"
        assert result["pending"][0]["current_outcome"] is None
        assert result["pending"][0]["revision"] == 0

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

    def test_include_scored_for_rescoring(self, augur, site_dir):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", old_date, "Scored Already",
                       outcome="partial", outcome_date="2026-03-05")
        result = _run(augur.list_pending_scores(include_scored=True))
        assert result["count"] == 1
        assert result["pending"][0]["current_outcome"] == "partial"

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

    def test_soon_horizon_needs_90_days(self, augur, site_dir):
        # 5 days ago with "soon" horizon (90 day window) — not yet scoreable
        date_5d = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "soon", date_5d, "Soon Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 0

        # 100 days ago — should be pending
        date_100d = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "soon", date_100d, "Old Soon Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 1

    def test_tomorrow_needs_3_days(self, augur, site_dir):
        # 2 days ago — not yet scoreable
        date_2d = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        _write_article(site_dir, "the", "tomorrow", date_2d, "Two Day Prediction")
        result = _run(augur.list_pending_scores())
        assert result["count"] == 0

    def test_revision_count_in_listing(self, augur, site_dir):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        path = _write_article(site_dir, "the", "tomorrow", old_date, "Revisited")
        _run(augur.score_prediction(str(path), "partial"))
        result = _run(augur.list_pending_scores(include_scored=True))
        assert result["pending"][0]["revision"] == 1


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


# ---------------------------------------------------------------------------
# post_social
# ---------------------------------------------------------------------------

def _mock_httpx_response(status_code=200, json_data=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


class TestPostSocial:
    def test_unknown_platform(self, augur):
        result = _run(augur.post_social("the", "tiktok", "caption", "https://example.com"))
        assert "error" in result
        assert "tiktok" in result["error"]

    def test_bluesky_missing_creds(self, augur, monkeypatch):
        monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
        monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
        result = _run(augur.post_social("the", "bluesky", "test", "https://example.com"))
        assert "error" in result
        assert "BLUESKY" in result["error"]

    def test_mastodon_missing_creds(self, augur, monkeypatch):
        monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("MASTODON_INSTANCE", raising=False)
        result = _run(augur.post_social("the", "mastodon", "test", "https://example.com"))
        assert "error" in result
        assert "MASTODON" in result["error"]

    def test_manual_platform_missing_ntfy(self, augur, monkeypatch):
        monkeypatch.setattr(augur, "_NTFY_TOPIC", "")
        result = _run(augur.post_social("the", "x", "caption", "https://example.com"))
        assert "error" in result

    def test_bluesky_success(self, augur, monkeypatch):
        monkeypatch.setenv("BLUESKY_HANDLE", "test.bsky.social")
        monkeypatch.setenv("BLUESKY_APP_PASSWORD", "test-pass")

        session_resp = _mock_httpx_response(json_data={"accessJwt": "tok", "did": "did:plc:123"})
        post_resp = _mock_httpx_response(json_data={"uri": "at://did:plc:123/post/abc"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[session_resp, post_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(augur._post_bluesky("Test caption", "https://example.com/article"))

        assert result.get("posted") is True
        assert "uri" in result

    def test_mastodon_success(self, augur, monkeypatch):
        monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("MASTODON_INSTANCE", "https://mastodon.social")

        post_resp = _mock_httpx_response(json_data={"url": "https://mastodon.social/@test/123"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(augur._post_mastodon("Test caption", "https://example.com/article"))

        assert result.get("posted") is True
        assert "url" in result

    def test_manual_ntfy_success(self, augur, monkeypatch):
        monkeypatch.setattr(augur, "_NTFY_TOPIC", "test-topic")

        ntfy_resp = _mock_httpx_response()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=ntfy_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(augur._notify_manual_post(
                "x", "the", "Test caption", "https://example.com/article"))

        assert result.get("notified") is True
        assert result["platform"] == "x"

        # Verify ntfy was called with deep link headers
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers["Click"] == "https://example.com/article"
        assert "Open article" in headers["Actions"]

    def test_manual_platforms_route_to_ntfy(self, augur, monkeypatch):
        """All manual platforms should route through _notify_manual_post."""
        for platform in ("x", "facebook", "linkedin", "instagram"):
            assert platform in augur._MANUAL_PLATFORMS

    def test_auto_platforms_set(self, augur):
        """Bluesky and Mastodon should be auto-post platforms."""
        assert "bluesky" in augur._AUTO_PLATFORMS
        assert "mastodon" in augur._AUTO_PLATFORMS

    def test_post_social_normalizes_case(self, augur, monkeypatch):
        monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
        result = _run(augur.post_social("the", "Bluesky", "test", "https://example.com"))
        # Should not error with "Unknown platform" — should hit bluesky path
        assert "BLUESKY" in result.get("error", "")

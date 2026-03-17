"""Tests for the Augur news subsystem — augur_common, augur_publish, augur_score.

All tests use a temporary site directory and no external services.
"""
import json
import os
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip(
    "pytest_asyncio",
    reason="pytest-asyncio required (pip install pytest-asyncio)",
)


# ---------------------------------------------------------------------------
# augur_common tests
# ---------------------------------------------------------------------------


class TestBrandsConfig:
    """Validate BRANDS, SCHEDULES, and related config."""

    def test_brands_have_required_keys(self):
        from src.servers.augur_common import BRANDS
        required = {"name", "locale", "module", "masthead", "horizons",
                    "image_prefix", "disclaimer", "accent_color"}
        for slug, brand in BRANDS.items():
            missing = required - set(brand.keys())
            assert not missing, f"Brand '{slug}' missing keys: {missing}"

    def test_brands_horizons_cover_all_four(self):
        from src.servers.augur_common import BRANDS
        expected = {"tomorrow", "soon", "future", "leap"}
        for slug, brand in BRANDS.items():
            assert set(brand["horizons"].keys()) == expected, \
                f"Brand '{slug}' horizons mismatch"

    def test_schedules_match_brands(self):
        from src.servers.augur_common import BRANDS, SCHEDULES
        assert set(SCHEDULES.keys()) == set(BRANDS.keys())

    def test_section_labels_both_locales(self):
        from src.servers.augur_common import SECTION_LABELS
        assert "en" in SECTION_LABELS
        assert "de" in SECTION_LABELS
        for locale in ("en", "de"):
            assert set(SECTION_LABELS[locale].keys()) == {"signal", "extrapolation", "in_the_works"}

    def test_horizon_days_all_horizons(self):
        from src.servers.augur_common import HORIZON_DAYS
        assert set(HORIZON_DAYS.keys()) == {"tomorrow", "soon", "future", "leap"}
        for k, v in HORIZON_DAYS.items():
            assert isinstance(v, int) and v > 0


class TestSlugify:
    def test_basic(self):
        from src.servers.augur_common import slugify
        assert slugify("Hello World!") == "hello-world"

    def test_max_len(self):
        from src.servers.augur_common import slugify
        result = slugify("a" * 100, max_len=10)
        assert len(result) <= 10

    def test_empty_string(self):
        from src.servers.augur_common import slugify
        assert slugify("!!!") == "untitled"

    def test_unicode(self):
        from src.servers.augur_common import slugify
        result = slugify("Märkte stürzen ab")
        assert "rkte" in result  # ä stripped, base letters remain


class TestComputeFictiveDate:
    def test_tomorrow(self):
        from src.servers.augur_common import compute_fictive_date
        now = datetime(2026, 3, 11, tzinfo=timezone.utc)
        assert compute_fictive_date("tomorrow", now) == "2026-03-14"

    def test_soon(self):
        from src.servers.augur_common import compute_fictive_date
        now = datetime(2026, 3, 11, tzinfo=timezone.utc)
        assert compute_fictive_date("soon", now) == "2026-06-11"

    def test_future(self):
        from src.servers.augur_common import compute_fictive_date
        now = datetime(2026, 3, 11, tzinfo=timezone.utc)
        assert compute_fictive_date("future", now) == "2029-03-11"

    def test_leap(self):
        from src.servers.augur_common import compute_fictive_date
        now = datetime(2026, 3, 11, tzinfo=timezone.utc)
        assert compute_fictive_date("leap", now) == "2056-03-11"

    def test_soon_end_of_month(self):
        """Jan 31 + 3 months = Apr 30 (not Apr 31)."""
        from src.servers.augur_common import compute_fictive_date
        now = datetime(2026, 1, 31, tzinfo=timezone.utc)
        result = compute_fictive_date("soon", now)
        assert result == "2026-04-30"

    def test_unknown_horizon_fallback(self):
        from src.servers.augur_common import compute_fictive_date
        now = datetime(2026, 3, 11, tzinfo=timezone.utc)
        result = compute_fictive_date("nonexistent", now)
        assert result == "2026-03-14"  # fallback = +3 days


class TestArticleUrl:
    def test_default_base(self):
        from src.servers.augur_common import article_url
        url = article_url("the", "tomorrow", "2026-03-14")
        assert url == "https://github.com/ManuelKugelmann/Augur/the/tomorrow/2026-03-14"

    def test_custom_base(self):
        from src.servers.augur_common import article_url
        with patch.dict(os.environ, {"AUGUR_SITE_URL": "https://custom.site/"}):
            url = article_url("financial", "soon", "2026-06-11")
            assert url == "https://custom.site/financial/soon/2026-06-11"


class TestIsDue:
    def test_simple_hour_match(self):
        from src.servers.augur_common import is_due
        now = datetime(2026, 3, 11, 6, 5, tzinfo=timezone.utc)
        assert is_due("0,6,12,18", now) is True

    def test_simple_hour_no_match(self):
        from src.servers.augur_common import is_due
        now = datetime(2026, 3, 11, 7, 5, tzinfo=timezone.utc)
        assert is_due("0,6,12,18", now) is False

    def test_minute_too_late(self):
        from src.servers.augur_common import is_due
        now = datetime(2026, 3, 11, 6, 20, tzinfo=timezone.utc)
        assert is_due("0,6,12,18", now) is False

    def test_monday_schedule_on_monday(self):
        from src.servers.augur_common import is_due
        # 2026-03-09 is a Monday
        now = datetime(2026, 3, 9, 3, 0, tzinfo=timezone.utc)
        assert is_due("3/mon", now) is True

    def test_monday_schedule_on_tuesday(self):
        from src.servers.augur_common import is_due
        now = datetime(2026, 3, 10, 3, 0, tzinfo=timezone.utc)  # Tuesday
        assert is_due("3/mon", now) is False


class TestParseFrontMatter:
    def test_basic(self):
        from src.servers.augur_common import parse_front_matter
        text = textwrap.dedent("""\
            ---
            layout: "article"
            brand: "the"
            headline: "Test Article"
            confidence: "high"
            ---

            Body text here.
        """)
        fm, body = parse_front_matter(text)
        assert fm["layout"] == "article"
        assert fm["brand"] == "the"
        assert fm["headline"] == "Test Article"
        assert "Body text here." in body

    def test_null_values(self):
        from src.servers.augur_common import parse_front_matter
        text = "---\noutcome:\noutcome_note: null\n---\nbody"
        fm, body = parse_front_matter(text)
        assert fm["outcome"] is None
        assert fm["outcome_note"] is None

    def test_no_front_matter(self):
        from src.servers.augur_common import parse_front_matter
        fm, body = parse_front_matter("Just plain text")
        assert fm == {}
        assert body == "Just plain text"

    def test_list_values(self):
        from src.servers.augur_common import parse_front_matter
        text = '---\ntags: ["a", "b", "c"]\n---\nbody'
        fm, body = parse_front_matter(text)
        assert fm["tags"] == ["a", "b", "c"]

    def test_numeric_values(self):
        from src.servers.augur_common import parse_front_matter
        text = "---\nconfidence_score: 0.85\ncount: 42\n---\nbody"
        fm, body = parse_front_matter(text)
        assert fm["confidence_score"] == 0.85
        assert fm["count"] == 42


class TestExtractSections:
    def test_english_sections(self):
        from src.servers.augur_common import extract_sections
        body = textwrap.dedent("""\
            ## The Signal

            Signal content here.

            ## The Extrapolation

            Extrapolation content here.

            ## In The Works

            In the works content here.
        """)
        sections = extract_sections(body)
        assert "Signal content here." in sections["signal"]
        assert "Extrapolation content here." in sections["extrapolation"]
        assert "In the works content here." in sections["in_the_works"]

    def test_german_sections(self):
        from src.servers.augur_common import extract_sections
        body = textwrap.dedent("""\
            ## Das Signal

            Signal-Inhalt hier.

            ## Die Extrapolation

            Extrapolation-Inhalt hier.

            ## In Arbeit

            In Arbeit Inhalt hier.
        """)
        sections = extract_sections(body)
        assert "Signal-Inhalt hier." in sections["signal"]
        assert "Extrapolation-Inhalt hier." in sections["extrapolation"]
        assert "In Arbeit Inhalt hier." in sections["in_the_works"]

    def test_empty_body(self):
        from src.servers.augur_common import extract_sections
        assert extract_sections("") == {}


class TestToYaml:
    def test_round_trip_with_parse(self):
        from src.servers.augur_common import parse_front_matter, to_yaml
        obj = {
            "layout": "article",
            "brand": "the",
            "tags": ["test", "ci"],
            "confidence": 0.85,
            "outcome": None,
        }
        yaml_str = to_yaml(obj)
        text = f"---\n{yaml_str}---\nbody"
        fm, _ = parse_front_matter(text)
        assert fm["layout"] == "article"
        assert fm["brand"] == "the"
        assert fm["tags"] == ["test", "ci"]
        assert fm["confidence"] == 0.85
        assert fm["outcome"] is None

    def test_dict_sources(self):
        from src.servers.augur_common import to_yaml
        obj = {
            "sources": [
                {"url": "https://example.com", "title": "Test"},
                {"url": "https://other.com", "title": "Other"},
            ]
        }
        yaml_str = to_yaml(obj)
        assert "url:" in yaml_str
        assert "title:" in yaml_str


class TestFindArticles:
    def test_find_all(self, tmp_path):
        from src.servers.augur_common import find_articles
        posts = tmp_path / "_posts" / "the" / "tomorrow"
        posts.mkdir(parents=True)
        (posts / "2026-03-11-test.md").write_text("---\n---\ntest")
        (posts / "2026-03-10-old.md").write_text("---\n---\nold")
        result = find_articles(str(tmp_path))
        assert len(result) == 2

    def test_filter_by_brand(self, tmp_path):
        from src.servers.augur_common import find_articles
        for brand in ("the", "der"):
            d = tmp_path / "_posts" / brand / "tomorrow"
            d.mkdir(parents=True)
            (d / "2026-03-11-test.md").write_text("---\n---\ntest")
        result = find_articles(str(tmp_path), brand="the")
        assert len(result) == 1

    def test_filter_by_horizon(self, tmp_path):
        from src.servers.augur_common import find_articles
        for h in ("tomorrow", "soon"):
            d = tmp_path / "_posts" / "the" / h
            d.mkdir(parents=True)
            (d / "2026-03-11-test.md").write_text("---\n---\ntest")
        result = find_articles(str(tmp_path), horizon="soon")
        assert len(result) == 1

    def test_empty_site(self, tmp_path):
        from src.servers.augur_common import find_articles
        assert find_articles(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# augur_publish tests
# ---------------------------------------------------------------------------


@pytest.fixture
def site_env(tmp_path):
    """Set up a temp site directory and patch AUGUR_SITE_DIR."""
    site = tmp_path / "augur-site"
    posts = site / "_posts"
    for brand in ("the", "der", "financial", "finanz"):
        for horizon in ("tomorrow", "soon", "future", "leap",
                        "morgen", "bald", "zukunft", "sprung"):
            (posts / brand / horizon).mkdir(parents=True, exist_ok=True)
    (site / "assets" / "images").mkdir(parents=True)
    (site / "assets" / "cards").mkdir(parents=True)
    (site / "_data").mkdir(parents=True)

    with patch.dict(os.environ, {"AUGUR_SITE_DIR": str(site)}):
        yield site


class TestListBrands:
    @pytest.mark.asyncio
    async def test_returns_all_brands(self):
        from src.servers.augur_publish import list_brands
        result = await list_brands()
        assert set(result.keys()) == {"the", "der", "financial", "finanz"}
        for slug, info in result.items():
            assert "name" in info
            assert "locale" in info
            assert "horizons" in info


class TestPublishDue:
    @pytest.mark.asyncio
    async def test_returns_due_list(self):
        from src.servers.augur_publish import publish_due
        result = await publish_due()
        assert "due" in result
        assert "count" in result
        assert isinstance(result["due"], list)


class TestPublishArticle:
    @pytest.mark.asyncio
    async def test_publish_english_article(self, site_env):
        from src.servers.augur_publish import publish_article
        result = await publish_article(
            brand="the",
            horizon="tomorrow",
            headline="Test Article Title",
            signal="Signal content.",
            extrapolation="Extrapolation content.",
            in_the_works="In the works content.",
            tags=["test", "ci"],
            sources=[{"url": "https://example.com", "title": "Example"}],
            confidence="high",
        )
        assert "path" in result
        assert result["brand"] == "the"
        assert result["horizon"] == "tomorrow"

        path = Path(result["path"])
        assert path.exists()
        content = path.read_text()
        assert "## The Signal" in content
        assert "Signal content." in content
        assert "## The Extrapolation" in content
        assert "## In The Works" in content

    @pytest.mark.asyncio
    async def test_publish_german_article(self, site_env):
        from src.servers.augur_publish import publish_article
        result = await publish_article(
            brand="der",
            horizon="soon",
            headline="Deutsche Schlagzeile",
            signal="Signal-Inhalt.",
            extrapolation="Extrapolation-Inhalt.",
            in_the_works="In Arbeit Inhalt.",
            tags=["test"],
            sources=[],
        )
        assert "path" in result
        path = Path(result["path"])
        content = path.read_text()
        assert "## Das Signal" in content
        assert "## Die Extrapolation" in content
        assert "## In Arbeit" in content

    @pytest.mark.asyncio
    async def test_dedup_same_day(self, site_env):
        from src.servers.augur_publish import publish_article
        await publish_article(
            brand="the", horizon="tomorrow", headline="First",
            signal="s", extrapolation="e", in_the_works="i",
            tags=[], sources=[],
        )
        result = await publish_article(
            brand="the", horizon="tomorrow", headline="Second",
            signal="s", extrapolation="e", in_the_works="i",
            tags=[], sources=[],
        )
        assert "error" in result
        assert "already published" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_brand(self, site_env):
        from src.servers.augur_publish import publish_article
        result = await publish_article(
            brand="nonexistent", horizon="tomorrow", headline="Fail",
            signal="s", extrapolation="e", in_the_works="i",
            tags=[], sources=[],
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_horizon(self, site_env):
        from src.servers.augur_publish import publish_article
        result = await publish_article(
            brand="the", horizon="invalid", headline="Fail",
            signal="s", extrapolation="e", in_the_works="i",
            tags=[], sources=[],
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_sentiment_fields(self, site_env):
        from src.servers.augur_publish import publish_article
        result = await publish_article(
            brand="financial", horizon="soon", headline="Markets Move",
            signal="s", extrapolation="e", in_the_works="i",
            tags=["markets"], sources=[],
            sentiment_sector="tech",
            sentiment_direction="bullish",
            sentiment_confidence=0.85,
        )
        assert "path" in result
        content = Path(result["path"]).read_text()
        assert "sentiment_sector" in content
        assert "tech" in content

    @pytest.mark.asyncio
    async def test_front_matter_fields(self, site_env):
        from src.servers.augur_common import parse_front_matter
        from src.servers.augur_publish import publish_article
        result = await publish_article(
            brand="the", horizon="future", headline="Future Headline",
            signal="s", extrapolation="e", in_the_works="i",
            tags=["a", "b"], sources=[{"url": "https://x.com", "title": "X"}],
            confidence="low",
            image_prompt="a test prompt",
        )
        content = Path(result["path"]).read_text()
        fm, _ = parse_front_matter(content)
        assert fm["layout"] == "article"
        assert fm["brand"] == "the"
        assert fm["horizon"] == "future"
        assert fm["confidence"] == "low"
        assert fm["image_prompt"] == "a test prompt"
        assert fm["outcome"] is None


class TestGenerateArticleImage:
    @pytest.mark.asyncio
    async def test_invalid_brand(self, site_env):
        from src.servers.augur_publish import generate_article_image
        result = await generate_article_image(
            prompt="test", brand="bad", horizon="tomorrow")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_replicate_token(self, site_env):
        pytest.importorskip("httpx")
        from src.servers.augur_publish import generate_article_image
        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": ""}, clear=False):
            result = await generate_article_image(
                prompt="test", brand="the", horizon="tomorrow")
            assert "error" in result
            assert "REPLICATE_API_TOKEN" in result["error"]


class TestGenerateSocialCards:
    @pytest.mark.asyncio
    async def test_invalid_brand(self, site_env):
        from src.servers.augur_publish import generate_social_cards
        result = await generate_social_cards(
            image_path="/nonexistent.webp", headline="Test",
            brand="bad", horizon="tomorrow", fictive_date="2026-03-14")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_image(self, site_env):
        from src.servers.augur_publish import generate_social_cards
        result = await generate_social_cards(
            image_path="/nonexistent.webp", headline="Test",
            brand="the", horizon="tomorrow", fictive_date="2026-03-14")
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestPostSocial:
    @pytest.mark.asyncio
    async def test_invalid_platform(self):
        from src.servers.augur_publish import post_social
        result = await post_social(
            brand="the", platform="tiktok", caption="test",
            article_url="https://example.com")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_bluesky_no_credentials(self):
        pytest.importorskip("httpx")
        from src.servers.augur_publish import post_social
        with patch.dict(os.environ, {"BLUESKY_HANDLE": "", "BLUESKY_APP_PASSWORD": ""},
                        clear=False):
            result = await post_social(
                brand="the", platform="bluesky", caption="test",
                article_url="https://example.com")
            assert "error" in result

    @pytest.mark.asyncio
    async def test_mastodon_no_credentials(self):
        pytest.importorskip("httpx")
        from src.servers.augur_publish import post_social
        with patch.dict(os.environ, {"MASTODON_ACCESS_TOKEN": "", "MASTODON_INSTANCE": ""},
                        clear=False):
            result = await post_social(
                brand="the", platform="mastodon", caption="test",
                article_url="https://example.com")
            assert "error" in result

    @pytest.mark.asyncio
    async def test_manual_platform_no_ntfy(self):
        pytest.importorskip("httpx")
        from src.servers.augur_publish import post_social
        with patch.dict(os.environ, {"NTFY_TOPIC": ""}, clear=False):
            result = await post_social(
                brand="the", platform="x", caption="test",
                article_url="https://example.com")
            assert "error" in result
            assert "NTFY_TOPIC" in result["error"]


# ---------------------------------------------------------------------------
# augur_score tests
# ---------------------------------------------------------------------------


def _write_article(site: Path, brand: str, horizon_slug: str,
                   date_key: str, headline: str,
                   horizon: str = "tomorrow",
                   outcome: str = None) -> Path:
    """Write a minimal test article."""
    from src.servers.augur_common import slugify
    slug = slugify(headline)
    path = site / "_posts" / brand / horizon_slug / f"{date_key}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    outcome_line = f'outcome: "{outcome}"' if outcome else "outcome:"
    content = textwrap.dedent(f"""\
        ---
        layout: "article"
        brand: "{brand}"
        horizon: "{horizon}"
        categories: "{brand}/{horizon_slug}"
        date: "{date_key}"
        headline: "{headline}"
        fictive_date: "{date_key}"
        confidence: "medium"
        {outcome_line}
        outcome_note:
        outcome_date:
        ---

        ## The Signal

        Test signal content.

        ## The Extrapolation

        Test extrapolation content.

        ## In The Works

        Test in the works content.
    """)
    path.write_text(content)
    return path


class TestListPendingScores:
    @pytest.mark.asyncio
    async def test_finds_old_unscored_articles(self, site_env):
        from src.servers.augur_score import list_pending_scores
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_env, "the", "tomorrow", old_date, "Old Prediction")

        result = await list_pending_scores()
        assert result["count"] >= 1
        assert any("Old Prediction" in p["headline"] for p in result["pending"])

    @pytest.mark.asyncio
    async def test_skips_recent_articles(self, site_env):
        from src.servers.augur_score import list_pending_scores
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _write_article(site_env, "the", "tomorrow", today, "Fresh Prediction")

        result = await list_pending_scores()
        assert not any("Fresh Prediction" in p["headline"] for p in result["pending"])

    @pytest.mark.asyncio
    async def test_skips_already_scored(self, site_env):
        from src.servers.augur_score import list_pending_scores
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_env, "the", "tomorrow", old_date,
                       "Already Scored", outcome="confirmed")

        result = await list_pending_scores()
        assert not any("Already Scored" in p["headline"] for p in result["pending"])

    @pytest.mark.asyncio
    async def test_include_scored(self, site_env):
        from src.servers.augur_score import list_pending_scores
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_env, "the", "tomorrow", old_date,
                       "Rescoreable", outcome="partial")

        result = await list_pending_scores(include_scored=True)
        assert any("Rescoreable" in p["headline"] for p in result["pending"])

    @pytest.mark.asyncio
    async def test_filter_by_brand(self, site_env):
        from src.servers.augur_score import list_pending_scores
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_env, "the", "tomorrow", old_date, "The Brand Article")
        _write_article(site_env, "der", "morgen", old_date, "Der Brand Article")

        result = await list_pending_scores(brand="the")
        headlines = [p["headline"] for p in result["pending"]]
        assert "The Brand Article" in headlines
        assert "Der Brand Article" not in headlines

    @pytest.mark.asyncio
    async def test_extracts_sections(self, site_env):
        from src.servers.augur_score import list_pending_scores
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        _write_article(site_env, "the", "tomorrow", old_date, "Sections Test")

        result = await list_pending_scores()
        entry = next(p for p in result["pending"] if p["headline"] == "Sections Test")
        assert "signal" in entry and entry["signal"]
        assert "extrapolation" in entry and entry["extrapolation"]


class TestScoreDue:
    @pytest.mark.asyncio
    async def test_returns_structure(self, site_env):
        from src.servers.augur_score import score_due
        result = await score_due()
        assert "score_due" in result
        assert "pending" in result
        assert "checked_at" in result


class TestScorePrediction:
    @pytest.mark.asyncio
    async def test_score_confirmed(self, site_env):
        from src.servers.augur_score import score_prediction
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        path = _write_article(site_env, "the", "tomorrow", old_date, "Score Me")

        result = await score_prediction(
            article_path=str(path),
            outcome="confirmed",
            outcome_note="Prediction came true.",
            evidence=[{"url": "https://example.com", "title": "Source"}],
        )
        assert result["outcome"] == "confirmed"
        assert result["revision"] == 1

        # Verify front matter was updated
        from src.servers.augur_common import parse_front_matter
        fm, _ = parse_front_matter(path.read_text())
        assert fm["outcome"] == "confirmed"
        assert fm["outcome_note"] == "Prediction came true."

    @pytest.mark.asyncio
    async def test_score_log_created(self, site_env):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        path = _write_article(site_env, "the", "tomorrow", old_date, "Log Test")

        from src.servers.augur_score import score_prediction
        await score_prediction(article_path=str(path), outcome="wrong",
                               outcome_note="Did not happen.")

        log_path = path.with_suffix(".scores.json")
        assert log_path.exists()
        history = json.loads(log_path.read_text())
        assert len(history) == 1
        assert history[0]["outcome"] == "wrong"
        assert history[0]["revision"] == 1

    @pytest.mark.asyncio
    async def test_rescore_increments_revision(self, site_env):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        path = _write_article(site_env, "the", "tomorrow", old_date, "Rescore Test")

        from src.servers.augur_score import score_prediction
        await score_prediction(article_path=str(path), outcome="partial",
                               outcome_note="Partially true.")
        result = await score_prediction(article_path=str(path), outcome="confirmed",
                                        outcome_note="Now confirmed.")
        assert result["revision"] == 2

        log_path = path.with_suffix(".scores.json")
        history = json.loads(log_path.read_text())
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_invalid_outcome(self, site_env):
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        path = _write_article(site_env, "the", "tomorrow", old_date, "Invalid")

        from src.servers.augur_score import score_prediction
        result = await score_prediction(article_path=str(path), outcome="maybe")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_article_not_found(self, site_env):
        from src.servers.augur_score import score_prediction
        result = await score_prediction(
            article_path="/nonexistent/path.md", outcome="confirmed")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_relative_path(self, site_env):
        from src.servers.augur_score import score_prediction
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        path = _write_article(site_env, "the", "tomorrow", old_date, "Relative Path")
        rel_path = str(path.relative_to(site_env))

        result = await score_prediction(
            article_path=rel_path, outcome="wrong", outcome_note="Nope.")
        assert result["outcome"] == "wrong"


class TestGenerateScorecard:
    @pytest.mark.asyncio
    async def test_empty_scorecard(self, site_env):
        from src.servers.augur_score import generate_scorecard
        result = await generate_scorecard()
        assert result["summary"]["total"] == 0
        assert result["summary"]["accuracy"] is None

    @pytest.mark.asyncio
    async def test_scorecard_with_scored_articles(self, site_env):
        from src.servers.augur_score import generate_scorecard, score_prediction
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

        p1 = _write_article(site_env, "the", "tomorrow", old_date, "Confirmed One")
        await score_prediction(str(p1), "confirmed", "Yes.")

        old_date2 = (datetime.now(timezone.utc) - timedelta(days=11)).strftime("%Y-%m-%d")
        p2 = _write_article(site_env, "the", "tomorrow", old_date2, "Wrong One")
        await score_prediction(str(p2), "wrong", "No.")

        result = await generate_scorecard()
        assert result["summary"]["total"] == 2
        assert result["summary"]["confirmed"] == 1
        assert result["summary"]["wrong"] == 1
        assert result["summary"]["accuracy"] == 0.5  # (1 + 0) / 2

    @pytest.mark.asyncio
    async def test_scorecard_writes_data_file(self, site_env):
        from src.servers.augur_score import generate_scorecard, score_prediction
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        p = _write_article(site_env, "the", "tomorrow", old_date, "Data File Test")
        await score_prediction(str(p), "partial", "Half right.")

        await generate_scorecard()

        data_file = site_env / "_data" / "scorecard.json"
        assert data_file.exists()
        data = json.loads(data_file.read_text())
        assert "summary" in data
        assert "breakdown" in data

    @pytest.mark.asyncio
    async def test_scorecard_breakdown_by_brand(self, site_env):
        from src.servers.augur_score import generate_scorecard, score_prediction
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        old_date2 = (datetime.now(timezone.utc) - timedelta(days=11)).strftime("%Y-%m-%d")

        p1 = _write_article(site_env, "the", "tomorrow", old_date, "The Brand Score")
        await score_prediction(str(p1), "confirmed", "Yes.")

        p2 = _write_article(site_env, "financial", "tomorrow", old_date2, "Financial Score")
        await score_prediction(str(p2), "wrong", "No.")

        result = await generate_scorecard()
        assert "the/tomorrow" in result["breakdown"]
        assert "financial/tomorrow" in result["breakdown"]

    @pytest.mark.asyncio
    async def test_partial_counts_as_half(self, site_env):
        from src.servers.augur_score import generate_scorecard, score_prediction
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

        p = _write_article(site_env, "the", "tomorrow", old_date, "Partial Score")
        await score_prediction(str(p), "partial", "Partly.")

        result = await generate_scorecard()
        assert result["summary"]["accuracy"] == 0.5  # partial * 0.5 / 1


# ---------------------------------------------------------------------------
# Push site (unit-level — no actual git)
# ---------------------------------------------------------------------------


class TestPushSite:
    @pytest.mark.asyncio
    async def test_no_changes(self, site_env):
        """push_site with no changes returns no-op status."""
        import asyncio
        from src.servers.augur_publish import push_site

        async def _mock_run(*args, **kwargs):
            class MockProc:
                returncode = 0
                async def communicate(self):
                    if "status" in args:
                        return (b"", b"")  # no changes
                    return (b"", b"")
            return MockProc()

        with patch("asyncio.create_subprocess_exec", side_effect=_mock_run):
            result = await push_site()
            assert result["status"] == "no changes to push"

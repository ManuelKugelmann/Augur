"""Augur combined MCP server — backwards-compatible entry point.

Imports from augur_common, augur_publish, and augur_score.
Re-exports all public functions and constants so existing tests
and imports continue to work unchanged.

For production, use augur_publish and augur_score as separate servers
with separate agents. This combined module is for dev/testing convenience.
"""

from fastmcp import FastMCP

# Re-export everything from common (config, helpers)
from src.servers.augur_common import (
    BRANDS,
    HORIZON_DAYS,
    HORIZON_OFFSETS,
    SCHEDULES,
    SECTION_LABELS,
    apply_watermark,
    article_url as _article_url,
    compute_fictive_date as _compute_fictive_date,
    extract_sections as _extract_sections,
    find_articles as _find_articles,
    is_due as _is_due,
    parse_front_matter as _parse_front_matter,
    site_dir as _site_dir,
    slugify as _slugify,
    to_yaml as _to_yaml,
)

# Re-export publish tools
from src.servers.augur_publish import (
    CARD_SIZES,
    _AUTO_PLATFORMS,
    _MANUAL_PLATFORMS,
    _NTFY_TOPIC,
    _generate_card,
    _notify_manual_post,
    _post_bluesky,
    _post_mastodon,
)

# Import the sub-servers
from src.servers.augur_publish import mcp as publish_mcp
from src.servers.augur_score import mcp as score_mcp

# Combined MCP server that mounts both
mcp = FastMCP("augur", instructions=(
    "Combined Augur server (publish + score). In production, use "
    "augur_publish and augur_score as separate agents."
))
mcp.mount("pub", publish_mcp)
mcp.mount("score", score_mcp)

# Re-export tool functions directly for test compatibility
from src.servers.augur_publish import (
    generate_article_image,
    generate_social_cards,
    list_brands,
    post_social,
    publish_article,
    publish_due as due_now,
    push_site,
)
from src.servers.augur_score import (
    generate_scorecard,
    list_pending_scores,
    score_due,
    score_prediction,
)

"""augur-engine CLI entry point.

Usage:
    python -m src cycle --brand=the --horizon=tomorrow
    python -m src post
    python -m src cycle --brand=the --horizon=tomorrow --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .config.brands import BRANDS
from .config.horizons import compute_fictive_date
from .config.types import BrandKey, HorizonKey
from .collect.collector import collect_signals, MIN_SIGNALS
from .extrapolate.pipeline import extrapolate
from .assets.imagegen import generate_image
from .assets.watermark import apply_watermark
from .assets.cards import generate_cards
from .publish.jekyll import write_prediction
from .publish.git_push import commit_and_push
from .publish.social_queue import queue_social_posts, read_pending_posts, move_post

log = logging.getLogger("augur")


def _get_site_dir() -> str:
    return os.environ.get("SITE_REPO_PATH", str(Path.cwd().parent / "augur-site"))


async def _notify(title: str, message: str) -> None:
    """Send push notification via ntfy."""
    import httpx

    ntfy_url = os.environ.get("NTFY_URL", "https://ntfy.sh")
    ntfy_token = os.environ.get("NTFY_TOKEN")
    ntfy_topic = os.environ.get("NTFY_TOPIC", "augur-pipeline")

    if not ntfy_token:
        log.info("NTFY_TOKEN not set, skipping notification")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{ntfy_url}/{ntfy_topic}",
                headers={"Title": title, "Authorization": f"Bearer {ntfy_token}"},
                content=message,
            )
            log.info("notification sent")
    except Exception as exc:
        log.warning("notification failed: %s", exc)


async def run_cycle(brand_key: str, horizon_key: str, dry_run: bool) -> None:
    """Run a full prediction cycle for one brand/horizon."""
    brand = BRANDS[brand_key]
    site_dir = _get_site_dir()
    fictive_date = compute_fictive_date(horizon_key)

    log.info(
        "cycle: %s / %s → %s%s",
        brand.name, horizon_key, fictive_date,
        " (dry-run)" if dry_run else "",
    )

    # Step 1: Collect signals
    log.info("step 1: collecting signals...")
    signals = await collect_signals(brand.osint_sources)
    if len(signals) < MIN_SIGNALS:
        log.error(
            "abort: only %d signals collected (need %d+)", len(signals), MIN_SIGNALS
        )
        sys.exit(1)

    # Step 2: Extrapolate via LLM
    log.info("step 2: extrapolating...")
    prediction, captions = await extrapolate(brand, horizon_key, signals)

    if dry_run:
        print(json.dumps({
            "prediction": {
                "headline": prediction.headline,
                "signal": prediction.signal,
                "extrapolation": prediction.extrapolation,
                "in_the_works": prediction.in_the_works,
                "sources": prediction.sources,
                "tags": prediction.tags,
                "image_prompt": prediction.image_prompt,
            },
            "captions": captions,
        }, indent=2, ensure_ascii=False))
        return

    # Step 3: Generate image + watermark + social cards
    log.info("step 3: generating assets...")
    try:
        image_prefix = f"{brand_key}-{horizon_key}-{prediction.date_key}"
        image_path = str(Path(site_dir) / "assets" / "images" / f"{image_prefix}.webp")
        full_prompt = brand.image_style_prefix + (prediction.image_prompt or prediction.headline)

        await generate_image(full_prompt, image_path)
        apply_watermark(image_path)

        horizon_slug = next(
            (h.slug for h in brand.horizons if h.key == horizon_key),
            horizon_key,
        )
        card_paths = generate_cards(
            image_path=image_path,
            headline=prediction.headline,
            brand_name=brand.masthead,
            horizon_label=horizon_slug.upper(),
            fictive_date=prediction.fictive_date,
            accent_color=brand.palette.accent,
            output_dir=str(Path(site_dir) / "assets" / "cards"),
            file_prefix=image_prefix,
        )

        prediction.image_paths = [
            f"assets/images/{image_prefix}.webp",
            *[str(Path(p).relative_to(site_dir)) for p in card_paths],
        ]
    except Exception as exc:
        log.warning("image generation failed, continuing without image: %s", exc)

    # Step 4: Publish
    log.info("step 4: publishing...")
    write_prediction(prediction, site_dir)
    queue_social_posts(prediction, captions, brand, site_dir)

    # Step 5: Commit and push
    log.info("step 5: pushing to git...")
    await commit_and_push(
        site_dir,
        f"augur: {brand.slug}/{horizon_key} {prediction.date_key} — {prediction.headline[:50]}",
    )

    # Step 6: Notify
    log.info("step 6: notifying...")
    await _notify(
        f"{brand.name}: new prediction",
        f"{prediction.headline}\n{brand.slug}/{horizon_key}/{prediction.date_key}",
    )

    log.info("cycle complete")


async def run_post() -> None:
    """Process pending social posts."""
    site_dir = _get_site_dir()
    pending = read_pending_posts(site_dir)

    if not pending:
        log.info("post: no pending posts due")
        return

    log.info("post: %d posts due", len(pending))

    for path, entry in pending:
        log.info("posting to %s: %s...", entry.platform, entry.caption[:60])
        log.warning("%s posting not yet implemented — marking as failed", entry.platform)
        move_post(path, entry, "failed", site_dir, error="platform not yet implemented")


def main() -> None:
    """CLI entry point."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="augur-engine — AI prediction pipeline")
    sub = parser.add_subparsers(dest="command")

    cycle_p = sub.add_parser("cycle", help="Generate prediction for a brand/horizon")
    cycle_p.add_argument("--brand", required=True, choices=list(BRANDS.keys()))
    cycle_p.add_argument("--horizon", required=True, choices=["tomorrow", "soon", "future"])
    cycle_p.add_argument("--dry-run", action="store_true")

    sub.add_parser("post", help="Process pending social posts")
    sub.add_parser("scorecard", help="Update prediction outcomes")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "cycle":
        asyncio.run(run_cycle(args.brand, args.horizon, args.dry_run))
    elif args.command == "post":
        asyncio.run(run_post())
    elif args.command == "scorecard":
        log.info("scorecard: not yet implemented")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

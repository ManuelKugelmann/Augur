"""JSON file-based social posting queue."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config.types import BrandConfig, Prediction, SocialQueueEntry

log = logging.getLogger("augur.social")


def queue_social_posts(
    prediction: Prediction,
    captions: dict[str, str],
    brand: BrandConfig,
    site_dir: str,
) -> None:
    """Schedule social posts for a prediction (staggered 2h apart per platform)."""
    pending_dir = Path(site_dir) / "_data" / "social" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    base_time = datetime.now(timezone.utc)

    for i, platform in enumerate(brand.social_targets):
        caption = captions.get(platform)
        if not caption:
            continue

        scheduled_at = base_time + timedelta(hours=i * 2)

        entry = SocialQueueEntry(
            brand=prediction.brand,
            horizon=prediction.horizon,
            date_key=prediction.date_key,
            platform=platform,
            scheduled_at=scheduled_at.isoformat(),
            caption=caption,
            image_path=prediction.image_paths[0] if prediction.image_paths else "",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        filename = f"{prediction.brand}-{prediction.date_key}-{platform}.json"
        (pending_dir / filename).write_text(
            json.dumps(asdict(entry), indent=2), encoding="utf-8"
        )
        log.info("queued: %s (scheduled %s)", filename, scheduled_at.isoformat())


def read_pending_posts(
    site_dir: str,
) -> list[tuple[str, SocialQueueEntry]]:
    """Read all pending social posts that are due."""
    pending_dir = Path(site_dir) / "_data" / "social" / "pending"
    if not pending_dir.exists():
        return []

    now = datetime.now(timezone.utc)
    results: list[tuple[str, SocialQueueEntry]] = []

    for f in pending_dir.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        entry = SocialQueueEntry(**data)
        if datetime.fromisoformat(entry.scheduled_at) <= now:
            results.append((str(f), entry))

    return results


def move_post(
    file_path: str,
    entry: SocialQueueEntry,
    status: str,
    site_dir: str,
    post_url: str | None = None,
    error: str | None = None,
) -> None:
    """Move a post from pending to posted (success) or failed (error)."""
    target_dir = Path(site_dir) / "_data" / "social" / status
    target_dir.mkdir(parents=True, exist_ok=True)

    if status == "posted":
        entry.post_url = post_url
        entry.posted_at = datetime.now(timezone.utc).isoformat()
    else:
        entry.error = error or "unknown error"
        entry.retry_count += 1

    filename = Path(file_path).name
    (target_dir / filename).write_text(
        json.dumps(asdict(entry), indent=2), encoding="utf-8"
    )

    # Remove from pending
    Path(file_path).unlink(missing_ok=True)
    log.info("%s: %s", status, filename)

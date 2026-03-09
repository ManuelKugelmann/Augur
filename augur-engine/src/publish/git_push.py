"""Git commit and push for the augur site repo."""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("augur.publish")


async def commit_and_push(
    site_dir: str,
    message: str,
    branch: str | None = None,
) -> None:
    """Commit and push new content to the augur site repo/branch."""
    target_branch = branch or os.environ.get("SITE_BRANCH", "augur_news")

    async def _run(cmd: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=site_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    # Ensure we're on the right branch
    rc, current, _ = await _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    current = current.strip()
    if current != target_branch:
        rc, _, _ = await _run(["git", "checkout", target_branch])
        if rc != 0:
            await _run(["git", "checkout", "-b", target_branch])

    # Stage all changes
    await _run(["git", "add", "."])

    # Check if there are actual changes
    rc, status_out, _ = await _run(["git", "status", "--porcelain"])
    if not status_out.strip():
        log.info("no changes to commit")
        return

    # Commit
    await _run(["git", "commit", "-m", message])
    log.info("committed: %s", message)

    # Push with retry (exponential backoff)
    backoff = [2, 4, 8, 16]
    for attempt in range(5):
        rc, _, stderr = await _run(
            ["git", "push", "-u", "origin", target_branch]
        )
        if rc == 0:
            log.info("pushed to origin/%s", target_branch)
            return
        if attempt < 4:
            delay = backoff[attempt]
            log.warning(
                "push failed (attempt %d/5), retrying in %ds...", attempt + 1, delay
            )
            await asyncio.sleep(delay)

    raise RuntimeError(f"push failed after 5 attempts: {stderr}")

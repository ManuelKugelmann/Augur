"""In-process plan worker — triggers T4 agent per user via ntfy.

Simple cron: on each interval, find all distinct users who have plans,
send one ntfy notification per user to trigger their agent.
The agent reads the user's plans and decides what to do.
"""

import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger("plan-worker")

_CHECK_INTERVAL = int(__import__("os").environ.get("PLAN_WORKER_INTERVAL", "60"))

_running = False
_task: asyncio.Task | None = None
_notify_func = None  # set by start() — server.send_notification


async def _run_loop(db_func):
    """Main loop: find users with plans, trigger their agent."""
    global _running
    _running = True
    log.info("Plan worker started (interval=%ds)", _CHECK_INTERVAL)

    while _running:
        try:
            notes_col = db_func().user_notes
            # Get distinct user_ids that have at least one plan
            user_ids = notes_col.distinct("user_id", {"kind": "plan"})

            for uid in user_ids:
                if not uid:
                    continue
                # Look up the user's ntfy topic from any of their plans
                sample = notes_col.find_one({"kind": "plan", "user_id": uid})
                topic = _extract_topic(sample)
                if topic and _notify_func:
                    _notify_func(topic, "Plan check",
                                 "Scheduled plan review — check your plans.",
                                 priority="default", tags="robot")
                    log.info("Triggered agent for user %s", uid)

        except Exception as e:
            log.error("Plan worker cycle error: %s", e)

        await asyncio.sleep(_CHECK_INTERVAL)


def _extract_topic(note: dict | None) -> str:
    """Try to read ntfy_topic from a plan note's content."""
    if note is None:
        return ""
    content = note.get("content", "")
    if isinstance(content, dict):
        return content.get("ntfy_topic", "")
    if isinstance(content, str):
        try:
            import json
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed.get("ntfy_topic", "")
        except (ValueError, TypeError):
            pass
    return ""


def start(db_func, notify_func=None):
    """Start the plan worker as a background asyncio task."""
    global _task, _notify_func
    _notify_func = notify_func
    if _task is not None and not _task.done():
        log.warning("Plan worker already running")
        return
    loop = asyncio.get_event_loop()
    _task = loop.create_task(_run_loop(db_func))
    return _task


def stop():
    """Stop the plan worker."""
    global _running, _task
    _running = False
    if _task is not None:
        _task.cancel()
        _task = None
    log.info("Plan worker stopped")


def status() -> dict:
    """Return worker status."""
    return {
        "running": _running,
        "check_interval_seconds": _CHECK_INTERVAL,
    }

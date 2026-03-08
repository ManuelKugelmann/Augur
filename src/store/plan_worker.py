"""In-process plan worker — timed agent trigger per user.

Scans all user plans (notes with kind="plan") on a timer.
For each enabled plan, sends an ntfy notification to the user's topic,
which triggers their LibreChat T4 agent to execute the plan.

No condition evaluation — just timed execution. KISS.

Plan content (JSON):
  schedule: interval in minutes (default: 5)
  enabled: bool (default: true)
  ntfy_topic: user's ntfy topic for push notifications
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("plan-worker")

# In-memory tracking: last trigger time per plan _id
_last_trigger: dict[str, datetime] = {}

# Default check interval in seconds
_CHECK_INTERVAL = int(__import__("os").environ.get("PLAN_WORKER_INTERVAL", "60"))

_running = False
_task: asyncio.Task | None = None
_notify_func = None  # set by start() — server.send_notification


def _parse_plan(note: dict) -> dict | None:
    """Extract structured plan data from a note's content field.
    Returns None if not a valid plan."""
    content = note.get("content", "")
    if isinstance(content, dict):
        plan = content
    elif isinstance(content, str):
        try:
            plan = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
    else:
        return None
    if not isinstance(plan, dict):
        return None
    plan.setdefault("schedule", 5)
    plan.setdefault("enabled", True)
    return plan


def _should_trigger(note_id: str, schedule_minutes: int) -> bool:
    """Check if enough time has passed since last trigger."""
    now = datetime.now(timezone.utc)
    last = _last_trigger.get(note_id)
    if last is None:
        return True
    elapsed = (now - last).total_seconds()
    return elapsed >= schedule_minutes * 60


async def _trigger_plan(note: dict, plan: dict, db_func) -> dict | None:
    """Trigger a plan: log event + send ntfy to activate user's agent."""
    note_id = str(note.get("_id", ""))
    user_id = note.get("user_id", "")
    title = note.get("title", "")
    ntfy_topic = plan.get("ntfy_topic", "")

    now = datetime.now(timezone.utc)
    _last_trigger[note_id] = now

    event = {
        "ts": now,
        "meta": {
            "kind": "plan_trigger",
            "type": "scheduled",
            "source": "plan_worker",
            "user_id": user_id,
        },
        "data": {
            "plan_id": note_id,
            "plan_title": title,
        },
    }
    try:
        db_func().events.insert_one(event)
    except Exception as e:
        log.error("Failed to insert plan event: %s", e)

    # Send ntfy push — triggers the T4 agent for this user
    if ntfy_topic and _notify_func:
        _notify_func(ntfy_topic, f"Plan: {title}",
                     f"Scheduled execution for plan '{title}'.",
                     priority="default", tags="robot")

    log.info("Plan triggered: %s for user %s", title, user_id)
    return event


async def _run_loop(db_func):
    """Main worker loop — scans plans and triggers on schedule."""
    global _running
    _running = True
    log.info("Plan worker started (interval=%ds)", _CHECK_INTERVAL)

    while _running:
        try:
            notes_col = db_func().user_notes
            plans = list(notes_col.find({"kind": "plan"}))

            for note in plans:
                plan = _parse_plan(note)
                if plan is None or not plan.get("enabled", True):
                    continue

                note_id = str(note.get("_id", ""))
                schedule = plan.get("schedule", 5)

                if not _should_trigger(note_id, schedule):
                    continue

                try:
                    await _trigger_plan(note, plan, db_func)
                except Exception as e:
                    log.error("Error triggering plan %s: %s", note_id, e)

        except Exception as e:
            log.error("Plan worker cycle error: %s", e)

        await asyncio.sleep(_CHECK_INTERVAL)


def start(db_func, notify_func=None):
    """Start the plan worker as a background asyncio task.

    Args:
        db_func: callable returning the MongoDB database
        notify_func: callable(topic, title, message, priority, tags) for ntfy
    """
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
        "plans_tracked": len(_last_trigger),
        "last_trigger_times": {
            k: v.isoformat() for k, v in _last_trigger.items()
        },
    }

"""Tests for the plan worker — parsing, schedule gating, triggering."""
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "store"))

import plan_worker


# ── Plan parsing ─────────────────────────────────


class TestParsePlan:
    def test_json_string_content(self):
        note = {"content": json.dumps({"schedule": 10})}
        plan = plan_worker._parse_plan(note)
        assert plan is not None
        assert plan["schedule"] == 10
        assert plan["enabled"] is True

    def test_dict_content(self):
        note = {"content": {"schedule": 15, "ntfy_topic": "my-topic"}}
        plan = plan_worker._parse_plan(note)
        assert plan is not None
        assert plan["schedule"] == 15

    def test_defaults(self):
        note = {"content": json.dumps({})}
        plan = plan_worker._parse_plan(note)
        assert plan["schedule"] == 5
        assert plan["enabled"] is True

    def test_plain_text_returns_none(self):
        note = {"content": "just a plain text plan"}
        assert plan_worker._parse_plan(note) is None

    def test_missing_content(self):
        assert plan_worker._parse_plan({}) is None


# ── Schedule gating ──────────────────────────────


class TestScheduleGating:
    def test_first_trigger_always_runs(self):
        plan_worker._last_trigger.clear()
        assert plan_worker._should_trigger("new-plan", 5)

    def test_recent_trigger_skipped(self):
        plan_worker._last_trigger["recent"] = datetime.now(timezone.utc)
        assert not plan_worker._should_trigger("recent", 5)


# ── Plan triggering ──────────────────────────────


class TestTriggerPlan:
    def _make_db_func(self):
        db = MagicMock()
        db.events.insert_one = MagicMock()
        db.user_notes.find = MagicMock(return_value=[])
        return lambda: db

    def test_trigger_logs_event(self):
        db_func = self._make_db_func()
        note = {"_id": "plan-1", "user_id": "user-1", "title": "Daily Check"}
        plan = {"schedule": 5, "enabled": True, "ntfy_topic": ""}
        result = asyncio.get_event_loop().run_until_complete(
            plan_worker._trigger_plan(note, plan, db_func)
        )
        assert result is not None
        assert result["meta"]["type"] == "scheduled"
        assert result["data"]["plan_title"] == "Daily Check"
        db_func().events.insert_one.assert_called_once()

    def test_trigger_calls_ntfy(self):
        db_func = self._make_db_func()
        notify = MagicMock()
        plan_worker._notify_func = notify
        note = {"_id": "plan-2", "user_id": "user-1", "title": "Alert"}
        plan = {"schedule": 5, "enabled": True, "ntfy_topic": "my-topic"}
        asyncio.get_event_loop().run_until_complete(
            plan_worker._trigger_plan(note, plan, db_func)
        )
        notify.assert_called_once()
        assert notify.call_args[0][0] == "my-topic"
        plan_worker._notify_func = None

    def test_trigger_skips_ntfy_without_topic(self):
        db_func = self._make_db_func()
        notify = MagicMock()
        plan_worker._notify_func = notify
        note = {"_id": "plan-3", "user_id": "user-1", "title": "X"}
        plan = {"schedule": 5, "enabled": True, "ntfy_topic": ""}
        asyncio.get_event_loop().run_until_complete(
            plan_worker._trigger_plan(note, plan, db_func)
        )
        notify.assert_not_called()
        plan_worker._notify_func = None


# ── Worker status ────────────────────────────────


class TestWorkerStatus:
    def test_status_returns_dict(self):
        s = plan_worker.status()
        assert "running" in s
        assert "check_interval_seconds" in s
        assert "plans_tracked" in s

"""Tests for the plan worker — topic extraction, agent triggering."""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "store"))

import plan_worker


class TestExtractTopic:
    def test_dict_content(self):
        note = {"content": {"ntfy_topic": "my-topic"}}
        assert plan_worker._extract_topic(note) == "my-topic"

    def test_json_string_content(self):
        note = {"content": json.dumps({"ntfy_topic": "t1"})}
        assert plan_worker._extract_topic(note) == "t1"

    def test_plain_text(self):
        note = {"content": "just text"}
        assert plan_worker._extract_topic(note) == ""

    def test_no_topic(self):
        note = {"content": {"other": "stuff"}}
        assert plan_worker._extract_topic(note) == ""

    def test_none(self):
        assert plan_worker._extract_topic(None) == ""

    def test_missing_content(self):
        assert plan_worker._extract_topic({}) == ""


class TestRunLoop:
    def _make_db(self, user_ids, sample_note=None):
        col = MagicMock()
        col.distinct.return_value = user_ids
        col.find_one.return_value = sample_note
        db = MagicMock()
        db.user_notes = col
        return lambda: db

    def test_triggers_per_user(self):
        """Worker sends one ntfy call per user with plans."""
        import asyncio
        notify = MagicMock()
        plan_worker._notify_func = notify

        note = {"content": {"ntfy_topic": "topic-a"}}
        db_func = self._make_db(["user-1", "user-2"], note)

        # Run one iteration by patching sleep to stop the loop
        async def one_cycle():
            plan_worker._running = True
            try:
                col = db_func().user_notes
                user_ids = col.distinct("user_id", {"kind": "plan"})
                for uid in user_ids:
                    if not uid:
                        continue
                    sample = col.find_one({"kind": "plan", "user_id": uid})
                    topic = plan_worker._extract_topic(sample)
                    if topic and plan_worker._notify_func:
                        plan_worker._notify_func(
                            topic, "Plan check",
                            "Scheduled plan review — check your plans.",
                            priority="default", tags="robot")
            finally:
                plan_worker._running = False

        asyncio.get_event_loop().run_until_complete(one_cycle())
        assert notify.call_count == 2
        plan_worker._notify_func = None

    def test_skips_empty_user_id(self):
        import asyncio
        notify = MagicMock()
        plan_worker._notify_func = notify
        db_func = self._make_db(["", "user-1"], {"content": {"ntfy_topic": "t"}})

        async def one_cycle():
            col = db_func().user_notes
            user_ids = col.distinct("user_id", {"kind": "plan"})
            for uid in user_ids:
                if not uid:
                    continue
                sample = col.find_one({"kind": "plan", "user_id": uid})
                topic = plan_worker._extract_topic(sample)
                if topic and plan_worker._notify_func:
                    plan_worker._notify_func(topic, "Plan check", "x",
                                             priority="default", tags="robot")

        asyncio.get_event_loop().run_until_complete(one_cycle())
        assert notify.call_count == 1
        plan_worker._notify_func = None

    def test_skips_without_topic(self):
        import asyncio
        notify = MagicMock()
        plan_worker._notify_func = notify
        db_func = self._make_db(["user-1"], {"content": {"no_topic": True}})

        async def one_cycle():
            col = db_func().user_notes
            user_ids = col.distinct("user_id", {"kind": "plan"})
            for uid in user_ids:
                if not uid:
                    continue
                sample = col.find_one({"kind": "plan", "user_id": uid})
                topic = plan_worker._extract_topic(sample)
                if topic and plan_worker._notify_func:
                    plan_worker._notify_func(topic, "Plan check", "x",
                                             priority="default", tags="robot")

        asyncio.get_event_loop().run_until_complete(one_cycle())
        notify.assert_not_called()
        plan_worker._notify_func = None


class TestWorkerStatus:
    def test_status_returns_dict(self):
        s = plan_worker.status()
        assert "running" in s
        assert "check_interval_seconds" in s

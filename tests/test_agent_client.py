"""Tests for agent_client.py — shared LibreChat Agents API client."""

import json
import os
import sys
import types

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for agent_client tests")

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "augur-uberspace",
    "scripts",
)
sys.path.insert(0, SCRIPT_DIR)

from agent_client import AgentClient, load_env  # noqa: E402


# ── Fixtures ──────────────────────────────────────


FAKE_MODELS_RESPONSE = {
    "data": [
        {"id": "agent_cron-planner_abc123", "name": "Cron Planner"},
        {"id": "agent_market-data_def456", "name": "Market Data"},
        {"id": "agent_news-the-augur_ghi789", "name": "News: The Augur"},
    ]
}


class FakeResponse:
    """Minimal httpx.Response mock."""
    def __init__(self, status_code=200, json_data=None, lines=None):
        self.status_code = status_code
        self._json_data = json_data
        self._lines = lines or []

    def json(self):
        return self._json_data

    def iter_lines(self):
        yield from self._lines

    def iter_text(self):
        yield json.dumps(self._json_data or {})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.fixture
def mock_client(monkeypatch):
    """Create an AgentClient with mocked httpx calls."""
    get_resp = FakeResponse(200, FAKE_MODELS_RESPONSE)

    def fake_get(url, **kwargs):
        return get_resp

    monkeypatch.setattr(httpx, "get", fake_get)
    return AgentClient("http://localhost:3080", "test-key")


# ── Tests: load_env ──────────────────────────────


class TestLoadEnv:
    def test_loads_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_AGENT_KEY=secret123\n")
        monkeypatch.delenv("TEST_AGENT_KEY", raising=False)
        load_env(str(env_file))
        assert os.environ.get("TEST_AGENT_KEY") == "secret123"
        # Cleanup
        monkeypatch.delenv("TEST_AGENT_KEY")

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_AGENT_KEY=from_file\n")
        monkeypatch.setenv("TEST_AGENT_KEY", "from_env")
        load_env(str(env_file))
        assert os.environ["TEST_AGENT_KEY"] == "from_env"

    def test_skips_comments_and_blanks(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nVALID_KEY=yes\n")
        monkeypatch.delenv("VALID_KEY", raising=False)
        load_env(str(env_file))
        assert os.environ.get("VALID_KEY") == "yes"
        monkeypatch.delenv("VALID_KEY")

    def test_strips_quotes(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_KEY="hello world"\n')
        monkeypatch.delenv("QUOTED_KEY", raising=False)
        load_env(str(env_file))
        assert os.environ.get("QUOTED_KEY") == "hello world"
        monkeypatch.delenv("QUOTED_KEY")

    def test_missing_file_is_noop(self):
        load_env("/nonexistent/path/.env")  # should not raise


# ── Tests: find_agent ────────────────────────────


class TestFindAgent:
    def test_find_by_name_substring(self, mock_client):
        assert mock_client.find_agent("cron-planner") == "agent_cron-planner_abc123"

    def test_find_by_id_substring(self, mock_client):
        assert mock_client.find_agent("abc123") == "agent_cron-planner_abc123"

    def test_find_case_insensitive(self, mock_client):
        assert mock_client.find_agent("market data") is not None

    def test_not_found_returns_none(self, mock_client):
        assert mock_client.find_agent("nonexistent") is None


# ── Tests: list_agents ───────────────────────────


class TestListAgents:
    def test_returns_id_name_map(self, mock_client):
        agents = mock_client.list_agents()
        assert agents["agent_cron-planner_abc123"] == "Cron Planner"
        assert agents["agent_market-data_def456"] == "Market Data"
        assert len(agents) == 3


# ── Tests: invoke ────────────────────────────────


class TestInvoke:
    def test_successful_invoke(self, mock_client, monkeypatch):
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            'data: [DONE]',
        ]
        fake_resp = FakeResponse(200, lines=sse_lines)

        def fake_stream(method, url, **kwargs):
            return fake_resp

        monkeypatch.setattr(httpx, "stream", fake_stream)
        result = mock_client.invoke("agent_abc123", "test prompt")
        assert result["status"] == "ok"
        assert result["content"] == "Hello world"

    def test_error_status_code(self, mock_client, monkeypatch):
        fake_resp = FakeResponse(500, json_data={"error": "Internal error"})

        def fake_stream(method, url, **kwargs):
            return fake_resp

        monkeypatch.setattr(httpx, "stream", fake_stream)
        result = mock_client.invoke("agent_abc123", "test")
        assert result["status"] == "error"
        assert "500" in result.get("error", "")

    def test_writes_log_file(self, mock_client, monkeypatch, tmp_path):
        sse_lines = [
            'data: {"choices":[{"delta":{"content":"logged output"}}]}',
            'data: [DONE]',
        ]
        fake_resp = FakeResponse(200, lines=sse_lines)

        def fake_stream(method, url, **kwargs):
            return fake_resp

        monkeypatch.setattr(httpx, "stream", fake_stream)
        log_file = str(tmp_path / "test.log")
        result = mock_client.invoke("agent_abc123", "test", log_file=log_file)
        assert result["status"] == "ok"
        assert os.path.isfile(log_file)
        content = open(log_file).read()
        assert "logged output" in content
        assert "agent_id=agent_abc123" in content

    def test_timeout_returns_partial(self, mock_client, monkeypatch):
        def fake_stream(method, url, **kwargs):
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx, "stream", fake_stream)
        result = mock_client.invoke("agent_abc123", "test", timeout=1)
        assert result["status"] == "timeout"

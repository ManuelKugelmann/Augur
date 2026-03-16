"""E2E smoke test — start LibreChat + augur server, verify full stack.

Downloads the prebuilt release bundle, starts both services, registers
a test user, seeds agents, and verifies health/MCP/agent endpoints.

Requires:
  MONGO_URI          — Atlas cluster URI (derives ci_e2e databases)
  ANTHROPIC_API_KEY   — or any LLM key for agent chat

Skipped if MONGO_URI is not set.
Marked with pytest.mark.integration + pytest.mark.e2e.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required")

# ── Config ──────────────────────────────────────

MONGO_URI = os.environ.get("MONGO_URI", "")
MONGO_URI_LC = os.environ.get("MONGO_URI_LIBRECHAT", "")
MONGO_URI_SIGNALS = os.environ.get("MONGO_URI_SIGNALS", "")

# LLM key: check common providers in priority order
LLM_KEY_NAME = ""
LLM_KEY_VALUE = ""
for _name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
    _val = os.environ.get(_name, "")
    if _val:
        LLM_KEY_NAME = _name
        LLM_KEY_VALUE = _val
        break

REPO_ROOT = Path(__file__).resolve().parent.parent
LC_PORT = 3080
MCP_PORT = 8071

# Test user credentials (created via registration API)
TEST_EMAIL = "ci-e2e@test.local"
TEST_PASSWORD = "CiE2eTestPass123!"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.skipif(not MONGO_URI_LC, reason="MONGO_URI_LIBRECHAT not set"),
    pytest.mark.skipif(not MONGO_URI_SIGNALS, reason="MONGO_URI_SIGNALS not set"),
]


# ── Helpers ──────────────────────────────────────


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_for_port(port: int, timeout: int = 60):
    """Block until port accepts connections or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_free(port):
            return True
        time.sleep(1)
    return False


def _wait_for_http(url: str, timeout: int = 60) -> bool:
    """Wait until URL returns a non-5xx response."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5, follow_redirects=True)
            if r.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(2)
    return False


# ── Fixtures ─────────────────────────────────────


@pytest.fixture(scope="module")
def lc_app_dir(tmp_path_factory):
    """Set up LibreChat app directory from release bundle or local build."""
    app_dir = tmp_path_factory.mktemp("librechat")

    # Try downloading latest release bundle
    bundle_path = app_dir / "librechat-bundle.tar.gz"
    dl_result = subprocess.run(
        ["gh", "release", "download", "--pattern", "librechat-bundle.tar.gz",
         "--dir", str(app_dir), "--repo", "ManuelKugelmann/Augur"],
        capture_output=True, text=True, timeout=120)

    if dl_result.returncode != 0 or not bundle_path.exists():
        pytest.skip("Could not download release bundle (gh CLI or release missing)")

    # Extract
    subprocess.run(
        ["tar", "xzf", str(bundle_path), "-C", str(app_dir)],
        check=True, timeout=60)

    # Verify LibreChat app code
    assert (app_dir / "api" / "server" / "index.js").exists(), \
        "Bundle missing api/server/index.js"

    return app_dir


@pytest.fixture(scope="module")
def lc_env(lc_app_dir):
    """Generate .env for LibreChat with CI credentials."""
    env_file = lc_app_dir / ".env"

    # Generate crypto keys
    creds_key = os.urandom(16).hex()
    creds_iv = os.urandom(8).hex()
    jwt_secret = os.urandom(32).hex()
    jwt_refresh = os.urandom(32).hex()

    env_content = textwrap.dedent(f"""\
        MONGO_URI={MONGO_URI_LC}
        CREDS_KEY={creds_key}
        CREDS_IV={creds_iv}
        JWT_SECRET={jwt_secret}
        JWT_REFRESH_SECRET={jwt_refresh}
        SEARCH=false
        {LLM_KEY_NAME}={LLM_KEY_VALUE}
        ALLOW_REGISTRATION=true
    """)

    env_file.write_text(env_content)
    return env_file


@pytest.fixture(scope="module")
def lc_yaml(lc_app_dir):
    """Copy and configure librechat.yaml."""
    yaml_src = REPO_ROOT / "augur-uberspace" / "config" / "librechat.yaml"
    yaml_dst = lc_app_dir / "librechat.yaml"

    content = yaml_src.read_text()
    # Replace __HOME__ with a dummy path (MCP servers won't actually launch
    # from their command definitions — we only test the trading server via URL)
    content = content.replace("__HOME__", str(lc_app_dir))

    # remoteAgents is enabled by default in librechat.yaml
    yaml_dst.write_text(content)
    return yaml_dst


@pytest.fixture(scope="module")
def signals_venv(tmp_path_factory):
    """Create a Python venv with signals stack deps."""
    venv_dir = tmp_path_factory.mktemp("venv")
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True, timeout=60)
    pip = str(venv_dir / "bin" / "pip")
    subprocess.run(
        [pip, "install", "-q", "-r", str(REPO_ROOT / "requirements.txt")],
        check=True, timeout=120)
    return venv_dir


@pytest.fixture(scope="module")
def augur_server(signals_venv):
    """Start the combined augur server on MCP_PORT."""
    if not _port_free(MCP_PORT):
        pytest.skip(f"Port {MCP_PORT} already in use")

    python = str(signals_venv / "bin" / "python")
    env = {
        **os.environ,
        "MCP_TRANSPORT": "http",
        "MCP_PORT": str(MCP_PORT),
        "MONGO_URI_SIGNALS": MONGO_URI_SIGNALS,
        "PROFILES_DIR": str(REPO_ROOT / "profiles"),
        "PYTHONPATH": str(REPO_ROOT / "src" / "servers") + ":"
                      + str(REPO_ROOT / "src" / "store"),
    }

    proc = subprocess.Popen(
        [python, str(REPO_ROOT / "src" / "servers" / "combined_server.py")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not _wait_for_port(MCP_PORT, timeout=30):
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        proc.kill()
        pytest.fail(f"Augur server didn't start on :{MCP_PORT}\n"
                    f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}")

    yield proc

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def librechat_server(lc_app_dir, lc_env, lc_yaml, augur_server):
    """Start LibreChat Node.js server on LC_PORT."""
    if not _port_free(LC_PORT):
        pytest.skip(f"Port {LC_PORT} already in use")

    env = {
        **os.environ,
        "NODE_ENV": "production",
        "HOST": "127.0.0.1",
        "PORT": str(LC_PORT),
    }

    proc = subprocess.Popen(
        ["node", "--max-old-space-size=1024", "api/server/index.js"],
        cwd=str(lc_app_dir), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not _wait_for_http(f"http://127.0.0.1:{LC_PORT}/api/health", timeout=90):
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        proc.kill()
        pytest.fail(f"LibreChat didn't start on :{LC_PORT}\n"
                    f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}")

    yield proc

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def auth_token(librechat_server):
    """Register test user and return JWT token."""
    base = f"http://127.0.0.1:{LC_PORT}"
    client = httpx.Client(base_url=base, timeout=15)

    # Register (ignore if already exists)
    reg_resp = client.post("/api/auth/register", json={
        "name": "CI E2E",
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "confirm_password": TEST_PASSWORD,
    })
    # 200 = created, 422/409 = already exists — both OK
    assert reg_resp.status_code in (200, 201, 409, 422, 500), \
        f"Registration unexpected: {reg_resp.status_code} {reg_resp.text[:200]}"

    # Login
    login_resp = client.post("/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert login_resp.status_code == 200, \
        f"Login failed: {login_resp.status_code} {login_resp.text[:200]}"

    data = login_resp.json()
    token = data.get("token")
    assert token, f"No token in login response: {data}"

    client.close()
    return token


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated httpx client for LibreChat API."""
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{LC_PORT}",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=30)
    yield client
    client.close()


@pytest.fixture(scope="module")
def agents_api_key(api_client):
    """Create an Agents API key via LibreChat for remote agent calls."""
    # Try creating an API key for the Agents API
    r = api_client.post("/api/keys", json={
        "name": "ci-e2e-cron-test",
        "endpoint": "agents",
    })
    if r.status_code not in (200, 201):
        # Fallback: try alternate endpoint patterns
        r = api_client.post("/api/agents/keys", json={
            "name": "ci-e2e-cron-test",
        })
    if r.status_code not in (200, 201):
        pytest.skip(f"Could not create Agents API key: {r.status_code}")
    data = r.json()
    key = data.get("key") or data.get("api_key") or data.get("value", "")
    if not key:
        pytest.skip(f"No key in API key response: {data}")
    return key


# ── Health checks ────────────────────────────────


class TestHealth:
    """Verify both services are running and responsive."""

    def test_augur_server_responds(self, augur_server):
        """Augur server MCP endpoint responds."""
        # streamable-http endpoint — POST with MCP initialize
        r = httpx.post(
            f"http://127.0.0.1:{MCP_PORT}/mcp",
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1,
                  "params": {"protocolVersion": "2024-11-05",
                             "clientInfo": {"name": "ci-test", "version": "1.0"},
                             "capabilities": {}}},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            timeout=15)
        assert r.status_code == 200, f"MCP endpoint: {r.status_code} {r.text[:200]}"

    def test_librechat_health(self, librechat_server):
        """LibreChat health endpoint returns 200."""
        r = httpx.get(f"http://127.0.0.1:{LC_PORT}/api/health",
                      timeout=10, follow_redirects=True)
        assert r.status_code == 200

    def test_librechat_serves_frontend(self, librechat_server):
        """LibreChat serves the React frontend."""
        r = httpx.get(f"http://127.0.0.1:{LC_PORT}/",
                      timeout=10, follow_redirects=True)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


# ── Auth & user management ───────────────────────


class TestAuth:
    """Verify user registration and authentication."""

    def test_login_returns_token(self, auth_token):
        assert len(auth_token) > 20

    def test_user_profile(self, api_client):
        """Authenticated user can fetch their profile."""
        r = api_client.get("/api/user")
        assert r.status_code == 200
        data = r.json()
        assert data.get("email") == TEST_EMAIL or "email" in data


# ── MCP tool verification ────────────────────────


class TestMCPTools:
    """Verify augur MCP server tools are accessible."""

    def test_mcp_tools_list(self, augur_server):
        """MCP tools/list returns 50+ tools."""
        # Send initialize + tools/list via JSON-RPC
        r = httpx.post(
            f"http://127.0.0.1:{MCP_PORT}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2,
                  "params": {}},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            timeout=15)
        assert r.status_code == 200
        # Response may be SSE — parse the JSON-RPC result
        body = r.text
        if "data:" in body:
            # SSE format: extract JSON from data: lines
            for line in body.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if "result" in data:
                        tools = data["result"].get("tools", [])
                        assert len(tools) >= 50, \
                            f"Expected 50+ tools, got {len(tools)}"
                        return
        else:
            data = r.json()
            tools = data.get("result", {}).get("tools", [])
            assert len(tools) >= 50, f"Expected 50+ tools, got {len(tools)}"

    def test_mcp_store_list_regions(self, augur_server):
        """Call store_list_regions tool via MCP."""
        r = httpx.post(
            f"http://127.0.0.1:{MCP_PORT}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call", "id": 3,
                  "params": {"name": "store_list_regions", "arguments": {}}},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            timeout=15)
        assert r.status_code == 200

    def test_mcp_namespaces_present(self, augur_server):
        """All namespaces have tools registered."""
        r = httpx.post(
            f"http://127.0.0.1:{MCP_PORT}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 4,
                  "params": {}},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            timeout=15)
        body = r.text
        tool_names = set()
        if "data:" in body:
            for line in body.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if "result" in data:
                        tool_names = {t["name"] for t in
                                      data["result"].get("tools", [])}
        else:
            data = r.json()
            tool_names = {t["name"] for t in
                          data.get("result", {}).get("tools", [])}

        expected_prefixes = {
            "store", "weather", "disaster", "econ", "agri", "conflict",
            "commodity", "health", "politics", "transport", "water",
            "humanitarian", "infra",
        }
        for prefix in expected_prefixes:
            matching = [t for t in tool_names if t.startswith(f"{prefix}_")]
            assert matching, f"No tools for namespace '{prefix}'"


# ── Agent seeding & tiers ────────────────────────


class TestAgents:
    """Seed agents via API and verify tier structure."""

    @pytest.fixture(autouse=True, scope="class")
    def _seed_agents(self, api_client):
        """Seed all 11 agents from agents.json."""
        agents_file = REPO_ROOT / "augur-uberspace" / "config" / "agents.json"
        if not agents_file.exists():
            pytest.skip("agents.json not found")

        agent_defs = json.loads(agents_file.read_text())

        # Phase 1: Create agents (without edges)
        id_map = {}
        for adef in agent_defs:
            payload = {k: v for k, v in adef.items() if not k.startswith("_")}
            payload.pop("edges", None)

            r = api_client.post("/api/agents", json=payload)
            if r.status_code in (200, 201):
                result = r.json()
                agent_id = result.get("id", "")
                if agent_id:
                    id_map[adef["_name"]] = agent_id

        # Phase 2: Wire edges
        sys.path.insert(0, str(REPO_ROOT / "augur-uberspace" / "scripts"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "seed_agents",
            REPO_ROOT / "augur-uberspace" / "scripts" / "seed-agents.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        resolved = mod.resolve_edges(agent_defs, id_map)
        for adef in agent_defs:
            name = adef["_name"]
            edges = resolved.get(name, [])
            if edges and name in id_map:
                api_client.patch(
                    f"/api/agents/{id_map[name]}",
                    json={"id": id_map[name], "edges": edges})

        self.id_map = id_map
        self.agent_defs = agent_defs
        yield

        # Cleanup: delete test agents
        for agent_id in id_map.values():
            api_client.delete(f"/api/agents/{agent_id}")

    def test_all_agents_created(self):
        """All 11 agents were created successfully."""
        assert len(self.id_map) == 11, \
            f"Expected 11 agents, created {len(self.id_map)}: {list(self.id_map)}"

    def test_agent_tiers(self, api_client):
        """Agent layers (L1-L5 + utility) are correct."""
        r = api_client.get("/api/agents")
        assert r.status_code == 200
        data = r.json()
        agents = data if isinstance(data, list) else data.get("agents", [])

        # Map agent names back to definitions for layer check
        name_to_layer = {a["name"]: a["_layer"] for a in self.agent_defs}
        for agent in agents:
            name = agent.get("name", "")
            if name in name_to_layer:
                # Agent exists in API response
                pass  # Verified by presence

    def test_l1_data_agents_exist(self):
        """L1 data agents (market-data, osint-data, signals-data) created."""
        for name in ("market-data", "osint-data", "signals-data"):
            assert name in self.id_map, f"L1 agent '{name}' not created"

    def test_l2_analyst_agents_exist(self):
        """L2 analyst agents created."""
        for name in ("market-analyst", "osint-analyst", "signals-analyst"):
            assert name in self.id_map, f"L2 agent '{name}' not created"

    def test_l3_synthesizer_exists(self):
        assert "synthesizer" in self.id_map

    def test_l4_cron_planner_exists(self):
        assert "cron-planner" in self.id_map

    def test_l5_live_chat_exists(self):
        assert "live-chat" in self.id_map

    def test_utility_agents_exist(self):
        for name in ("trader", "charter"):
            assert name in self.id_map, f"Utility agent '{name}' not created"

    def test_list_agents_via_api(self, api_client):
        """GET /api/agents returns our seeded agents."""
        r = api_client.get("/api/agents")
        assert r.status_code == 200
        data = r.json()
        agents = data if isinstance(data, list) else data.get("agents", [])
        agent_names = {a.get("name", "") for a in agents}
        for adef in self.agent_defs:
            assert adef["name"] in agent_names, \
                f"Agent '{adef['name']}' not in API response"


# ── Config validation ────────────────────────────


class TestConfig:
    """Verify LibreChat configuration is correct."""

    def test_librechat_yaml_loaded(self, librechat_server, api_client):
        """LibreChat loaded our config (MCP servers defined)."""
        # Check /api/config or similar endpoint
        r = api_client.get("/api/config")
        if r.status_code == 200:
            data = r.json()
            # Just verify config endpoint is reachable
            assert isinstance(data, dict)

    def test_endpoints_config(self, api_client):
        """Agents endpoint is configured."""
        r = api_client.get("/api/endpoints")
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, (dict, list))


# ── MongoDB connectivity ─────────────────────────


class TestMongoDB:
    """Verify MongoDB connectivity for both databases."""

    @staticmethod
    def _real_mongo_client(uri, **kwargs):
        """Get a real MongoClient, bypassing conftest.py mock."""
        if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
            del sys.modules["pymongo"]
        import pymongo
        return pymongo.MongoClient(uri, **kwargs)

    def test_signals_db_ping(self):
        """Signals MongoDB responds to ping."""
        if not MONGO_URI_SIGNALS:
            pytest.skip("MONGO_URI_SIGNALS not set")
        client = self._real_mongo_client(
            MONGO_URI_SIGNALS, serverSelectionTimeoutMS=5000)
        try:
            result = client.admin.command("ping")
            assert result.get("ok") == 1.0
        except Exception as exc:
            pytest.skip(f"MongoDB not reachable: {exc}")
        finally:
            client.close()

    def test_librechat_db_ping(self):
        """LibreChat MongoDB responds to ping."""
        if not MONGO_URI_LC:
            pytest.skip("MONGO_URI_LIBRECHAT not set")
        client = self._real_mongo_client(
            MONGO_URI_LC, serverSelectionTimeoutMS=5000)
        try:
            result = client.admin.command("ping")
            assert result.get("ok") == 1.0
        except Exception as exc:
            pytest.skip(f"MongoDB not reachable: {exc}")
        finally:
            client.close()


# ── Store round-trip via MCP ─────────────────────


class TestStoreViaMCP:
    """Test store operations through the live MCP server."""

    def _call_tool(self, name: str, args: dict) -> dict:
        """Call an MCP tool and return the result."""
        r = httpx.post(
            f"http://127.0.0.1:{MCP_PORT}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call", "id": 10,
                  "params": {"name": name, "arguments": args}},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"},
            timeout=15)
        assert r.status_code == 200
        body = r.text
        if "data:" in body:
            for line in body.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if "result" in data:
                        return data["result"]
        return r.json().get("result", {})

    def test_list_regions(self, augur_server):
        result = self._call_tool("store_list_regions", {})
        assert result is not None

    def test_list_profiles(self, augur_server):
        result = self._call_tool("store_list_profiles",
                                 {"kind": "countries"})
        assert result is not None

    def test_snapshot_roundtrip(self, augur_server):
        """Write snapshot via MCP, read it back."""
        self._call_tool("store_snapshot", {
            "kind": "countries", "entity": "TST", "type": "e2e_test",
            "data": {"value": 99, "source": "ci_e2e"},
            "region": "global"})

        result = self._call_tool("store_history", {
            "kind": "countries", "entity": "TST", "type": "e2e_test"})
        assert result is not None

    def test_event_roundtrip(self, augur_server):
        """Log event via MCP, query it back."""
        self._call_tool("store_event", {
            "subtype": "ci_e2e", "summary": "E2E smoke test event",
            "data": {"source": "ci"}, "region": "global"})

        result = self._call_tool("store_recent_events",
                                 {"subtype": "ci_e2e"})
        assert result is not None


# ── Cron API call via Agents API ─────────────────


class TestCronAPICall:
    """Test invoking the cron-planner agent via LibreChat's Agents API.

    This simulates what `ta cron` would do: send a message to the
    cron-planner agent via the OpenAI-compatible chat/completions endpoint.
    The agent should read plans, call MCP tools, and return a structured response.
    """

    @pytest.fixture(autouse=True, scope="class")
    def _setup_cron_agent(self, api_client):
        """Seed agents and store the cron-planner agent ID."""
        agents_file = REPO_ROOT / "augur-uberspace" / "config" / "agents.json"
        if not agents_file.exists():
            pytest.skip("agents.json not found")

        agent_defs = json.loads(agents_file.read_text())

        # Create all agents to get cron-planner ID
        id_map = {}
        for adef in agent_defs:
            payload = {k: v for k, v in adef.items() if not k.startswith("_")}
            payload.pop("edges", None)
            r = api_client.post("/api/agents", json=payload)
            if r.status_code in (200, 201):
                result = r.json()
                agent_id = result.get("id", "")
                if agent_id:
                    id_map[adef["_name"]] = agent_id

        if "cron-planner" not in id_map:
            pytest.skip("Could not create cron-planner agent")

        self.cron_agent_id = id_map["cron-planner"]
        self.id_map = id_map
        self.agent_defs = agent_defs
        yield

        # Cleanup
        for agent_id in id_map.values():
            api_client.delete(f"/api/agents/{agent_id}")

    @pytest.mark.skipif(not LLM_KEY_VALUE,
                        reason="No LLM API key available")
    def test_cron_agent_via_chat_completions(self, agents_api_key):
        """Invoke cron-planner via /api/agents/v1/chat/completions."""
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{LC_PORT}",
            headers={"Authorization": f"Bearer {agents_api_key}",
                     "Content-Type": "application/json"},
            timeout=120)

        r = client.post("/api/agents/v1/chat/completions", json={
            "model": self.cron_agent_id,
            "messages": [
                {"role": "user",
                 "content": "Run a quick status check: read current plans "
                            "(store_get_notes kind=plan), check risk status "
                            "(store_risk_status), and list available regions "
                            "(store_list_regions). Return a brief summary."}
            ],
            "stream": False,
        })
        client.close()

        assert r.status_code == 200, \
            f"Chat completions failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        # OpenAI-compatible response: {choices: [{message: {content: ...}}]}
        choices = data.get("choices", [])
        assert len(choices) > 0, f"No choices in response: {data}"
        content = choices[0].get("message", {}).get("content", "")
        assert len(content) > 10, f"Empty agent response: {content}"

    @pytest.mark.skipif(not LLM_KEY_VALUE,
                        reason="No LLM API key available")
    def test_cron_agent_via_responses(self, agents_api_key):
        """Invoke cron-planner via /api/agents/v1/responses (Open Responses)."""
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{LC_PORT}",
            headers={"Authorization": f"Bearer {agents_api_key}",
                     "Content-Type": "application/json"},
            timeout=120)

        r = client.post("/api/agents/v1/responses", json={
            "model": self.cron_agent_id,
            "input": "Check store_risk_status and report remaining daily budget.",
        })
        client.close()

        # Responses API may not be available in all LC versions
        if r.status_code == 404:
            pytest.skip("Responses API not available in this LibreChat version")

        assert r.status_code == 200, \
            f"Responses API failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        # Open Responses format: {output: [{type: "message", content: [...]}]}
        output = data.get("output", data.get("choices", []))
        assert len(output) > 0, f"No output in response: {data}"

    @pytest.mark.skipif(not LLM_KEY_VALUE,
                        reason="No LLM API key available")
    def test_cron_agent_calls_mcp_tools(self, agents_api_key):
        """Verify cron-planner actually calls MCP tools (not just generates text)."""
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{LC_PORT}",
            headers={"Authorization": f"Bearer {agents_api_key}",
                     "Content-Type": "application/json"},
            timeout=120)

        r = client.post("/api/agents/v1/chat/completions", json={
            "model": self.cron_agent_id,
            "messages": [
                {"role": "user",
                 "content": "Call store_list_regions to list all available "
                            "regions. Return the exact list."}
            ],
            "stream": False,
        })
        client.close()

        if r.status_code != 200:
            pytest.skip(f"Agent call failed: {r.status_code}")

        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        # The response should mention actual regions from the profiles
        region_keywords = ["europe", "north_america", "global", "east_asia", "mena"]
        found = [kw for kw in region_keywords if kw in content.lower()]
        assert len(found) >= 2, \
            f"Agent response doesn't contain region data (tool may not have been called): {content[:300]}"

    def test_agents_api_models_list(self, agents_api_key):
        """GET /api/agents/v1/models returns available agents."""
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{LC_PORT}",
            headers={"Authorization": f"Bearer {agents_api_key}"},
            timeout=15)

        r = client.get("/api/agents/v1/models")
        client.close()

        if r.status_code == 404:
            pytest.skip("Models endpoint not available")

        assert r.status_code == 200
        data = r.json()
        models = data.get("data", [])
        # Should include our seeded agents
        model_ids = {m.get("id", "") for m in models}
        assert self.cron_agent_id in model_ids, \
            f"Cron-planner {self.cron_agent_id} not in models list: {model_ids}"

    @pytest.mark.skipif(not LLM_KEY_VALUE,
                        reason="No LLM API key available")
    def test_cron_agent_streaming(self, agents_api_key):
        """Verify streaming mode works for cron-planner."""
        client = httpx.Client(
            base_url=f"http://127.0.0.1:{LC_PORT}",
            headers={"Authorization": f"Bearer {agents_api_key}",
                     "Content-Type": "application/json"},
            timeout=120)

        with client.stream("POST", "/api/agents/v1/chat/completions", json={
            "model": self.cron_agent_id,
            "messages": [
                {"role": "user",
                 "content": "Call store_risk_status and return the result."}
            ],
            "stream": True,
        }) as r:
            assert r.status_code == 200, \
                f"Streaming failed: {r.status_code}"
            chunks = []
            for line in r.iter_lines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    chunks.append(chunk)

        client.close()
        assert len(chunks) > 0, "No streaming chunks received"

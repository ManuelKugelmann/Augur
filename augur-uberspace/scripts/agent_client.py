"""Shared LibreChat Agents API client.

Used by cron dispatcher, trigger command, and bootstrap-data.py
to avoid duplicating agent discovery, streaming, and .env loading.

Usage:
    from agent_client import AgentClient

    client = AgentClient("http://localhost:3080", api_key="sk-...")
    agent_id = client.find_agent("cron-planner")
    result = client.invoke(agent_id, "Do your thing", timeout=300)
    print(result["content"])
    client.close()
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

# Retry config for rate-limited requests
MAX_RETRIES = 4
BACKOFF_BASE = 2  # seconds: 2, 4, 8, 16


def load_env(env_file: str | None = None) -> None:
    """Load .env file into os.environ (best-effort, no hard dotenv dependency).

    Skips keys already present in the environment.
    """
    if env_file is None:
        # Default: ~/augur/.env (works both from repo and from installed location)
        env_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        )
    if not os.path.isfile(env_file):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        return
    except ImportError:
        pass
    # Fallback: simple KEY=VALUE parser
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


class AgentClient:
    """Lightweight LibreChat Agents API client with discovery and streaming."""

    def __init__(self, base_url: str, api_key: str):
        if httpx is None:
            raise ImportError("httpx required. Install: pip install httpx")
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._agents: dict[str, dict] | None = None

    def _fetch_agents(self) -> dict[str, dict]:
        """Fetch agent list from /api/agents/v1/models. Cached after first call."""
        if self._agents is not None:
            return self._agents
        resp = httpx.get(
            f"{self.base_url}/api/agents/v1/models",
            headers=self.headers,
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Agent list failed: HTTP {resp.status_code}")
        self._agents = {m["id"]: m for m in resp.json().get("data", [])}
        return self._agents

    def find_agent(self, name_match: str) -> str | None:
        """Find agent ID by substring match on id or display name.

        Returns agent_id string or None.
        """
        agents = self._fetch_agents()
        for aid, m in agents.items():
            if name_match in aid.lower() or name_match in m.get("name", "").lower():
                return aid
        return None

    def list_agents(self) -> dict[str, str]:
        """Return {agent_id: display_name} for all agents."""
        agents = self._fetch_agents()
        return {aid: m.get("name", aid) for aid, m in agents.items()}

    def invoke(
        self,
        agent_id: str,
        message: str,
        timeout: int = 300,
        log_file: str | None = None,
        stream_to_stdout: bool = False,
    ) -> dict:
        """Invoke an agent via chat/completions streaming endpoint.

        Args:
            agent_id: Agent model ID (from find_agent).
            message: User message to send.
            timeout: Request timeout in seconds.
            log_file: Optional path to write full response log.
            stream_to_stdout: If True, print response text as it arrives.

        Returns:
            {"status": "ok"|"error"|"timeout", "content": str, "usage": dict}
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        content_parts: list[str] = []
        usage: dict = {}
        log_fh = None

        for attempt in range(MAX_RETRIES + 1):
            content_parts = []
            usage = {}

            try:
                if log_file:
                    mode = "w" if attempt == 0 else "a"
                    os.makedirs(os.path.dirname(log_file), exist_ok=True)
                    log_fh = open(log_file, mode)
                    if attempt == 0:
                        log_fh.write(f"[{ts}] agent_id={agent_id}\n")
                        log_fh.write(f"[{ts}] prompt: {message}\n")
                        log_fh.write(f"{'=' * 60}\n")
                    else:
                        log_fh.write(f"\n[{ts}] retry {attempt}/{MAX_RETRIES}\n")

                with httpx.stream(
                    "POST",
                    f"{self.base_url}/api/agents/v1/chat/completions",
                    headers=self.headers,
                    json={
                        "model": agent_id,
                        "messages": [{"role": "user", "content": message}],
                        "stream": True,
                    },
                    timeout=timeout,
                ) as resp:
                    if resp.status_code == 429 and attempt < MAX_RETRIES:
                        # Rate limited — backoff and retry
                        wait = BACKOFF_BASE ** (attempt + 1)
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            wait = max(wait, int(retry_after))
                        print(f"    Rate limited (429), retrying in {wait}s "
                              f"(attempt {attempt + 1}/{MAX_RETRIES})",
                              file=sys.stderr)
                        if log_fh:
                            log_fh.close()
                            log_fh = None
                        time.sleep(wait)
                        continue

                    if resp.status_code != 200:
                        error_body = ""
                        for chunk in resp.iter_text():
                            error_body += chunk
                        if resp.status_code >= 500 and attempt < MAX_RETRIES:
                            wait = BACKOFF_BASE ** (attempt + 1)
                            print(f"    Server error ({resp.status_code}), retrying in {wait}s "
                                  f"(attempt {attempt + 1}/{MAX_RETRIES})",
                                  file=sys.stderr)
                            if log_fh:
                                log_fh.close()
                                log_fh = None
                            time.sleep(wait)
                            continue
                        return {"status": "error", "content": "",
                                "error": f"HTTP {resp.status_code}: {error_body[:500]}"}

                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    content_parts.append(text)
                                    if stream_to_stdout:
                                        sys.stdout.write(text)
                                        sys.stdout.flush()
                                    if log_fh:
                                        log_fh.write(text)
                                        log_fh.flush()
                            if "usage" in chunk:
                                usage = chunk["usage"]
                        except json.JSONDecodeError:
                            pass

                if log_fh:
                    log_fh.write(f"\n{'=' * 60}\n[{ts}] done\n")

                return {"status": "ok", "content": "".join(content_parts), "usage": usage}

            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    print(f"    Timeout, retrying in {wait}s "
                          f"(attempt {attempt + 1}/{MAX_RETRIES})",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                return {"status": "timeout", "content": "".join(content_parts),
                        "error": "Request timed out", "usage": usage}
            except httpx.HTTPError as e:
                if attempt < MAX_RETRIES:
                    wait = BACKOFF_BASE ** (attempt + 1)
                    print(f"    Network error, retrying in {wait}s "
                          f"(attempt {attempt + 1}/{MAX_RETRIES})",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                return {"status": "error", "content": "".join(content_parts),
                        "error": str(e), "usage": usage}
            finally:
                if log_fh:
                    log_fh.close()
                    log_fh = None

        return {"status": "error", "content": "", "error": "Max retries exceeded"}

    def close(self):
        """No-op for compatibility (httpx calls are per-request)."""
        pass
